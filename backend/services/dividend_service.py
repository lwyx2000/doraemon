"""红利策略研究服务：红利指数估值 + 全市场红利基金名录。

数据源（全部经 aksharewebapi 的 ``/api/ak`` 通用代理）：
- ``stock_zh_index_hist_csindex``  ：指数日频收盘 + 滚动市盈率（2016 至今，约 2600 行）
- ``stock_zh_index_value_csindex`` ：中证官方估值（股息率1 / 市盈率1，最近约 20 个交易日）
- ``fund_name_em``                 ：全市场公募基金名录（约 2.8 万条）
- 10Y 国债收益率：复用 ``services.market_service._fetch_10y_history``

设计原则：
- 全部真实数据；取数失败返回 None / 空列表，**绝不使用 mock 填充**。
- 指数估值与基金名录分别缓存（前者 6h、后者 24h），避免每次请求重复拉取 5MB 名录。
- 仓位信号按**指标维度独立给出**（股债收益比 / PE 分位 / 股息率），**不做综合裁决**，
  由使用者自行权衡。阈值常量见 ``SIGNAL_*``，口径来自两篇红利策略研究文档。
"""

from __future__ import annotations

import bisect
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone

from services.akshare_client import akshare_request
from services import fund_fee_service, fund_index_map_service, index_compilation_service
from services import fund_extra_metrics_service

#: 展示统一用北京时间（容器时区为 UTC）
CST = timezone(timedelta(hours=8))

# ============================================================
# 常量
# ============================================================

#: PE 历史窗口起点（近 10 年，与文档「近10年分位」口径一致）
HIST_START = "20160101"

#: 红利指数宇宙：(代码, 中文简称, 区域, 名称别名)
#:   区域 ``A``=A股 / ``HK``=港股 / ``SHS``=沪港深跨市场（决定基金名能否匹配该指数）
#: ⚠️ 顺序即优先级（别名长度相同时按此顺序），越靠前越优先匹配。
#:   例如「中证红利低波动」必须命中 930955/H30269 而不是被「中证红利」抢走。
#: 代码均取自中证指数公司全量指数表（akshare ``index_csindex_all``）。
DIVIDEND_INDICES: list[tuple[str, str, str, list[str]]] = [
    # ---- A 股 ----
    ("932422", "A500红利低波", "A", ["A500红利低波"]),
    ("930955", "红利低波100", "A", ["红利低波动100", "红利低波100"]),
    ("931848", "800红利低波", "A", ["800红利低波"]),
    ("930740", "300红利低波", "A", ["300红利低波"]),
    ("931231", "央企红利50", "A", ["央企红利50"]),
    ("931130", "红利成长低波", "A", ["红利成长低波"]),
    ("H30269", "红利低波", "A", ["红利低波动", "红利低波"]),
    ("932154", "A500红利", "A", ["A500红利"]),
    ("931644", "800红利", "A", ["800红利"]),
    ("000821", "300红利", "A", ["沪深300红利", "300红利"]),
    ("000824", "国企红利", "A", ["国企红利"]),
    ("000825", "央企红利", "A", ["央企红利"]),
    ("931468", "红利质量", "A", ["红利质量"]),
    ("H30270", "红利价值", "A", ["红利价值"]),
    ("H30089", "红利潜力", "A", ["红利潜力"]),
    ("H30094", "消费红利", "A", ["消费红利"]),
    ("000015", "上证红利", "A", ["上证红利"]),
    ("000922", "中证红利", "A", ["中证红利"]),
    # ---- 港股 ----
    ("932596", "港股通红利低波", "HK", ["港股通红利低波", "港股红利低波"]),
    ("932584", "智选港股通红利低波", "HK", ["智选港股通红利低波"]),
    ("931722", "国新港股通央企红利", "HK", ["国新港股通央企红利"]),
    ("931233", "港股通央企红利", "HK", ["港股通央企红利", "港股央企红利"]),
    ("930914", "港股通高股息", "HK", ["港股通高股息", "港股高股息"]),
    ("H11140", "香港红利", "HK", ["香港红利"]),
    # ---- 沪港深跨市场 ----
    ("931157", "沪港深红利成长低波", "SHS", ["沪港深红利成长低波"]),
    ("930992", "沪港深红利低波", "SHS", ["沪港深红利低波"]),
    # ---- 池外扩展（2026-10-06：基金「跟踪标的 / 业绩比较基准」原文反查得到）----
    # ⚠️ 这些指数中证站/行情接口取不到估值，页面对应列显示 —，但基金→指数映射能命中，
    #    因此不再是「— 无跟踪指数」，弹窗可正常展示跟踪基金清单。
    ("399324", "深证红利", "A", ["深证红利"]),
    ("932305", "智选高股息", "A", ["智选高股息"]),
    ("931053", "高股息策略", "A", ["高股息策略"]),
    ("930836", "沪港深高股息", "SHS", ["沪港深高股息", "沪港深高股息精选"]),
    ("CESFHY", "中华预期高股息", "A", ["中华预期高股息", "中华交易服务预期高股息"]),
    ("995082", "华证龙头红利50", "A", ["华证龙头红利50"]),
    ("995128", "华证沪深港红利50", "A", ["华证沪深港红利50"]),
    ("995127", "华证沪港深红利100", "SHS", ["华证沪港深红利100"]),
    ("SPAHLVCP", "标普港股通低波红利", "HK", ["标普港股通低波红利", "标普港股通低波动红利"]),
    ("HSSCHKY", "恒生港股通红利", "HK", ["恒生港股通红利"]),
    ("932039", "央企股东回报", "A", ["央企股东回报", "国新央企股东回报"]),
    ("930838", "中证高股息精选", "A", ["中证高股息精选", "CS高股息", "中证高股息精选指数"]),
    ("SPCADMCP", "标普中国A股红利100", "A", ["标普中国A股红利100", "标普A股红利100"]),
    ("spdjicspsadrp", "标普中国A股红利机会", "A", ["标普中国A股红利机会", "标普A股红利"]),
    ("HSMCHYI", "恒生港股通中国内地企业红利", "HK", ["恒生港股通中国内地企业红利", "恒生港股通中国内地企业高股息率", "恒生中国内地企业高股息率"]),
    ("hkH11153", "中证香港内地国有企业", "HK", ["中证香港内地国有企业", "香港内地国有企业", "内地国有"]),
    ("GPCCH003.FI", "富时中国国企开放共赢", "A", ["富时中国国企开放共赢", "国企开放共赢"]),
    # 2026-10-06：002011 华夏红利混合的业绩比较基准「新华富时150红利指数」。
    # 该指数 2010-12-16 随富时全资收购新华富时而更名「富时中国A股红利150指数」
    # （FTSE China A High Yield 150，富时罗素 factsheet issueName=XH150CH）；
    # 库里 002011 存的仍是旧名文本，故别名两套都要留。
    ("XH150CH", "富时中国A股红利150", "A",
     ["富时中国A股红利150", "新华富时150红利", "新华富时红利150", "富时中国A150"]),
]

#: 基金名称中的港股关键词（决定该基金只能匹配 HK 系指数）
HK_NAME_KEYWORDS = ("港股", "恒生", "香港")

#: 少数名称里看不出跟踪指数、但市场共识明确的产品，人工兜底映射
FUND_INDEX_OVERRIDES: dict[str, str] = {
    "510880": "000015",  # 红利ETF华泰柏瑞 → 上证红利
    "515180": "000922",  # 红利ETF易方达 → 中证红利
    # 2026-10-06：基金名含「国企红利」但跟踪的是富时系，别被 000824 的泛化别名抢走
    "019259": "GPCCH003.FI",  # 国泰富时国企红利ETF联接A
    "019269": "GPCCH003.FI",  # 国泰富时国企红利ETF联接C
}

#: 基金名称命中任一关键词即视为「红利基金」
FUND_NAME_KEYS = ("红利", "高股息", "股息")

#: 现金流基金名称关键词（2026-10-07 用户拍板：**单开一条现金流 Tab，不动红利名录**）。
#:
#: ⚠️ 与红利名录**完全独立**：红利闸门只认「红利/高股息/股息」，会把 159399「现金流ETF国泰」
#:    挡掉（走 no_name_hit 分支静默消失、且不计入 excluded）。自由现金流 / 现金流是**另一条
#:    因子线**（自由现金流 vs 股息率），用户口径是「红利页保持纯净，现金流另开一条」——
#:    所以这里另起一套闸门，绝不去改 FUND_NAME_KEYS（那会污染 361 只红利名录的口径）。
CASHFLOW_NAME_KEYS = ("现金流",)

#: 现金流指数池 —— **只服务现金流 Tab，红利 ``DIVIDEND_INDICES`` 一个字都没动**。
#:
#: ⚠️ 指数代码全部来自权威公开源交叉核实（2026-10-07 取证），**没有一个是推断出来的**：
#:   - 国金证券 ETF 投资手册：932366 沪深300 / 932367 中证500 / 932368 中证800 / 932369 中证1000
#:   - 国信证券研报(2025-06-08) + 富国 563990 招募说明书(2026-03-18)：932368 中证800自由现金流
#:   - 广发基金《都叫"自由现金流"，这3个指数区别在哪》：932365 中证全指 / 980092 国证
#:   - 天天基金 F10「跟踪标的」逐只实测 + A股基本信息表「ETF跟踪指数代码」字段（sh560120→cs932367）
#: 富时中国A股自由现金流聚焦指数（159399 跟踪）**没有公开通用代码** → 代码留空只填名称，绝不编。
CASHFLOW_INDICES: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("932365", "中证全指自由现金流指数", "CN",
     ("中证全指自由现金流", "中证全指现金流", "全指现金流", "中证现金流")),
    ("932366", "沪深300自由现金流指数", "CN",
     ("沪深300自由现金流", "300自由现金流", "300现金流", "沪深300现金流")),
    ("932367", "中证500自由现金流指数", "CN",
     ("中证500自由现金流", "500自由现金流", "500现金流", "中证500现金流")),
    ("932368", "中证800自由现金流指数", "CN",
     ("中证800自由现金流", "800自由现金流", "800现金流", "中证800现金流")),
    ("932369", "中证1000自由现金流指数", "CN",
     ("中证1000自由现金流", "1000自由现金流", "1000现金流", "中证1000现金流")),
    ("980092", "国证自由现金流指数", "CN",
     ("国证自由现金流", "国证现金流", "国证自由现金")),
    ("", "富时中国A股自由现金流聚焦指数", "CN",
     ("富时中国A股自由现金流聚焦", "富时中国A股自由现金流")),
]

#: 场内现金流 ETF → 跟踪指数（**天天基金 F10「跟踪标的」逐只实测结果**，2026-10-07）。
#:
#: ⚠️ 为什么必须有这张静态表：**基金简称里看不出跟的是国证还是中证系列**——
#: 「自由现金流ETF华夏」「现金流ETF国泰」名字里没有任何指数线索，只有 F10 的「跟踪标的」
#: 才会写死「国证自由现金流指数」还是「中证全指自由现金流指数」。所以这一层是主路径，
#: ``CASHFLOW_INDICES`` 词表只作未来新增 ETF 的兜底（F10 原文含指数全称时能命中）。
#: 代码一律取自上表核实值，全市场只有 159399 那只富时指数拿不到公开代码 → 代码留空。
CASHFLOW_INDEX_OVERRIDES: dict[str, tuple[str, str | None]] = {
    "159119": ("932368", "中证800自由现金流指数"),
    "159166": ("980092", "国证自由现金流指数"),
    "159201": ("980092", "国证自由现金流指数"),
    "159221": ("980092", "国证自由现金流指数"),
    "159222": ("980092", "国证自由现金流指数"),
    "159223": ("980092", "国证自由现金流指数"),
    "159225": ("980092", "国证自由现金流指数"),
    "159229": ("932368", "中证800自由现金流指数"),
    "159232": ("932365", "中证全指自由现金流指数"),
    "159233": ("932365", "中证全指自由现金流指数"),
    "159235": ("932365", "中证全指自由现金流指数"),
    "159236": ("932365", "中证全指自由现金流指数"),
    "159276": ("980092", "国证自由现金流指数"),
    # 159399 现金流ETF国泰 → 富时中国A股自由现金流聚焦指数（无公开代码，只填名称）
    "159399": ("", "富时中国A股自由现金流聚焦指数"),
    "512130": ("932365", "中证全指自由现金流指数"),
    "516040": ("932366", "沪深300自由现金流指数"),
    "516460": ("932368", "中证800自由现金流指数"),
    "560120": ("932367", "中证500自由现金流指数"),
    "561080": ("932365", "中证全指自由现金流指数"),
    "561420": ("932366", "沪深300自由现金流指数"),
    "561870": ("932365", "中证全指自由现金流指数"),
    "562080": ("932366", "沪深300自由现金流指数"),
    "562170": ("932366", "沪深300自由现金流指数"),
    "563390": ("932365", "中证全指自由现金流指数"),
    "563580": ("932368", "中证800自由现金流指数"),
    "563620": ("932365", "中证全指自由现金流指数"),
    "563680": ("932368", "中证800自由现金流指数"),
    "563760": ("932365", "中证全指自由现金流指数"),
    "563770": ("932365", "中证全指自由现金流指数"),
    "563780": ("932365", "中证全指自由现金流指数"),
    "563830": ("932365", "中证全指自由现金流指数"),
    "563900": ("932366", "沪深300自由现金流指数"),
    "563990": ("932368", "中证800自由现金流指数"),
}

#: 现金流名录缓存（TTL 比红利短：新产品发行快，6 小时即可见新 ETF）
_CASHFLOW_CACHE: dict = {"data": None, "ts": 0}
CASHFLOW_CACHE_TTL = 6 * 3600
_LAST_CASHFLOW_EXCLUDED: dict[str, int] = {}

#: 现金流指数估值缓存（独立一块，与红利的 _INDEX_CACHE 互不影响）
_CASHFLOW_INDEX_CACHE: dict = {"data": None, "ts": 0}

#: 「中证未发布官方股息率」的说明（现金流类指数不是股息导向，中证不披露该指标；
#: 且 ``stock_zh_index_value_csindex`` 当前上游 500，连中证红利 000922 都取不到 → 不硬凑）
CF_DY_UNAVAILABLE_REASON = (
    "中证未发布该类指数的官方股息率（自由现金流 ≠ 股息导向）；"
    "且官方估值接口 stock_zh_index_value_csindex 当前上游不可用"
)

#: 明确排除的基金类型（货币基金虽名字带红利，但不是红利策略产品；
#: 债券型同理——名字带「红利/双息/信用红利」但本质是纯债、没有股票持仓，
#: 放进红利名录只会污染「红利基金持仓」与「跟踪指数」两块的口径）。
EXCLUDED_FUND_TYPES = ("货币型", "债券型")

#: 唯一准入的基金类型前缀：**只有被动指数型**进红利名录。
#:
#: ⚠️ 用户口径（2026-10-06 拍板）：「纯债 / 主动不进红利名录」。
#: 东财「基金类型」字段里，主动管理产品的取值是 混合型-偏股 / 混合型-灵活 /
#: 股票型 / QDII-混合偏股 等，指数产品一律以「指数型」开头——用它做准入比
#: 逐个罗列主动类型更稳（主动产品的分类名会变，指数型的命名永远不会变）。
PASSIVE_TYPE_PREFIX = ("指数型",)

#: 最近一次名录构建时被闸门剔除的计数（按原因分桶），供 overview 展示。
#: 注意：这是**读时统计**，只在 _build_fund_list 真正跑过（缓存未命中/force）后才刷新。
_LAST_EXCLUDED: dict[str, int] = {}

#: 缓存 TTL（秒）
INDEX_CACHE_TTL = 6 * 3600

#: 指数指标构建的**整体时间预算**（秒）。
#: 超过则放弃未完成的，用本地缓存兜底 —— 保证 HTTP 请求不会无限等。
#: 实测：上游与回填 job 并发时，逐个 fut.result() 无超时会把请求拖到 >150s。
INDEX_BUILD_BUDGET_S = 60
FUND_CACHE_TTL = 24 * 3600

#: 估值（股息率）接口失败后的静默期（秒）。
#: ⚠️ 中证 csindex 对并发/高频请求会返回 403 封禁一段时间；失败后必须静默，
#:   否则每次刷新页面都重试 26 个指数，会把封禁越拖越久（并连累共用 aksharewebapi 的其他功能）。
VALUE_FAIL_TTL = 30 * 60
_VALUE_FAIL_AT: dict[str, float] = {}

#: 最近一次取到的股息率（code -> (dy, dy_date)），上游封禁期间用于「沿用最后一期」
_DY_LAST: dict[str, tuple[float | None, str | None]] = {}
_DY_LOADED = False

#: 股息率落库表（上游 403 封禁 / 进程重启时兜底，避免整列变空）
DY_DDL = """
CREATE TABLE IF NOT EXISTS base_dividend_index_dy (
    code          VARCHAR PRIMARY KEY,
    name          VARCHAR,
    dy            DOUBLE,
    dy_date       VARCHAR,
    updated_at    TIMESTAMP
)
"""

#: PE 日频序列落库表（2026-10-08）
#:
#: 背景：PE 分位/区间依赖**全量历史**（pe_percentile/pe_min/pe_max/pe_p25/pe_median/
#: pe_p75/window_days 全部由全历史排序算出，window_days 实测 2613 天），而原实现每次
#: 都实时抓中证官网 `stock_zh_index_hist_csindex`，导致三个问题：
#:   ① 中证官网长期限流（返回非 JSON → JSONDecodeError，10-06 报错 2300+ 次）
#:   ② 6 并发批量构建时可能返回「行存在但 PE 列全空」的中间态，且**不抛异常**
#:   ③ 整批失败后_INDEX_CACHE 的`if indices:` 判空会让**空结果被缓存冻住 6 小时**
#: 本地表落地后：分位计算不再依赖实时抓取，上游全挂时仍可显示历史分位。
PE_DDL = """
CREATE TABLE IF NOT EXISTS base_dividend_index_pe (
    code          VARCHAR NOT NULL,
    trade_date    VARCHAR NOT NULL,
    pe            DOUBLE,
    updated_at    TIMESTAMP,
    PRIMARY KEY (code, trade_date)
)
"""

#: PE 序列本地缓存（进程内，避免每次都查 DuckDB）
_PE_CACHE: dict[str, list[tuple[str, float]]] = {}
_PE_CACHE_LOADED = False

#: 各指数最近一次回填失败的原因（区分「限流，可重试」vs「不覆盖，别浪费配额」）
#: 见 ``_pe_refresh`` —— 两者都曾返回 0，导致日志与判断都含混。
_PE_LAST_ERROR: dict[str, str] = {}

#: 距今多少天以内算「新鲜」（超过则打pe_stale 标记，前端可提示）
#: ⚠️ 仅作为**交易日历不可用时**的兜底（自然日）。
PE_STALE_DAYS = 5
#: 落后多少个**交易日**算陈旧（主判据，按交易日历比）。
#: 用 `>=` 语义：缺 1 个交易日即陈旧 → 阈值设为 1。
#: ⚠️ 中证 PE 通常**次日**才更新，故缺 1 天仍属正常，不标 stale。
PE_STALE_TRADE_DAYS = 1

#: 请求路径首次兜底时只拉最近多少天（**不要改成全量**）。
#: 全量回填是 job 的职责；在 overview 请求里拉 44×2613 行会把请求拖到数分钟。
PE_TAIL_DAYS = 30

# ---- 仓位信号阈值（来源：两篇红利策略研究文档）----
# 股债收益比 = 股息率 / 10年期国债收益率
EB_ADD = 3.0        # >= 3.0 可适当加仓
EB_LOW = 2.5        # 2.5~3.0 低估区间，可持有
EB_RISK = 1.5       # < 1.5 风险区间，考虑减仓
# PE 历史分位
PE_REDUCE = 90.0    # > 90% 可考虑减仓
PE_STOP = 80.0      # > 80% 停止加仓（不清仓，新增资金转向更低估品种）
PE_ADD = 20.0       # < 20% 可加仓
# 股息率（%）
DY_HOLD = 4.0       # > 4% 正常持有
DY_STOP = 3.5       # 3.5~4% 停止加仓但不减仓；< 3.5% 减仓 3 成转宽基

#: 动作元信息（颜色遵循 A 股习惯：红=加仓/看多，绿=减仓/看空）
ACTION_META: dict[str, dict[str, str]] = {
    "add": {"label": "加仓", "color": "#d03050"},
    "hold_low": {"label": "低估·持有", "color": "#2b7fd4"},
    "hold": {"label": "持有", "color": "#2080f0"},
    "stop": {"label": "停止加仓", "color": "#f0a020"},
    "reduce": {"label": "减仓", "color": "#18a058"},
}

_ACTION_RANK = {"add": 2, "hold_low": 1, "hold": 0, "stop": -1, "reduce": -2}

# ============================================================
# 模块级缓存
# ============================================================

_INDEX_CACHE: dict = {"ts": 0.0, "data": None}
_FUND_CACHE: dict = {"ts": 0.0, "data": None}
_CODES_CACHE: dict = {"ts": 0.0, "data": []}


def _today() -> str:
    return datetime.now(CST).strftime("%Y%m%d")


def _num(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ============================================================
# 上游取数
# ============================================================

def _fetch_index_hist(code: str) -> list[dict]:
    """指数日频历史（收盘 + 滚动市盈率），全量历史窗口。"""
    return _fetch_index_hist_range(code, HIST_START)


def _fetch_index_hist_range(code: str, start: str) -> list[dict]:
    """指数日频历史（滚动市盈率），``start`` 形如 ``20160101`` / ``20260101``。

    ⚠️ 中证官网长期限流，调用方必须容忍返回空列表（上层会退回本地缓存并打 stale 标记）。
    """
    data = akshare_request(
        "stock_zh_index_hist_csindex",
        {"symbol": code, "start_date": start, "end_date": _today()},
        timeout=30,
        retries=2,
    )
    return data if isinstance(data, list) else []


def _series_is_behind(series: list[tuple[str, float]]) -> bool:
    """本地 PE 序列是否已落后于最新交易日（落后则需去上游补增量）。

    ⚠️ **按「交易日」而非「自然日」判断**（2026-10-08 修正）：
       原实现用 `(今天 - 最后日期).days > PE_STALE_DAYS`，在长假必然误报——
       国庆 10-01~10-07 无交易，节前最后交易日 09-30 距10-08 有 8 个自然日
       （> 阈值 5），会被判成陈旧 → 误打 `pe_stale` 标记 + 回填 job 白跑一轮。
       现改为：算出「最近交易日」，与序列最后日期比**交易日差**。
       交易日历取不到时回退「周一~周五」判断（见 ``services.trading_calendar``）。
    """
    if not series:
        return True
    last = series[-1][0]
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return True
    try:
        from services.trading_calendar import latest_trading_day, trading_days_between

        today = datetime.now(CST).date()
        latest = latest_trading_day(today)
        if last_dt >= latest:
            return False
        # 落后几个交易日。
        # ⚠️ **基准日当天不计入**：序列最后日期 = 09-30、最新交易日 = 10-08 时，
        #   之间只缺 10-08 这**1** 个交易日（而不是「09-30~10-08 共 2 天」）。
        #   故基准日当天补1 天再算，避免 off-by-one 把「只差一天」误判成「落后两天」。
        return trading_days_between(last_dt + timedelta(days=1), latest) >= PE_STALE_TRADE_DAYS
    except Exception as e:  # pragma: no cover — 日历不可用时的兜底
        print(f"[Dividend] 交易日历不可用，回退自然日判断: {type(e).__name__}")
        return (datetime.now(CST).date() - last_dt).days > PE_STALE_DAYS


def _date_is_behind(date_str: str | None) -> bool:
    """单个日期是否已落后于「最近交易日」（用于股息率等只有日期、无序列的数据）。

    与 ``_series_is_behind`` **同一套交易日历口径**，保证 PE 与股息率的
    「新鲜度」判断一致，不会一个说新鲜一个说陈旧。
    """
    if not date_str:
        return True
    try:
        last_dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return True
    return _series_is_behind([(str(date_str)[:10], 0.0)])


def _fetch_index_value(code: str) -> list[dict]:
    """中证官方估值（股息率1 / 市盈率1），仅最近约 20 个交易日。

    ⚠️ 上游 403 期间进入静默期（VALUE_FAIL_TTL），期间直接返回空，不再打扰上游。
    """
    ts = _VALUE_FAIL_AT.get(code)
    if ts and (time.time() - ts) < VALUE_FAIL_TTL:
        return []
    data = akshare_request(
        "stock_zh_index_value_csindex",
        {"symbol": code},
        timeout=30,
        retries=1,
    )
    rows = data if isinstance(data, list) else []
    if not rows:
        _VALUE_FAIL_AT[code] = time.time()
    return rows


#: 全市场基金名录的进程内缓存（``fund_name_em`` 返回 2.8 万条，约 9s）
#: ⚠️ 2026-10-08：原来每次 overview 请求都重拉一遍 → 单这一项就吃掉 ~9s，
#:   是force=0 剩余耗时（13.8s）的主因。基金名录一天也变不了几支，
#:   故按 6h 缓存即可（与INDEX_CACHE_TTL 同周期）。
_FUND_DIR_CACHE: dict = {"data": None, "ts": 0.0}
FUND_DIR_CACHE_TTL = 6 * 3600


def _fetch_fund_directory(force: bool = False) -> list[dict]:
    """全市场公募基金名录（带 6h 进程内缓存）。

    ⚠️ ``fund_name_em`` 返回约 2.8 万条、耗时约 9s，且**名录本身几乎不变**
    （一天新增不了几支基金），故缓存 6h；``force=True`` 时才强制重拉。
    """
    now = time.time()
    if not force and _FUND_DIR_CACHE["data"]:
        if (now - _FUND_DIR_CACHE["ts"]) <= FUND_DIR_CACHE_TTL:
            return _FUND_DIR_CACHE["data"]
    data = akshare_request("fund_name_em", timeout=60, retries=2)
    rows = data if isinstance(data, list) else []
    if rows:
        _FUND_DIR_CACHE["data"] = rows
        _FUND_DIR_CACHE["ts"] = now
        print(f"[Dividend] 基金名录已刷新：{len(rows)} 条")
    return rows


def _get_yield_10y() -> tuple[float | None, str | None]:
    """最新 10Y 国债收益率（%）及其日期。非阻塞：拿不到就直接返回 None。"""
    try:
        from services.market_service import _fetch_10y_history

        yld_map = _fetch_10y_history() or {}
        if not yld_map:
            return None, None
        latest = max(yld_map.keys())
        return _num(yld_map[latest]), latest
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] 获取10Y国债失败: {e}")
        return None, None


# ============================================================
# 指标计算
# ============================================================

def _percentile(sorted_vals: list[float], v: float) -> float:
    """当前值在历史序列中的分位（0~100，值越小越便宜 → 分位越低）。"""
    if not sorted_vals:
        return None  # type: ignore[return-value]
    le = bisect.bisect_right(sorted_vals, v)
    return round(le / len(sorted_vals) * 100, 1)


def _monthly_sample(rows: list[dict]) -> list[dict]:
    """按月抽样：每月取最后一个交易日，控制返回体大小。"""
    buckets: dict[str, dict] = {}
    for r in rows:
        d = str(r.get("日期", ""))[:10]
        if len(d) < 7:
            continue
        buckets[d[:7]] = {"date": d, "pe": _num(r.get("滚动市盈率"))}
    return [buckets[k] for k in sorted(buckets.keys())]


def _signal(action: str, reason: str) -> dict:
    meta = ACTION_META.get(action, ACTION_META["hold"])
    return {"action": action, "label": meta["label"], "color": meta["color"], "reason": reason}


def _eb_signal(ratio: float | None) -> dict | None:
    if ratio is None:
        return None
    if ratio >= EB_ADD:
        return _signal("add", f"股债收益比 {ratio:.2f} ≥ {EB_ADD}，可适当加仓")
    if ratio >= EB_LOW:
        return _signal("hold_low", f"股债收益比 {ratio:.2f} 处于 {EB_LOW}~{EB_ADD} 低估区间，可继续持有")
    if ratio >= EB_RISK:
        return _signal("hold", f"股债收益比 {ratio:.2f} 处于 {EB_RISK}~{EB_LOW} 中性区间，持有")
    return _signal("reduce", f"股债收益比 {ratio:.2f} < {EB_RISK}，进入风险区间，考虑减仓")


def _pe_signal(pct: float | None) -> dict | None:
    if pct is None:
        return None
    if pct > PE_REDUCE:
        return _signal("reduce", f"PE 分位 {pct:.0f}% > {PE_REDUCE:.0f}%，可考虑减仓")
    if pct > PE_STOP:
        return _signal("stop", f"PE 分位 {pct:.0f}% > {PE_STOP:.0f}%，停止加仓，新增资金转向更低估品种")
    if pct < PE_ADD:
        return _signal("add", f"PE 分位 {pct:.0f}% < {PE_ADD:.0f}%，估值低位，可加仓")
    return _signal("hold", f"PE 分位 {pct:.0f}% 处于 {PE_ADD:.0f}%~{PE_STOP:.0f}% 正常区间，持有")


def _dy_signal(dy: float | None) -> dict | None:
    if dy is None:
        return None
    if dy > DY_HOLD:
        return _signal("hold", f"股息率 {dy:.2f}% > {DY_HOLD}%，正常持有")
    if dy >= DY_STOP:
        return _signal("stop", f"股息率 {dy:.2f}% 处于 {DY_STOP}~{DY_HOLD}% ，停止加仓但不减仓")
    return _signal("reduce", f"股息率 {dy:.2f}% < {DY_STOP}%，减仓 3 成转向宽基")


def _dy_load_from_db() -> None:
    """启动时/首次使用时把库里最后一期股息率灌进内存兜底表。"""
    global _DY_LOADED
    if _DY_LOADED:
        return
    _DY_LOADED = True
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(DY_DDL)
        rows = db.fetchall("SELECT code, dy, dy_date FROM base_dividend_index_dy")
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] 股息率兜底读取失败（忽略）: {e}")
        return
    for code, dy, dy_date in rows:
        if dy is not None and code not in _DY_LAST:
            _DY_LAST[str(code)] = (float(dy), str(dy_date) if dy_date else None)
    if rows:
        print(f"[Dividend] 已从库里恢复 {len(rows)} 个指数的最后一期股息率")


def _dy_save_to_db(indices: list[dict]) -> None:
    """把最新一期股息率落库（只写当次真正取到的，不覆盖成 stale 值）。"""
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(DY_DDL)
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] 股息率落库失败（忽略）: {e}")
        return
    for i in indices or []:
        if i.get("dividend_yield") is None or i.get("dy_stale"):
            continue
        try:
            db.execute("DELETE FROM base_dividend_index_dy WHERE code = ?", [i["code"]])
            db.execute(
                "INSERT INTO base_dividend_index_dy (code, name, dy, dy_date, updated_at) VALUES (?,?,?,?,?)",
                [i["code"], i["name"], i["dividend_yield"], i.get("dy_date"), datetime.now(CST)],
            )
        except Exception as e:
            print(f"[Dividend] {i.get('code')} 股息率落库失败: {e}")


# ============================================================
# PE 序列本地累积（2026-10-08）
#   策略：**本地优先 + 上游只补增量**，不是切断上游。
#   - 本地已有历史 → 分位/区间完全本地算，不受中证限流影响
#   - 本地最新日期落后 → 才去上游抓，抓到后 upsert 回库
#   - 上游失败/限流 → 用本地最后值计算，打 pe_stale 标记（对齐 dy_stale 做法）
# ============================================================


def _pe_load_all() -> None:
    """把库里的 PE 序列全量灌进进程内缓存（首次调用时执行）。"""
    global _PE_CACHE_LOADED
    if _PE_CACHE_LOADED:
        return
    _PE_CACHE_LOADED = True
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(PE_DDL)
        rows = db.fetchall(
            "SELECT code, trade_date, pe FROM base_dividend_index_pe "
            "WHERE pe IS NOT NULL ORDER BY code, trade_date"
        )
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] PE 序列读取失败（忽略）: {e}")
        return
    series: dict[str, list[tuple[str, float]]] = {}
    for code, d, pe in rows:
        v = _num(pe)
        if v is None or not d:
            continue
        series.setdefault(str(code), []).append((str(d)[:10], v))
    _PE_CACHE.update(series)
    total = sum(len(v) for v in series.values())
    if rows:
        print(f"[Dividend] 已从库里加载 PE 序列：{len(series)} 个指数 / {total} 个交易日")


def _pe_get_series(code: str) -> list[tuple[str, float]]:
    """取本地 PE 序列（按日期升序）。"""
    _pe_load_all()
    return _PE_CACHE.get(code, [])


def _pe_latest_date(code: str) -> str | None:
    s = _pe_get_series(code)
    return s[-1][0] if s else None


def _pe_save_rows(code: str, rows: list[dict]) -> int:
    """把上游取到的 PE 行 upsert 进库+ 进程缓存，返回新增条数。

    只写「本地还没有的日期」，已存在的日期不重复写（幂等，可安全重跑）。
    """
    if not rows:
        return 0
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(PE_DDL)
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] PE 序列落库失败（忽略）: {e}")
        return 0

    existing = {d for d, _ in _pe_get_series(code)}
    now = datetime.now(CST)
    added = 0
    for r in rows:
        d = str(r.get("日期", ""))[:10]
        v = _num(r.get("滚动市盈率"))
        if len(d) < 10 or v is None or d in existing:
            continue
        try:
            db.execute(
                "INSERT INTO base_dividend_index_pe (code, trade_date, pe, updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT (code, trade_date) DO UPDATE SET pe=excluded.pe",
                [code, d, v, now],
            )
        except Exception as e:
            print(f"[Dividend] {code} {d} PE 落库失败: {e}")
            continue
        existing.add(d)
        _PE_CACHE.setdefault(code, []).append((d, v))
        added += 1

    if added:
        # 新增日期一定在末尾（上游按日期升序返回），故append 后排序即可
        _PE_CACHE[code] = sorted(_PE_CACHE.get(code, []), key=lambda x: x[0])
    return added


def _pe_refresh(code: str, full: bool = False, since_days: int | None = None) -> int:
    """从上游拉 PE 序列并落库。

    三种模式：
      - ``full=True``（回填 job 用）：抓 ``HIST_START`` 起的全量历史。
      - ``since_days=N``（请求路径首次兜底用）：只抓最近 N 天，避免请求被拖死。
      - 默认（日常增量）：抓本地最后日期之后的部分。

    ⚠️ **返回 0 有两种截然不同的含义，必须区分**（2026-10-08 加）：
      上游**限流/报错**（该重试）vs **中证根本不覆盖该指数**（重试永远无意义）。
      原实现两者都返回 0，回填日志统一报「上游无数据（中证不覆盖或限流）」——
      **看着像限流、实际可能是不覆盖**，导致既误判运维状态、又白白消耗中证配额。
      现在用``last_error`` 区分：抛过异常 → 限流（可重试）；正常返回但空 → 不覆盖（放弃）。
    """
    if full:
        start = HIST_START
    elif since_days:
        start = (datetime.now(CST) - timedelta(days=since_days)).strftime("%Y%m%d")
    else:
        start = (_pe_latest_date(code) or HIST_START).replace("-", "")
    try:
        rows = _fetch_index_hist_range(code, start)
    except Exception as e:
        _PE_LAST_ERROR[code] = f"限流/报错: {type(e).__name__}"
        print(f"[Dividend] {code} PE 上游拉取失败: {e}")
        return 0
    if not rows:
        # 正常响应但空数据 → 中证不覆盖该指数（换时间再试也没用）
        _PE_LAST_ERROR[code] = "中证不覆盖该指数"
        return 0
    if not _pe_save_rows(code, rows):
        # 有行但一行都没落库 → 数据陈旧（限流中间态），属可重试
        _PE_LAST_ERROR[code] = "上游返回的数据陈旧（限流中间态）"
        return 0
    _PE_LAST_ERROR.pop(code, None)
    return 1 if _pe_get_series(code) else 0


# ============================================================
# PE 历史回填（分批低并发 + 断点续传）
#
# ⚠️ 必须在 **backend 进程内** 调用：DuckDB 是独占进程锁，独立 python 进程
#    连read_only=True 都会报「Conflicting lock is held in PID 7」。
#    故不提供独立脚本入口，而是暴露成 HTTP 端点由运行中的 backend 执行。
# ============================================================

#: 回填进度（进程内state，重启后由库中实际行数重建）
_PE_BACKFILL: dict = {
    "running": False,
    "done": False,
    "scanned": 0,
    "total": 0,
    "filled": 0,
    "failed": 0,
    "rows_added": 0,
    "current": "",
    "started_at": None,
    "finished_at": None,
    "log": [],
}

#: 视为「已回填」的最小行数（正常老指数≈2613 天）
#: ⚠️ **不能单独用它判完成**：2024 年后才发布的新指数天然只有几十~几百天
#:   （实测931848 只有 103 天、932422 只有 367 天），用固定阈值会把它们
#:   永远判为「未回填」→ 每天重复回填，白白消耗中证配额并加剧限流。
#:   真正的判据是「是否尝试过并落过库」，见 ``base_dividend_index_pe_backfill``。
PE_BACKFILL_MIN_ROWS = 1000

#: 回填完成记录表：记录「哪些指数已经全量回填过」，与行数无关。
#: 新指数行数少属正常；只有「从未成功回填过」才需要继续尝试。
PE_BACKFILL_LOG_DDL = """
CREATE TABLE IF NOT EXISTS base_dividend_index_pe_backfill (
    code        VARCHAR PRIMARY KEY,
    name        VARCHAR,
    rows        INTEGER,
    done_at     TIMESTAMP
)
"""

#: **永久不支持**表：中证官网根本不覆盖的指数（华证系 995xxx / 港股恒生系 /
#: 标普富时系 / 399324 深市）。重试多少次都没结果，记下来让回填 job **彻底跳过**，
#: 避免每天白耗中证配额并加剧限流。
#: ⚠️ 与「限流失败」严格区分 —— 限流是可重试的，不该进这张表。
PE_UNSUPPORTED_DDL = """
CREATE TABLE IF NOT EXISTS base_dividend_index_pe_unsupported (
    code        VARCHAR PRIMARY KEY,
    name        VARCHAR,
    reason      VARCHAR,
    marked_at   TIMESTAMP
)
"""

#: 回填并发（**不要调高**，中证官网限流频繁，>3 极易触发封禁）
PE_BACKFILL_CONCURRENCY = 2


def _pe_backfill_done_codes() -> set[str]:
    """读出「已经全量回填过」的指数代码集合。

    判完成**不看行数**（新指数天然只有几十~几百天），只看是否尝试并落库成功过。
    """
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(PE_BACKFILL_LOG_DDL)
        rows = db.fetchall("SELECT code FROM base_dividend_index_pe_backfill")
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] 回填完成记录读取失败（忽略）: {e}")
        return set()
    return {str(r[0]) for r in rows}


def _pe_mark_backfilled(code: str, name: str, rows: int) -> None:
    """标记某指数已全量回填过（之后不再重复抓）。"""
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(PE_BACKFILL_LOG_DDL)
        db.execute(
            "INSERT INTO base_dividend_index_pe_backfill (code, name, rows, done_at) "
            "VALUES (?,?,?,?) ON CONFLICT (code) DO UPDATE SET rows=excluded.rows, done_at=excluded.done_at",
            [code, name, rows, datetime.now(CST)],
        )
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] 标记 {code} 回填完成失败（忽略）: {e}")


def _pe_mark_unsupported(code: str, name: str) -> None:
    """标记某指数为「中证不覆盖」→ 之后回填 job **彻底跳过**，不再浪费配额。"""
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(PE_UNSUPPORTED_DDL)
        db.execute(
            "INSERT INTO base_dividend_index_pe_unsupported (code, name, reason, marked_at) "
            "VALUES (?,?,?,?) ON CONFLICT (code) DO UPDATE SET reason=excluded.reason",
            [code, name, _PE_LAST_ERROR.get(code, "上游无数据"), datetime.now(CST)],
        )
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] 标记 {code} 不支持失败（忽略）: {e}")


def _pe_unsupported_codes() -> set[str]:
    """读出已确认「中证不覆盖」的指数（回填时直接跳过）。"""
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(PE_UNSUPPORTED_DDL)
        rows = db.fetchall("SELECT code FROM base_dividend_index_pe_unsupported")
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] 不支持列表读取失败（忽略）: {e}")
        return set()
    return {str(r[0]) for r in rows}


def pe_backfill_status() -> dict:
    """回填进度 + 各指数当前行数（供前端展示）。

    ⚠️ 范围与 ``pe_backfill_start`` 的待办**必须一致**（都含现金流 5 只），
       否则这里算出 ``pending_count==0`` 而实际还有待办 → job 误停。
    """
    _pe_load_all()
    done_codes = _pe_backfill_done_codes()
    unsupported = _pe_unsupported_codes()
    all_specs = [(c, n) for c, n, _r, _a in DIVIDEND_INDICES] + [
        (c, n) for c, n, _reg, _al in CASHFLOW_INDICES if c.startswith("93")
    ]
    rows = []
    done = 0
    for code, name in all_specs:
        n = len(_pe_get_series(code))
        # 已回填过 → 完成（无论行数多少，新指数本来就短）
        # 未回填过但已有数据（如上次部分成功后重启）→ 也算完成
        # 已确认中证不覆盖 → 单独标记，不算「完成」也不算「待办」
        ok = code in done_codes or n > 0
        if ok:
            done += 1
        rows.append(
            {
                "code": code,
                "name": name,
                "rows": n,
                "filled": ok,
                "unsupported": code in unsupported,
                "last_error": _PE_LAST_ERROR.get(code),
            }
        )
    pending = [
        r for r in rows if not r["filled"] and not r["unsupported"]
    ]
    return {
        **_PE_BACKFILL,
        "done_count": done,
        "pending_count": len(pending),
        "unsupported_count": sum(1 for r in rows if r["unsupported"]),
        "index_count": len(all_specs),
        "indices": rows,
    }


def pe_backfill_start(codes: list[str] | None = None, limit: int = 8) -> dict:
    """启动一轮历史回填（后台线程）。已在跑时直接返回当前进度。

    ``codes`` 为空则自动挑「**尚未成功回填过**」的指数
    （行数不足不算，见 ``PE_BACKFILL_MIN_ROWS`` 注释里的坑），
    因此**中断后重跑会自动续传**（断点续传即靠这个判定）。
    """
    if _PE_BACKFILL["running"]:
        return {"started": False, "reason": "回填已在运行中", **_PE_BACKFILL}

    _pe_load_all()
    # ⚠️ 已确认「中证不覆盖」的指数**直接排除**：重试永远无果，
    #   每天试它们只会白耗中证配额、把限流越搞越狠。
    unsupported = _pe_unsupported_codes()
    if codes:
        want = {c.strip() for c in codes if c.strip() and c.strip() not in unsupported}
        todo = [(c, n) for c, n, _r, _a in DIVIDEND_INDICES if c in want]
    else:
        # 只挑「本地为空**或**数据已陈旧**且未被判为不覆盖**」的指数。
        # ⚠️ 不能只看 `len(series)==0`（2026-10-08 踩）：限流时上游会返回**残缺的
        #   历史片段**（实测 930836 只拿到 2019-07-26 截止的 803 天、000015 只到
        #   2025-06-16），这些指数**有行数**但数据停在几年前，按「有行数就跳过」
        #   会让它们永远停在老数据上。按新鲜度筛选才能自愈。
        # 范围 = 红利指数 + 现金流指数（2026-10-08）：
        #   现金流那 5 只中证系列指数（932365~932369）同样要读PE 序列，
        #   否则「日常访问走本地基线」时它们没数据可用。
        # ⚠️ 只取``CASHFLOW_INDICES`` 里 ``93`` 开头的（中证系列）；
        #   国证 980092 / 富时那条两源都不覆盖，让它们自然判为 unsupported。
        all_specs = [(c, n) for c, n, _r, _a in DIVIDEND_INDICES] + [
            (c, n) for c, n, _reg, _al in CASHFLOW_INDICES if c.startswith("93")
        ]
        todo = [
            (c, n)
            for c, n in all_specs
            if c not in unsupported
            and (not _pe_get_series(c) or _series_is_behind(_pe_get_series(c)))
        ][: max(1, limit)]

    if not todo:
        _PE_BACKFILL.update(
            running=False, done=True, finished_at=datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        )
        return {"started": False, "reason": "没有待回填的指数", **_PE_BACKFILL}

    _PE_BACKFILL.update(
        running=True,
        done=False,
        scanned=0,
        total=len(todo),
        filled=0,
        failed=0,
        rows_added=0,
        current="",
        started_at=datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=None,
        log=[],
    )

    def _log(msg: str) -> None:
        line = f"{datetime.now(CST).strftime('%H:%M:%S')} {msg}"
        print(f"[PE回填] {msg}", flush=True)
        # 只留最近 60 条，避免长时间回填把内存吃满
        _PE_BACKFILL["log"].append(line)
        if len(_PE_BACKFILL["log"]) > 60:
            del _PE_BACKFILL["log"][:-60]

    def _worker() -> None:
        def one(spec: tuple[str, str]) -> tuple[str, int, bool]:
            code, name = spec
            _PE_BACKFILL["current"] = code
            before = len(_pe_get_series(code))
            try:
                added = ds_pe_refresh_full(code)
            except Exception as e:  # noqa: BLE001
                _log(f"✗ {code} {name} 异常 {type(e).__name__}: {e}")
                return code, 0, False
            after = len(_pe_get_series(code))
            latest = _pe_latest_date(code)
            # ⚠️ **完成判据必须含「数据够新」**，不能只看「拿到数据」：
            #   中证限流时会返回**残缺的历史片段**（实测 930836 只拿到 2019-07-26
            #   截止的 803 天、000015 只到 2025-06-16），若「有数据就标记完成」，
            #   这些指数会被**永久跳过**，永远停在几年前。
            #   故要求最后日期落在 PE_STALE_DAYS 宽限内才算回填完成，
            #   否则留给下一轮 job 重试。
            fresh_enough = bool(latest) and not _series_is_behind(_pe_get_series(code))
            if after > before and fresh_enough:
                _log(f"✓ {code} {name} +{after - before} 行 → 共 {after}（截至 {latest}）")
                _pe_mark_backfilled(code, name, after)
                return code, after - before, True
            if after > before:
                #拿到数据但不够新 → 视为未完成，下轮继续补
                _log(
                    f"… {code} {name} +{after - before} 行但数据仍陈旧（截至 {latest or '无'}），"
                    f"留待下轮重试"
                )
                return code, after - before, False
            if after > 0 and fresh_enough:
                _log(f"= {code} {name} 无新增（库内 {after} 行，截至 {latest}）")
                _pe_mark_backfilled(code, name, after)
                return code, 0, True
            # ⚠️ 失败原因必须说清是「限流」还是「不覆盖」——**处理方式完全不同**：
            #   · 不覆盖（华证系/ 港股恒生系 / 399324 深市）→ **永久放弃**，别再试，白耗配额
            #   · 限流 / 数据陈旧              → **降频重试**，等封禁窗口过去
            reason = _PE_LAST_ERROR.get(code) or "上游无数据"
            if "不覆盖" in reason:
                _log(f"⊘ {code} {name} {reason} → 永久跳过，不再重试")
                _pe_mark_unsupported(code, name)
                return code, 0, False
            _log(f"… {code} {name} {reason} → 稍后重试")
            return code, 0, False

        try:
            with ThreadPoolExecutor(max_workers=PE_BACKFILL_CONCURRENCY) as pool:
                for code, gained, ok in pool.map(one, todo):
                    _PE_BACKFILL["scanned"] += 1
                    _PE_BACKFILL["rows_added"] += gained
                    if ok:
                        _PE_BACKFILL["filled"] += 1
                    else:
                        _PE_BACKFILL["failed"] += 1
        except Exception as e:  # noqa: BLE001
            _log(f"批量回填异常：{type(e).__name__}: {e}")
        finally:
            _PE_BACKFILL.update(
                running=False,
                done=True,
                current="",
                finished_at=datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            )
            _log(
                f"完成：成功 {_PE_BACKFILL['filled']} / 失败 {_PE_BACKFILL['failed']}，"
                f"新增 {_PE_BACKFILL['rows_added']} 行"
            )

    threading.Thread(target=_worker, name="pe-backfill", daemon=True).start()
    _log(f"开始回填 {len(todo)} 个指数：{[c for c, _ in todo]}")
    return {"started": True, **_PE_BACKFILL}


def ds_pe_refresh_full(code: str) -> int:
    """全量回填单个指数（内部调 _pe_refresh(full=True)）。"""
    return _pe_refresh(code, full=True)


# ============================================================
# 股息率每日刷新（2026-10-08）
#
# ⚠️ 为什么必须单独加（与 PE 同类的隐患）：
#   overview 改成「日常访问走本地基线」后，``_build_index_metric(offline=True)``
#   的股息率只从内存 ``_DY_LAST`` 读、**不抓上游**；而 ``_DY_LAST`` 只靠
#   ``_dy_load_from_db``（库表→内存）和 ``_dy_save_to_db``（内存→库表）维持，
#   **这两者都只在 force=1 时才会被触发**。
#   → 后果：只要没人点刷新，股息率就**永久冻结在最后一次 force=1 的值**，
#     股债收益比/ 股息率信号随之过期而不自知。
#   PE 序列有 ``dividend_pe_backfill_job`` 每日推进，股息率却没有 —— 故补上。
# ============================================================


def dy_refresh_one(code: str) -> tuple[str | None, str | None, bool]:
    """抓单个指数的股息率并落库+ 更新内存 ``_DY_LAST``。

    返回 ``(dy, dy_date, ok)``；ok=False 表示上游限流或无数据（**保留旧值**）。
    """
    try:
        rows = _fetch_index_value(code)
    except Exception as e:  # noqa: BLE001
        print(f"[Dividend] {code} 股息率拉取失败: {type(e).__name__}")
        return None, None, False
    usable = [r for r in rows if _num(r.get("股息率1")) is not None and r.get("日期")]
    if not usable:
        return None, None, False
    top = max(usable, key=lambda r: str(r.get("日期"))[:10])
    dy, dy_date = _num(top.get("股息率1")), str(top.get("日期"))[:10]
    if dy is None:
        return None, None, False
    _DY_LAST[code] = (dy, dy_date)
    _dy_save_one(code, dy, dy_date)
    return dy, dy_date, True


def _dy_save_one(code: str, dy: float, dy_date: str, name: str = "") -> None:
    """把单个指数的股息率落库（``base_dividend_index_dy``）。"""
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(DY_DDL)
        db.execute("DELETE FROM base_dividend_index_dy WHERE code = ?", [code])
        db.execute(
            "INSERT INTO base_dividend_index_dy (code, name, dy, dy_date, updated_at) "
            "VALUES (?,?,?,?,?)",
            [code, name or code, dy, dy_date, datetime.now(CST)],
        )
    except Exception as e:  # pragma: no cover
        print(f"[Dividend] {code} 股息率落库失败（忽略）: {e}")


def dy_refresh_batch(codes: list[str] | None = None) -> dict:
    """批量刷新股息率（后台线程内跑，并发 2避免加剧限流）。

    返回统计：``{"total":, "ok":, "failed":, "skipped":}``
    """
    _dy_load_from_db()
    targets = codes or [c for c, _n, _r, _a in DIVIDEND_INDICES]
    stat = {"total": len(targets), "ok": 0, "failed": 0, "skipped": 0}
    name_by_code = {c: n for c, n, _r, _a in DIVIDEND_INDICES}

    def one(code: str) -> None:
        dy, dy_date, ok = dy_refresh_one(code)
        if ok:
            _dy_save_one(code, dy or 0.0, dy_date or "", name_by_code.get(code, ""))
            stat["ok"] += 1
            print(f"[股息率刷新] ✓ {code} {dy:.2f}%（{dy_date}）")
        else:
            stat["failed"] += 1
            print(f"[股息率刷新] ✗ {code} 上游无数据/限流，保留旧值")

    pool = ThreadPoolExecutor(max_workers=PE_BACKFILL_CONCURRENCY)
    try:
        list(pool.map(one, targets))
    except Exception as e:  # noqa: BLE001
        print(f"[股息率刷新] 批量异常: {type(e).__name__}: {e}")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return stat


def _build_index_metric(
    spec: tuple[str, str, str, list[str]], yield_10y: float | None, offline: bool = False
) -> dict:
    """组装单指数的估值指标。

    ``offline=True`` 时**完全不碰网络**：PE 只读本地 ``base_dividend_index_pe``、
    股息率只读本地 ``base_dividend_index_dy`` / 进程内 ``_DY_LAST``。
    用于两阶段构建的**基线**（先无网络算全量，再让有时间预算的上游结果覆盖），
    保证「上游慢 / 限流 / 回填 job 抢资源」时接口仍能立刻返回全部指数。
    """
    code, name, _region, _aliases = spec

    # ---- PE 序列：本地优先，上游只补增量 ----
    series = _pe_get_series(code)
    # ⚠️ 「本地值」≠「陈旧值」：本地序列可能就是今天的、完全新鲜的。
    #   所以 offline 基线也要按**实际新鲜度**判stale，否则日常访问 44 个全部
    #   打 `*`，用户会麻木、真陈旧时反而看不出来（2026-10-08 修）。
    #   判据：本地为空不算 stale（显示 — 即可）；有序列但落后才stale。
    pe_stale = _series_is_behind(series) if series else False
    if not offline:
        if not series:
            # 本地还没有历史 → **不在请求路径里拉全量**。
            # ⚠️ 历史回填是job（dividend_pe_backfill_job）的职责，每天小批量推进。
            #   若在overview 里拉全量：44 指数 × 2613 行会把这个 HTTP 请求拖到
            #   数分钟甚至超时（实测 >300s → 前端 HTTP=000），且与限流对抗。
            #   这里只补「最近一小段」用于兜底显示，全量等 job 慢慢补齐。
            added = _pe_refresh(code, since_days=PE_TAIL_DAYS)
            if added:
                series = _pe_get_series(code)
        elif _series_is_behind(series):
            # 已有历史但落后 → 只补增量（start = 本地最后日期）
            added = _pe_refresh(code)
            if added:
                series = _pe_get_series(code)
            else:
                pe_stale = True  # 上游没给到新的，沿用本地最后值

    rows = [{"日期": d, "滚动市盈率": v} for d, v in series]

    pe_values = sorted(_num(r["滚动市盈率"]) for r in rows)
    latest = rows[-1] if rows else None

    pe = _num(latest.get("滚动市盈率")) if latest else None
    pe_date = str(latest.get("日期"))[:10] if latest else None
    pct = _percentile(pe_values, pe) if (pe is not None and pe_values) else None

    # 股息率（中证官方，仅最近约 20 个交易日）
    dy = None
    dy_date = None
    # ⚠️ 必须先初始化：offline 且 `_DY_LAST` 里没有该code 时会直接走到下面的
    #   return dict(dy_stale=...)，漏掉这行会 UnboundLocalError（2026-10-09 实测 500）。
    dy_stale = False
    if offline:
        # 本地兜底：内存 _DY_LAST（启动时由 _dy_load_from_db 从库里灌入）
        if code in _DY_LAST:
            dy, dy_date = _DY_LAST[code]
            # ⚠️ 判新鲜度**按日期**、不按 `_DY_FRESH` 集合（2026-10-09 二次修正）：
            #   `_DY_FRESH` 是进程级 set、一经添加永不清除 —— 若靠它判定，
            #   容器跑久了会出反向误标：周一刷新成功 → 周二上游挂了，
            #   但 code 仍在 set 里 → **陈旧数据被判「新鲜」、不标 stale**。
            #   这与今天修的「新鲜被误标 stale」是同一类错误的镜像。
            #   改为复用 PE 那套交易日判据，口径统一且与时间无关。
            dy_stale = _date_is_behind(dy_date)
    else:
        val_rows = _fetch_index_value(code)
        usable = [r for r in val_rows if _num(r.get("股息率1")) is not None and r.get("日期")]
        if usable:
            top = max(usable, key=lambda r: str(r.get("日期"))[:10])
            dy = _num(top.get("股息率1"))
            dy_date = str(top.get("日期"))[:10]

    # 上游封禁期间沿用最后一期股息率，并打 stale 标记（前端可提示）
    if dy is not None and dy_date:
        _DY_LAST[code] = (dy, dy_date)
        # ⚠️ 这里**不**用「本次抓到过」来判定新鲜度：进程级 set 一经添加永不清除，
        #   容器跑久了会造成「陈旧数据被判新鲜」。统一按 `dy_date` 判（见上）。
    elif dy is None and code in _DY_LAST:
        dy, dy_date = _DY_LAST[code]
        dy_stale = True

    eb_ratio = round(dy / yield_10y, 2) if (dy is not None and yield_10y) else None
    dy_spread = round(dy - yield_10y, 2) if (dy is not None and yield_10y is not None) else None

    sig_eb = _eb_signal(eb_ratio)
    sig_pe = _pe_signal(pct)
    sig_dy = _dy_signal(dy)

    actions = [s["action"] for s in (sig_eb, sig_pe, sig_dy) if s]
    conflict = ("add" in actions) and ("stop" in actions or "reduce" in actions)

    def _q(p: float) -> float | None:
        if not pe_values:
            return None
        idx = min(len(pe_values) - 1, max(0, int(round((len(pe_values) - 1) * p))))
        return round(pe_values[idx], 2)

    return {
        "code": code,
        "name": name,
        "pe": pe,
        "pe_date": pe_date,
        "pe_percentile": pct,
        "pe_min": round(pe_values[0], 2) if pe_values else None,
        "pe_max": round(pe_values[-1], 2) if pe_values else None,
        "pe_p25": _q(0.25),
        "pe_median": _q(0.5),
        "pe_p75": _q(0.75),
        "window_days": len(pe_values),
        "window_start": str(rows[0].get("日期"))[:10] if rows else None,
        "pe_stale": pe_stale,
        "dividend_yield": dy,
        "dy_date": dy_date,
        "dy_stale": dy_stale,
        "yield_10y": yield_10y,
        "eb_ratio": eb_ratio,
        "dy_spread": dy_spread,
        "signals": {"eb": sig_eb, "pe": sig_pe, "dy": sig_dy},
        "conflict": conflict,
        "pe_series": _monthly_sample(rows),
    }


# ============================================================
# 基金名录
# ============================================================

def _index_alias_map() -> list[tuple[str, str, str, str]]:
    """(别名, 指数代码, 指数简称, 区域)，按别名长度降序 → 长别名优先匹配。"""
    pairs: list[tuple[str, str, str, str]] = []
    for code, name, region, aliases in DIVIDEND_INDICES:
        for a in aliases:
            pairs.append((a, code, name, region))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def _region_of(name: str) -> str:
    """基金名称 → 所属市场区域。"""
    if "沪港深" in name:
        return "SHS"
    if any(k in name for k in HK_NAME_KEYWORDS):
        return "HK"
    return "A"


def _match_index(name: str, alias_pairs: list[tuple[str, str, str, str]]) -> tuple[str | None, str | None]:
    """基金名称 → 跟踪指数（**区域必须一致**才匹配）。

    ⚠️ 防错：先按名称判定区域，再只在该区域的指数里找最长别名。
    否则「港股通红利低波ETF」会被 A 股的「红利低波(H30269)」抢走、
    「沪港深红利成长低波」会被 A 股指数误配。宁可留空，不可错配。
    """
    region = _region_of(name)
    for alias, code, idx_name, reg in alias_pairs:
        if alias in name and reg == region:
            return code, idx_name
    return None, None


_CASHFLOW_ALIAS_PAIRS: list[tuple[str, str, str]] | None = None


def _cashflow_alias_pairs() -> list[tuple[str, str, str]]:
    """现金流指数别名表（**(别名, 指数代码, 指数简称)**，长别名优先），进程内只构建一次。"""
    global _CASHFLOW_ALIAS_PAIRS
    if _CASHFLOW_ALIAS_PAIRS is None:
        pairs = [
            (a, code, name)
            for code, name, _reg, aliases in CASHFLOW_INDICES
            for a in aliases
        ]
        pairs.sort(key=lambda p: len(p[0]), reverse=True)
        _CASHFLOW_ALIAS_PAIRS = pairs
    return _CASHFLOW_ALIAS_PAIRS


def _match_cashflow_fund(code: str, name: str) -> tuple[str | None, str | None]:
    """场内现金流 ETF → 跟踪指数。

    三级顺序：``CASHFLOW_INDEX_OVERRIDES``（天天基金 F10 逐只实测，主路径）→
    ``_match_cashflow_index``（词表，兜住未来新增 ETF）→ 红利 ``_match_index``
    （万一某只现金流 ETF 名里带「红利」，也别让它显示成未识别）。
    """
    hit = CASHFLOW_INDEX_OVERRIDES.get(code)
    if hit:
        return (hit[0] or None), hit[1]
    hit = _match_cashflow_index(name)
    if hit[0] or hit[1]:
        return hit
    return _match_index(name, _index_alias_map())


def _match_cashflow_index(name_or_text: str) -> tuple[str | None, str | None]:
    """文本（基金简称 / F10「跟踪标的」原文）→ 现金流指数（长别名优先）。

    ⚠️ 与 ``_match_index`` 同一原则：**只认 ``CASHFLOW_INDICES`` 里登记过的别名，
    匹配不上就返回 (None, None)**。指数代码在常量里已经逐条核实过，这里不做任何推断——
    猜错就是把错误数据写进展示层。引用代码为空的指数（富时那条）返回 ``(None, 名称)``。
    """
    if not name_or_text:
        return None, None
    for alias, code, idx_name in _cashflow_alias_pairs():
        if alias in name_or_text:
            return (code or None), idx_name
    return None, None


_SHARE_RE = re.compile(r"[联接指数增强]?([ABCDEI])$")


def _parse_share_class(name: str) -> str:
    m = _SHARE_RE.search(name)
    return m.group(1) if m else ""


def _classify(name: str, ftype: str) -> tuple[str, str]:
    """返回 (分类 key, 场内/场外)。

    - ETF（不含「联接」）→ 场内交易型
    - LOF → 可场内交易，但按基金类型归入 passive / active
    - 其余 → 场外
    """
    is_etf = "ETF" in name and "联接" not in name
    if is_etf:
        return "etf", "场内"
    onshore = "LOF" in name
    if ftype.startswith("指数型"):
        return "passive", ("场内" if onshore else "场外")
    return "active", ("场内" if onshore else "场外")


def _build_fund_list(indices: list[dict]) -> dict[str, list[dict]]:
    rows = _fetch_fund_directory()
    alias_pairs = _index_alias_map()
    idx_by_code = {i["code"]: i for i in indices}

    buckets: dict[str, list[dict]] = {"etf": [], "passive": [], "active": []}
    excluded: dict[str, int] = {"non_passive": 0, "bond": 0, "money": 0, "no_name_hit": 0}
    for r in rows:
        name = str(r.get("基金简称", ""))
        code = str(r.get("基金代码", ""))
        ftype = str(r.get("基金类型", ""))
        if not name or not code:
            continue
        if not any(k in name for k in FUND_NAME_KEYS):
            excluded["no_name_hit"] += 1
            continue
        if ftype.startswith("货币型"):
            excluded["money"] += 1
            continue
        if ftype.startswith("债券型"):
            # 纯债：名字再像红利（双息红利 / 信用红利 / 红利债券）也不是红利产品
            excluded["bond"] += 1
            continue
        if not any(ftype.startswith(p) for p in PASSIVE_TYPE_PREFIX):
            # 主动管理：混合型-偏股 / 混合型-灵活 / 股票型 / QDII 等
            excluded["non_passive"] += 1
            continue

        category, market = _classify(name, ftype)
        idx_code = FUND_INDEX_OVERRIDES.get(code)
        idx_name = None
        if idx_code:
            idx_name = (idx_by_code.get(idx_code) or {}).get("name")
        if not idx_code:
            idx_code, idx_name = _match_index(name, alias_pairs)

        metric = idx_by_code.get(idx_code) if idx_code else None
        buckets[category].append({
            "code": code,
            "name": name,
            "type": ftype,
            "market": market,
            "share_class": _parse_share_class(name),
            "index_code": idx_code,
            "index_name": idx_name,
            # 估值指标（跟踪指数未识别时为 None，前端显示 —）
            "pe": metric.get("pe") if metric else None,
            "pe_percentile": metric.get("pe_percentile") if metric else None,
            "dividend_yield": metric.get("dividend_yield") if metric else None,
            "eb_ratio": metric.get("eb_ratio") if metric else None,
            "signals": metric.get("signals") if metric else None,
            # 规模 / 费率：由 fund_fee_service 后台渐进补全（同花顺 fund_info_ths）
            "scale": None,
            "scale_date": None,
            "mgmt_fee": None,
            "custody_fee": None,
            "subscribe_fee": None,
            "manager": None,
            # ⚠️ 仍无数据源：跟踪误差 / 分红频率 / 行业分散度
            "tracking_error": None,
            "payout_freq": None,
            "sector_concentration": None,
        })

    for key in buckets:
        buckets[key].sort(key=lambda x: x["code"])

    # 「主动」桶按新口径恒为空：名录只收被动指数型。保留键位以免下游解包炸掉。
    _LAST_EXCLUDED.clear()
    _LAST_EXCLUDED.update(excluded)
    return buckets


# ============================================================
# 现金流基金名录（独立一条线，2026-10-07 用户拍板「单开 Tab」）
# ============================================================

def _build_cashflow_fund_list() -> dict[str, list[dict]]:
    """全市场「现金流」类**场内 ETF**（与红利名录同构，但走自己的名称闸门）。

    ⚠️ **绝不复用 ``_build_fund_list``**：它把 ``FUND_NAME_KEYS`` 写死成
    （红利 / 高股息 / 股息），而现金流 ETF 名字里压根没「红利」二字（159399「现金流ETF国泰」）
    ——复用它，这条线永远是空的。类型口径（纯债 / 货币 / 主动同样不入）与红利完全一致。

    ⚠️ **只收场内 ETF**（2026-10-07 用户拍板「只要场内」）：全市场「现金流」类有 111 只，
    其中场外被动 78 只绝大多数是同一指数的 A/C/E 份额（华夏 159201 / 159221 同指数重复），
    摊进列表只会灌满重复项、看不出增量信息。场外一律计入 ``excluded["offshore"]``。
    """
    rows = _fetch_fund_directory()

    buckets: dict[str, list[dict]] = {"etf": [], "passive": [], "active": []}
    excluded: dict[str, int] = {"non_passive": 0, "bond": 0, "money": 0, "offshore": 0}
    for r in rows:
        name = str(r.get("基金简称", ""))
        code = str(r.get("基金代码", ""))
        ftype = str(r.get("基金类型", ""))
        if not name or not code:
            continue
        if not any(k in name for k in CASHFLOW_NAME_KEYS):
            continue
        if ftype.startswith("货币型"):
            excluded["money"] += 1
            continue
        if ftype.startswith("债券型"):
            excluded["bond"] += 1
            continue
        if not any(ftype.startswith(p) for p in PASSIVE_TYPE_PREFIX):
            excluded["non_passive"] += 1
            continue

        category, market = _classify(name, ftype)
        if category != "etf":
            # 只看场内 ETF：场外被动（A/C/E 份额为主）不进列表，只计入排除明细
            excluded["offshore"] += 1
            continue

        idx_code, idx_name = _match_cashflow_fund(code, name)

        buckets["etf"].append({
            "code": code,
            "name": name,
            "type": ftype,
            "market": market,
            "share_class": _parse_share_class(name),
            "index_code": idx_code,
            "index_name": idx_name,
            "pe": None,
            "pe_percentile": None,
            "dividend_yield": None,
            "eb_ratio": None,
            "signals": None,
            "scale": None,
            "scale_date": None,
            "mgmt_fee": None,
            "custody_fee": None,
            "subscribe_fee": None,
            "manager": None,
            "tracking_error": None,
            "payout_freq": None,
            "sector_concentration": None,
        })

    for key in buckets:
        buckets[key].sort(key=lambda x: x["code"])

    _LAST_CASHFLOW_EXCLUDED.clear()
    _LAST_CASHFLOW_EXCLUDED.update(excluded)
    return buckets


#: 中证官方估值源覆盖不到的指数：国证（非中证系列）与富时（无公开代码）
#: → 明确列出来，前端好解释「为什么这里是 —」，而不是让人以为是抓错了
CF_NO_DATA_INDICES: list[dict] = [
    {
        "code": "980092",
        "name": "国证自由现金流指数",
        "reason": "国证系列指数（深证信息发布），中证 csindex 估值接口不覆盖 → 无官方 PE",
    },
    {
        "code": "",
        "name": "富时中国A股自由现金流聚焦指数",
        "reason": "富时罗素编制、无公开通用指数代码 → 中证 / 国证两源都取不到估值",
    },
]


def _build_cf_index_metric(
    code: str, name: str, yield_10y: float | None, offline: bool = False
) -> dict:
    """单只现金流指数的估值（**只算 PE 一路**）。

    ⚠️ 为什么不复用 ``_build_index_metric``：红利那一版会在取不到股息率时回退到
    ``_DY_LAST``（上一次的历史值，并打 stale 标记），这套兜底对 2024 年底才发布、
    本来就没有官方股息率的现金流指数**毫无意义**（回退出来的就是 None），
    还会把本不属于它的股债比信号带出来。所以这版只在真正拿到股息率时才算 EB/股债比，
    拿不到就如实留 None + 说明文案，**绝不估算**。

    PE 源：``stock_zh_index_hist_csindex`` 的「滚动市盈率」（中证官方，随指数一起发布）。

    ``offline=True`` 时**不碰网络**：PE 只读已落库的 ``base_dividend_index_pe``
    （现金流指数同样在回填 PE 序列，2026-10-08 起可复用），供日常访问走本地基线。
    """
    if offline:
        series = _pe_get_series(code)
        rows = [{"日期": d, "滚动市盈率": v} for d, v in series]
    else:
        rows = [
            r
            for r in _fetch_index_hist(code)
            if _num(r.get("滚动市盈率")) is not None and r.get("日期")
        ]
        rows.sort(key=lambda r: str(r.get("日期"))[:10])

    pe_values = sorted(_num(r["滚动市盈率"]) for r in rows)
    latest = rows[-1] if rows else None
    pe = _num(latest.get("滚动市盈率")) if latest else None
    pe_date = str(latest.get("日期"))[:10] if latest else None
    pct = _percentile(pe_values, pe) if (pe is not None and pe_values) else None

    # 股息率：能拿到才算（风向变了、接口好了会自动有值），拿不到就是没有
    # ⚠️ offline 时不抓上游（现金流指数本就无官方股息率，抓了也是 None）
    dy, dy_date, dy_reason = None, None, CF_DY_UNAVAILABLE_REASON
    if not offline:
        usable = [
            r
            for r in _fetch_index_value(code)
            if _num(r.get("股息率1")) is not None and r.get("日期")
        ]
        if usable:
            top = max(usable, key=lambda r: str(r.get("日期"))[:10])
            dy, dy_date = _num(top.get("股息率1")), str(top.get("日期"))[:10]
            dy_reason = None

    eb_ratio = round(dy / yield_10y, 2) if (dy is not None and yield_10y) else None
    dy_spread = round(dy - yield_10y, 2) if (dy is not None and yield_10y is not None) else None

    sig_eb = _eb_signal(eb_ratio)
    sig_pe = _pe_signal(pct)
    sig_dy = _dy_signal(dy)
    actions = [s["action"] for s in (sig_eb, sig_pe, sig_dy) if s]

    def _q(p: float) -> float | None:
        if not pe_values:
            return None
        idx = min(len(pe_values) - 1, max(0, int(round((len(pe_values) - 1) * p))))
        return round(pe_values[idx], 2)

    return {
        "code": code,
        "name": name,
        "pe": pe,
        "pe_date": pe_date,
        "pe_percentile": pct,
        "pe_min": round(pe_values[0], 2) if pe_values else None,
        "pe_max": round(pe_values[-1], 2) if pe_values else None,
        "pe_p25": _q(0.25),
        "pe_median": _q(0.5),
        "pe_p75": _q(0.75),
        "window_days": len(pe_values),
        "window_start": str(rows[0].get("日期"))[:10] if rows else None,
        "pe_stale": False,
        "dividend_yield": dy,
        "dy_date": dy_date,
        "dy_reason": dy_reason,
        "dy_stale": False,
        "yield_10y": yield_10y,
        "eb_ratio": eb_ratio,
        "dy_spread": dy_spread,
        "signals": {"eb": sig_eb, "pe": sig_pe, "dy": sig_dy},
        "conflict": ("add" in actions) and ("stop" in actions or "reduce" in actions),
        "pe_series": _monthly_sample(rows),
        "source": "中证官方·指数日频（滚动市盈率）",
    }


def _build_cf_index_metrics(yield_10y: float | None, force: bool = False) -> list[dict]:
    """现金流指数池估值（并发限流 3，避免把中证打疼）。

    ⚠️ 只放**有代码且属于中证系列**的指数（932365/932366/932367/932368/932369）；
    国证 980092 与富时那条两个源都不覆盖，硬请求只会白等 → 走 ``CF_NO_DATA_INDICES`` 说明。

    ⚠️ **2026-10-08 加时间预算**（与红利页同款问题，此处原先是裸的
       ``with ThreadPoolExecutor`` + ``fut.result()``，上游一慢就把整个
       HTTP 请求拖死、且 ``__exit__`` 的 ``shutdown(wait=True)`` 让超时形同虚设）。
       现在：只有 ``force=True`` 才打上游，且整体限时 ``INDEX_BUILD_BUDGET_S``。
    """
    specs = [(c, n) for c, n, _reg, _al in CASHFLOW_INDICES if c.startswith("93")]
    if not specs:
        return []
    out: list[dict | None] = [None] * len(specs)

    if not force:
        # 日常访问：直接给本地数据（PE 读已落库的 base_dividend_index_pe）
        for i, (c, n) in enumerate(specs):
            out[i] = _build_cf_index_metric(c, n, yield_10y, offline=True)
        return [x for x in out if x]

    pool = ThreadPoolExecutor(max_workers=min(3, len(specs)))
    try:
        futures = {
            pool.submit(_build_cf_index_metric, c, n, yield_10y, False): i
            for i, (c, n) in enumerate(specs)
        }
        done_futs, not_done = wait(futures, timeout=INDEX_BUILD_BUDGET_S)
        if not_done:
            print(
                f"[Dividend] 现金流指数上游超时 {len(not_done)}/{len(futures)}"
                f"（预算 {INDEX_BUILD_BUDGET_S}s）"
            )
        for fut in done_futs:
            i = futures[fut]
            try:
                out[i] = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"[Dividend] 现金流指数 {specs[i][0]} 估值失败: {e}")
        # 超时的用本地数据兜底，避免整列变空
        for i, x in enumerate(out):
            if x is None:
                out[i] = _build_cf_index_metric(specs[i][0], specs[i][1], yield_10y, offline=True)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return [x for x in out if x]


def get_cashflow_overview(force: bool = False) -> dict:
    """现金流基金名录总览（**独立缓存**，与红利 361 只互不影响）。

    ⚠️ 取数只碰 ``fund_name_em``（全市场 2.8 万条，约 9s，**不碰中证接口**），
    因此冷启动首次调用会慢一点，之后走 6h 缓存。

    2026-10-07 用户拍板「2.动吧」：**补指数估值** → 这里同时返回 ``indices``
    （5 只中证现金流指数的 PE / 分位 / 信号），并把 PE 一行式回填到每只基金，
    用法与红利名录里「一只基金继承它所跟踪指数的估值」完全一致。
    """
    now = time.time()
    if force or not _CASHFLOW_CACHE["data"] or (now - _CASHFLOW_CACHE["ts"] > CASHFLOW_CACHE_TTL):
        funds = _build_cashflow_fund_list()
        if any(funds.values()):
            _CASHFLOW_CACHE["data"] = funds
            _CASHFLOW_CACHE["ts"] = now

    funds = _CASHFLOW_CACHE["data"] or {"etf": []}

    # ---- 指数估值（独立缓存 6h；失败不拖垮名录）----
    try:
        _cf_yield_10y, _cf_yield_date = _get_yield_10y()
    except Exception:  # noqa: BLE001
        _cf_yield_10y, _cf_yield_date = None, None
    if force or not _CASHFLOW_INDEX_CACHE["data"] or (
        now - _CASHFLOW_INDEX_CACHE["ts"] > CASHFLOW_CACHE_TTL
    ):
        metrics = _build_cf_index_metrics(_cf_yield_10y, force=force)
        if metrics:
            _CASHFLOW_INDEX_CACHE["data"] = metrics
            _CASHFLOW_INDEX_CACHE["ts"] = now
    cf_indices: list[dict] = _CASHFLOW_INDEX_CACHE["data"] or []

    # 每只基金继承它所跟踪指数的估值（与红利名录同一套玩法）
    by_code = {m["code"]: m for m in cf_indices}
    for r in funds.get("etf", []):
        m = by_code.get(r.get("index_code") or "")
        if not m:
            continue
        for k in (
            "pe",
            "pe_date",
            "pe_percentile",
            "pe_min",
            "pe_max",
            "pe_p25",
            "pe_median",
            "pe_p75",
            "window_days",
            "window_start",
            "dividend_yield",
            "dy_date",
            "dy_reason",
            "eb_ratio",
            "dy_spread",
            "signals",
            "conflict",
        ):
            r[k] = m.get(k)

    # ---- 规模 / 费率：复用红利那套后台渐进补全（2026-10-07 用户拍板「最好都扩」）----
    fee_codes, _fee_prog = fund_fee_service.attach_fees(funds)
    # 三项补充指标：跟踪误差 / 分红频率 / 行业集中度（后台渐进补全，落 DuckDB）
    _extra_codes, _extra_prog = fund_extra_metrics_service.attach_extra_metrics(funds)

    # 只吐 etf：场外被动（A/C/E 份额）已由 _build_cashflow_fund_list 归入 excluded["offshore"]
    mapped = {r["index_code"] for r in funds.get("etf", []) if r.get("index_code")}
    return {
        "funds": funds,
        "indices": cf_indices,
        # 估值源覆盖不到的指数：前端照着 reason 显示「为什么没有」，不假的填数
        "no_data_indices": CF_NO_DATA_INDICES,
        "yield_10y": _cf_yield_10y,
        "counts": {
            "etf": len(funds.get("etf", [])),
            "index": len(mapped),
            "index_valued": len(cf_indices),
            "excluded": sum(_LAST_CASHFLOW_EXCLUDED.values()),
            "excluded_detail": dict(_LAST_CASHFLOW_EXCLUDED),
        },
        # 口径说明：前端 Tab 顶部直接展示，避免被当成「官方编制」
        "gate": "只收场内 ETF + 名称含「现金流」；纯债 / 货币 / 主动 / 场外份额同样不入（与红利名录同一套类型口径）",
        "updated_at": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(_CASHFLOW_CACHE["ts"] or time.time())
        ),
        "index_updated_at": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(_CASHFLOW_INDEX_CACHE["ts"] or time.time())
        ),
        "fee_progress": fund_fee_service.snapshot(fee_codes),
        "extra_progress": fund_extra_metrics_service.snapshot(_extra_codes),
    }


# ============================================================
# 对外入口
# ============================================================

def get_dividend_overview(force: bool = False) -> dict:
    """红利研究总览：指数估值信号 + 红利基金名录（分 ETF / 被动场外 / 主动）。"""
    now = time.time()

    _dy_load_from_db()
    yield_10y, yield_10y_date = _get_yield_10y()

    # ---- 指数估值（两阶段构建，6h 缓存）----
    if force or not _INDEX_CACHE["data"] or (now - _INDEX_CACHE["ts"] > INDEX_CACHE_TTL):
        # ===== 阶段 1：纯本地基线（**不碰网络，微秒级**）=====
        # 先无网络算出全部 44 个指数。这样即便上游全挂 / 超时 / 被回填 job
        # 抢住资源，本次响应也**一个指数都不丢**（PE 来自
        # base_dividend_index_pe、股息率来自 _DY_LAST）。
        indices: list[dict] = [
            _build_index_metric(spec, yield_10y, offline=True) for spec in DIVIDEND_INDICES
        ]

        # ===== 阶段 2：上游刷新，**仅 force=True 时才做** =====
        # ⚠️ 为什么日常访问（force=0）不刷上游（2026-10-08 事故后调整）：
        #   页面日常看的是 6h 缓存，让**每次请求**去打 44 个指数的上游毫无意义，
        #   实测会把请求拖到 122s，且与回填 job 抢资源、加剧中证限流。
        #   上游刷新的职责归给：
        #     · 用户手动点「刷新」→ force=True（此刻等网络是合理的）
        #     · 定时回填 job →每天 07:20 小批量推进 PE 序列
        #   所以 force=False 走到这里就是**纯本地结果**，微秒级返回。
        n_upstream = 0
        if force:
            # ⚠️ 并发压到 26 会触发中证 403：限流到 6 并发
            pool = ThreadPoolExecutor(max_workers=min(6, len(DIVIDEND_INDICES)))
            try:
                futures = {
                    pool.submit(_build_index_metric, spec, yield_10y, False): i
                    for i, spec in enumerate(DIVIDEND_INDICES)
                }
                # ⚠️ **必须给整体加时间预算**（2026-10-08 事故）：
                #   上游可能整体变慢，逐个 ``fut.result()`` 无超时会把
                #   整个 HTTP 请求拖死 → 前端 HTTP=000（实测曾>150s 拿不到响应，
                #   而 /health 只要 3ms）。超时/失败的**保留阶段 1 的本地基线**。
                # ⚠️ ``wait()`` 返回 `DoneAndNotDoneFutures(done, not_done)` **二元组**，
                #   必须解包；直接对返回值迭代/取 len 会把 not_done 也当结果 → 500。
                done_futs, not_done = wait(futures, timeout=INDEX_BUILD_BUDGET_S)
                if not_done:
                    print(
                        f"[Dividend] 指数指标上游超时 {len(not_done)}/{len(futures)}"
                        f"（预算 {INDEX_BUILD_BUDGET_S}s），这些指数保留本地基线"
                    )
                for fut in done_futs:
                    i = futures[fut]
                    try:
                        got = fut.result()
                    except Exception as e:
                        print(f"[Dividend] 指数指标构建失败（用本地基线）: {e}")
                        continue
                    # ⚠️ 上游返回空壳（PE/股息率全None）时**不覆盖**基线，
                    #   否则限流中间态会把完整数据换成空数据（930838 式故障）。
                    if got is not None and (
                        got.get("pe") is not None or got.get("dividend_yield") is not None
                    ):
                        indices[i] = got
                        n_upstream += 1
                print(f"[Dividend] 上游数据覆盖 {n_upstream}/{len(futures)} 个指数，其余用本地基线")
            finally:
                # ⚠️ 不能用 `with pool:`——它的 __exit__ 会 shutdown(wait=True)，
                #   把超时放弃的 future 又等回来，前功尽弃。必须 cancel + 不等待。
                pool.shutdown(wait=False, cancel_futures=True)
        else:
            print(
                f"[Dividend] 日常访问：走本地基线（不刷上游，force=1 才刷新；"
                f"PE 序列由回填 job 每天推进）"
            )

        indices = [x for x in indices if x]
        _dy_save_to_db(indices)
        if indices:
            _INDEX_CACHE["data"] = indices
            _INDEX_CACHE["ts"] = now
        elif _INDEX_CACHE["data"]:
            indices = _INDEX_CACHE["data"]
    else:
        indices = _INDEX_CACHE["data"]

    # 10Y 每次取最新并回写，保证股债收益比不过期
    if indices:
        for item in indices:
            item["yield_10y"] = yield_10y
            if item.get("dividend_yield") is not None and yield_10y:
                item["eb_ratio"] = round(item["dividend_yield"] / yield_10y, 2)
                item["dy_spread"] = round(item["dividend_yield"] - yield_10y, 2)
                item["signals"]["eb"] = _eb_signal(item["eb_ratio"])

    # ---- 基金名录（24h 缓存）----
    if force or not _FUND_CACHE["data"] or (now - _FUND_CACHE["ts"] > FUND_CACHE_TTL):
        funds = _build_fund_list(indices)
        if any(funds.values()):
            _FUND_CACHE["data"] = funds
            _FUND_CACHE["ts"] = now
        elif _FUND_CACHE["data"]:
            funds = _FUND_CACHE["data"]
    else:
        funds = _FUND_CACHE["data"]

    # ---- 规模 / 费率（后台渐进补全，结果落 DuckDB）----
    funds = funds or {"etf": [], "passive": [], "active": []}
    fee_codes, _fee_prog = fund_fee_service.attach_fees(funds)

    # 「业绩比较基准」文本反查映射（库里已识别的直接回填，不新增请求）
    fund_index_map_service.augment_funds(funds)
    # 仍未识别的：回填它实际跟踪的指数原文，页面据此说明「不在 26 指数池内」
    fund_index_map_service.attach_tracking_texts(funds)
    # 三项补充指标：跟踪误差 / 分红频率 / 行业集中度（后台渐进补全，落 DuckDB）
    _extra_codes, _extra_prog = fund_extra_metrics_service.attach_extra_metrics(funds)

    return {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "yield_10y": yield_10y,
        "yield_10y_date": yield_10y_date,
        "indices": indices or [],
        "funds": funds,
        "fee_progress": fund_fee_service.snapshot(fee_codes),
        "extra_progress": fund_extra_metrics_service.snapshot(_extra_codes),
        "counts": {
            "etf": len((funds or {}).get("etf", [])),
            "passive": len((funds or {}).get("passive", [])),
            "active": len((funds or {}).get("active", [])),
            "index": len(indices or []),
            # 被闸门剔除的只数（纯债 / 主动 / 货币），让名录数量的变化可解释。
            # ⚠️ 故意不含 no_name_hit（那是全市场 2.7 万只压根不叫红利的产品，不是「剔除」）
            "excluded": _LAST_EXCLUDED.get("non_passive", 0)
            + _LAST_EXCLUDED.get("bond", 0)
            + _LAST_EXCLUDED.get("money", 0),
            "excluded_detail": dict(_LAST_EXCLUDED),
        },
        "thresholds": {
            "eb_add": EB_ADD,
            "eb_low": EB_LOW,
            "eb_risk": EB_RISK,
            "pe_reduce": PE_REDUCE,
            "pe_stop": PE_STOP,
            "pe_add": PE_ADD,
            "dy_hold": DY_HOLD,
            "dy_stop": DY_STOP,
        },
        "pending_fields": [],
    }


def get_dividend_fund_codes(force: bool = False) -> list[str]:
    """只取**红利名录**基金代码全集（**不触发中证指数取数**）。

    供费率补全的定时任务 / 手动端点使用：拿代码不需要 PE 与股息率，
    因此绝不调用 ``stock_zh_index_*``，避免在上游 403 封禁期反复打扰中证。
    """
    now = time.time()
    if force or not _CODES_CACHE["data"] or (now - _CODES_CACHE["ts"] > FUND_CACHE_TTL):
        funds = _FUND_CACHE["data"]
        if not funds or force:
            funds = _build_fund_list([])  # 仅拉基金名录（5MB），不碰指数接口
        codes = [str(r.get("code")) for rows in (funds or {}).values() for r in rows]
        if codes:
            _CODES_CACHE["data"] = codes
            _CODES_CACHE["ts"] = now
    return list(_CODES_CACHE["data"])


def get_cashflow_fund_codes() -> list[str]:
    """现金流**场内 ETF** 代码全集（供后台补全使用，与名录同一份缓存）。

    ⚠️ 只回场内那 33 只：场外 78 只绝大多数是同一指数的 A/C/E 份额，
    补全额度花在它们身上等于把同一份数据抓三遍。
    """
    funds = _CASHFLOW_CACHE["data"]
    if not funds or not (funds or {}).get("etf"):
        funds = _build_cashflow_fund_list()
        if funds.get("etf"):
            _CASHFLOW_CACHE["data"] = funds
            _CASHFLOW_CACHE["ts"] = time.time()
    return [str(r["code"]) for r in (funds or {}).get("etf", [])]


def get_backend_fund_codes(force: bool = False) -> list[str]:
    """**后台渐进补全的目标全集** = 红利名录 + 现金流场内 ETF（去重，红利在前）。

    2026-10-07 用户拍板「1.最好都扩」：现金流 33 只 ETF 与红利名录共用同一套后台补全
    （``fund_holdings_service`` 季报持仓 / ``fund_fee_service`` 规模费率），
    只是目标代码多了 33 只。**两边的前端口径互不干涉**，这里只扩后台取数范围。

    ⚠️ 顺序刻意让红利在前：补全任务是「先到先得」的按轮次取数，红利是主业不能排到队尾。
    """
    base = list(get_dividend_fund_codes(force))
    seen = set(base)
    extra = [c for c in get_cashflow_fund_codes() if c not in seen]
    return base + extra


def get_index_funds(index_code: str) -> dict:
    """单只红利指数 → **跟踪它的场内/场外基金** + **中证官方编制说明**。

    供前端「点指数行弹出基金清单」使用：
    - ``funds``：按 ``market`` 分成 ``onshore``（场内）/ ``offshore``（场外）；
    - ``compilation``：中证 ``index-basic-info`` 的官方编制说明；
      取数失败时为 ``None``（前端显示「暂不可得」，**不 mock**）。
    """
    overview = get_dividend_overview()
    funds = overview.get("funds") or {}
    idx = next((i for i in overview.get("indices") or [] if str(i.get("code")) == str(index_code)), None)

    matched: list[dict] = []
    for rows in funds.values():
        matched.extend(r for r in rows if str(r.get("index_code")) == str(index_code))
    onshore = [r for r in matched if r.get("market") == "场内"]
    offshore = [r for r in matched if r.get("market") != "场内"]

    # 代表基金的「业绩比较基准」：中证官方编制说明取不到时，用它当真实兜底素材
    bench_samples: list[dict] = []
    try:
        from database.connection import get_db

        codes = [str(r.get("code")) for r in matched]
        for i in range(0, len(codes), 300):
            chunk = codes[i: i + 300]
            marks = ",".join("?" for _ in chunk)
            rows = get_db().fetchall(
                f"SELECT code, name, benchmark FROM base_fund_fee_info WHERE code IN ({marks})",
                chunk,
            )
            for code, fname, benchmark in rows:
                if benchmark and str(benchmark) not in {b["benchmark"] for b in bench_samples}:
                    bench_samples.append({"code": code, "name": fname, "benchmark": str(benchmark)})
            if len(bench_samples) >= 6:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[Dividend] {index_code} 基准文本读取失败（忽略）: {e}")

    return {
        "code": str(index_code),
        "name": (idx or {}).get("name"),
        "pe": (idx or {}).get("pe"),
        "pe_percentile": (idx or {}).get("pe_percentile"),
        "dividend_yield": (idx or {}).get("dividend_yield"),
        "eb_ratio": (idx or {}).get("eb_ratio"),
        "signals": (idx or {}).get("signals"),
        "compilation": index_compilation_service.get_compilation(str(index_code)),
        "benchmark_samples": bench_samples[:6],
        "funds": {"onshore": onshore, "offshore": offshore},
        "counts": {
            "onshore": len(onshore),
            "offshore": len(offshore),
            "total": len(matched),
        },
    }


def refresh_dividend_cache() -> dict:
    """强制刷新缓存（指数估值 + 基金名录）。"""
    _INDEX_CACHE["ts"] = 0.0
    _INDEX_CACHE["data"] = None
    _FUND_CACHE["ts"] = 0.0
    _FUND_CACHE["data"] = None
    data = get_dividend_overview(force=True)
    return {"ok": True, "updated_at": data["updated_at"], "counts": data["counts"]}
