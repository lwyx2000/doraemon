"""同标的跨基金溢价轮动 —— 「卖高溢价、买低溢价」的换仓候选。

## 为什么值得做（《无敌哥估值说明文档》3.14，最实战的一页）

同一底层资产常有多只场内基金并存（纳指100 同时有 513100 等 ETF 与 161130 等 LOF），
它们的合理净值几乎相同，但**二级市场溢价可以相差十几个百分点**。卖出溢价高的、
买入溢价低的，赚的是价差而不是方向——不占 QDII 额度、不做汇率判断。

## 两条关键口径约束

1. **组内必须同口径比。** `premium_pct` 是集思录/东财官方口径，`est_premium_pct` 是本项目
   自算口径，两者对 ETF 类可差 0.7~0.8pp（文档 5.2 实测）。混着比会把口径差当成机会，
   所以这里**先选一个口径**（谁覆盖的成员多用谁），只在该口径内部比。
2. **净值失效的不能参与。** 净值滞后 ≥5 个交易日的（513800 那种挂半年前的 EST 还在显示
   14.67% 溢价）会把组内极差撑爆，必须排除，并在 warnings 里点名。

## 成本假设
场内基金买卖无印花税，双边佣金按万分之五 + 冲击成本估算，合计 **0.10%**（保守）。这是
估算值，可按券商实际费率调整 `SWITCH_COST_PCT`；判定门槛：
  价差 − 成本 ≥ 1.0pp → switch（可换仓）；≥ 0.3pp → marginal（边缘）；否则 none。
"""

from __future__ import annotations

import json
import os
import threading
import time

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "qdii_baskets.json"
)

# 双边换仓成本（%）：佣金万分之五双边 + 冲击成本估算。无印花税。
SWITCH_COST_PCT = 0.10
_SWITCH_MIN_PCT = 1.0     # 扣成本后价差 ≥ 1.0pp 才算明确机会
_MARGINAL_MIN_PCT = 0.3   # 0.3~1.0pp 属边缘
_SUSPICIOUS_PREMIUM = 30.0  # |溢价| > 30% 多半流动性极差/数据异常，标注但仍展示
# 组内孤点剔除阈值：同指数纯跟踪品种的真实折溢价离散度很小。
#   严格组（A股宽基）：常态 0.5pp 内 → 2.5pp 已远超正常，多半是细分主题基金混入；
#   QDII 组：溢价受限购/额度影响可拉开很多（纳指实测 7~17pp），阈值放宽到 8pp。
_OUTLIER_PP_STRICT = 2.5
_OUTLIER_PP_QDII = 8.0

# 主题词黑名单：只对 strict 组（A股宽基）生效。
# 不加这层会出假信号 —— 实测「创业板」组会吸进创业板人工智能/医药/新能源等
# 主题 ETF，组内 74 只、价差算成 17.12pp，而那些根本不是同一个指数。
# 判定方式：名称去掉本组关键词后，若仍含**任何非本组关键词的**主题词 → 不是纯跟踪。
_THEME_WORDS = [
    "人工智能", "AI", "新能源", "光伏", "储能", "锂电", "电池", "风电", "氢能", "碳中和",
    "环保", "电力", "电网", "医药", "医疗", "生物", "创新药", "疫苗", "健康", "养老",
    "军工", "国防", "航空", "航天", "卫星", "机器人", "高端装备", "机械", "工程机械",
    "芯片", "半导体", "集成电路", "电子", "科技", "软件", "计算机", "通信", "5G",
    "云计算", "大数据", "数字经济", "信创", "传媒", "游戏", "动漫", "影视", "元宇宙",
    "消费", "白酒", "食品", "饮料", "家电", "农业", "养殖", "畜牧", "旅游", "酒店",
    "金融", "银行", "证券", "保险", "非银", "地产", "房地产", "建材", "建筑", "基建",
    "有色", "钢铁", "煤炭", "化工", "稀土", "新材料", "资源", "石油", "天然气",
    "自由现金流", "现金流", "红利", "股息",
    "汽车", "智能车", "新能车", "国企", "国有", "央企", "价值", "成长", "质量", "低波",
    "ESG", "责任", "增强", "指增", "量化", "对冲", "等权", "综指", "沪港深", "沪港",
    "港股", "恒生", "中概", "纳斯达克", "标普", "日经", "德国", "法国", "美国", "MSCI",
    "A500", "A50", "A100", "A股",
    "亚太", "全球", "海外", "跨境", "科创", "双创", "北证", "深证", "上证",
]

# 同标的组定义。anchors 命中「QDII 篮子主锚」；keywords 命中基金名（含 ETF/LOF 全称）。
# exclude 用来挡掉「同词不同标的」——最典型的是「黄金股ETF」（跟踪金矿股，不是金价）。
# strict: A股宽基组专用，要求名称是「公司名 + 指数名 + 通用后缀」，混进主题词就剔除。
PEER_GROUPS: list[dict] = [
    {"key": "ndx100", "name": "纳指100", "anchors": ["QQQ"],
     "keywords": ["纳指", "纳斯达克100", "纳斯达克指数"], "exclude": []},
    {"key": "sp500", "name": "标普500", "anchors": ["SPY", "VOO", "IVV"],
     "keywords": ["标普500"], "exclude": []},
    {"key": "dow", "name": "道琼斯", "anchors": ["DIA"],
     "keywords": ["道琼斯"], "exclude": []},
    {"key": "gold", "name": "黄金", "anchors": ["GLD", "IAU"],
     "keywords": ["黄金", "金ETF"], "exclude": ["股", "矿", "白银"]},
    {"key": "silver", "name": "白银", "anchors": ["SLV"],
     "keywords": ["白银"], "exclude": ["股", "矿"]},
    # 油气拆三组：商品原油（期货/现货）、美股油气公司、A股油气公司。
    # 底层资产完全不同，混在一起比溢价没有意义（2026-11-03 实测：不拆会把
    # 中证油气产业ETF(国内油企) 和 标普石油天然气ETF(美股油企) 塞进同一组）。
    {"key": "crude", "name": "商品原油", "anchors": ["USO", "CL"],
     "keywords": ["原油"], "exclude": ["股", "油气"]},
    {"key": "oil_us", "name": "美股油气", "anchors": ["XOP"],
     "keywords": ["华宝油气", "石油天然气", "美国石油", "标普油气"], "exclude": []},
    {"key": "oil_cn", "name": "A股油气", "anchors": [],
     "keywords": ["油气"], "exclude": ["标普", "华宝"]},
    {"key": "hstech", "name": "恒生科技", "anchors": ["3033", "KTEC"],
     "keywords": ["恒生科技"], "exclude": []},
    {"key": "hbar", "name": "恒生红利", "anchors": [],
     "keywords": ["恒生红利", "港股通红利"], "exclude": []},
    {"key": "cninternet", "name": "中概互联", "anchors": ["KWEB"],
     "keywords": ["中概互联", "中国互联", "海外互联网"], "exclude": []},
    {"key": "japan", "name": "日经225", "anchors": ["EWJ", "NKY"],
     "keywords": ["日经", "日本"], "exclude": ["日本REIT"]},
    {"key": "germany", "name": "德国DAX", "anchors": ["EWG"],
     "keywords": ["德国"], "exclude": []},
    {"key": "france", "name": "法国CAC", "anchors": ["EWQ"],
     "keywords": ["法国"], "exclude": []},
    {"key": "nasdaq_tech", "name": "海外科技", "anchors": ["SOXX", "XLK"],
     "keywords": ["海外科技", "全球科技"], "exclude": []},
    # A 股宽基：指数增强/指增的净值含主动超额，与纯跟踪 ETF 不可比（实测混进来过
    # 161039 富国中证1000指数增强，折价 −0.54% 会被当成"最该卖"的那只）
    {"key": "hs300", "name": "沪深300", "anchors": [], "strict": True,
     "keywords": ["沪深300"], "exclude": ["300价值", "300成长", "300医药", "300非周", "增强", "指增"]},
    {"key": "zz500", "name": "中证500", "anchors": [], "strict": True,
     "keywords": ["中证500"], "exclude": ["500质量", "增强", "指增"]},
    {"key": "zz1000", "name": "中证1000", "anchors": [], "strict": True,
     "keywords": ["中证1000"], "exclude": ["增强", "指增"]},
    {"key": "zz2000", "name": "中证2000", "anchors": [], "strict": True,
     "keywords": ["中证2000"], "exclude": ["增强", "指增"]},
    {"key": "cyb", "name": "创业板", "anchors": [], "strict": True,
     "keywords": ["创业板"],
     "exclude": ["创业板50", "创业板200", "创业板300", "创业板综", "增强", "指增"]},
    {"key": "cyb50", "name": "创业板50", "anchors": [], "strict": True,
     "keywords": ["创业板50"], "exclude": ["增强", "指增"]},
    {"key": "star50", "name": "科创50", "anchors": [], "strict": True,
     "keywords": ["科创50"], "exclude": ["增强", "指增"]},
    # 红利拆两组：「红利低波」和「纯红利（中证/上证/深证红利）」跟踪的是不同指数，
    # 混在一起会把指数差当价差（2026-11-03 实测 44 只混成一组，spread 2.19pp 不可解释）。
    {"key": "div_lv", "name": "红利低波", "anchors": [], "strict": True,
     "keywords": ["红利低波"], "exclude": ["恒生", "港股", "消费", "央企", "国企"]},
    {"key": "div_plain", "name": "红利", "anchors": [], "strict": True,
     "keywords": ["红利ETF", "中证红利", "上证红利", "深证红利"],
     "exclude": ["恒生", "港股", "消费", "低波", "央企", "国企", "价值"]},
]

_CACHE_TTL = 120
_cache: dict[str, object] = {"ts": 0.0, "data": None, "meta": {}}
_lock = threading.Lock()


def _load_basket_anchors() -> dict[str, str]:
    """基金代码 → 篮子**主锚**（权重最大的成分）。用于把 LOF/QDII 归到同标的组。"""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[FundRotation] 篮子配置读取失败（忽略）: {type(e).__name__}: {e}")
        return {}
    out: dict[str, str] = {}
    for code, item in (cfg.get("funds") or {}).items():
        basket = (item or {}).get("basket") or []
        best, best_w = None, -1.0
        for leg in basket:
            try:
                w = float(leg.get("weight") or 0)
            except (TypeError, ValueError):
                continue
            if w > best_w:
                best, best_w = str(leg.get("symbol") or ""), w
        if best:
            out[str(code)] = best.upper()
    return out


def _name_matches(name: str, group: dict) -> bool:
    """名称是否属于该组。strict 组额外要求「纯跟踪」：去掉本组关键词后不得残留主题词。"""
    kws = group["keywords"]
    if any(x in name for x in group.get("exclude") or []):
        return False
    if not any(k in name for k in kws):
        return False
    if not group.get("strict"):
        return True
    rest = name
    for k in kws:
        rest = rest.replace(k, "")
    for w in _THEME_WORDS:
        # 主题词本身是本组关键词的一部分时不算越界（如「红利」组遇到「红利」二字）
        if w in rest and not any(w in k for k in kws):
            return False
    return True


def _match_group(fund: dict, anchors: dict[str, str]) -> dict | None:
    """先按篮子主锚精确匹配，再按名称关键词匹配。"""
    code = str(fund.get("code") or "")
    anchor = anchors.get(code)
    if anchor:
        for g in PEER_GROUPS:
            if anchor in {a.upper() for a in g["anchors"]}:
                return g

    name = str(fund.get("name") or "")
    if not name:
        return None
    for g in PEER_GROUPS:
        if _name_matches(name, g):
            return g
    return None


def _kind(fund: dict) -> str:
    """按代码段判断品种（ETF / LOF）。

    不能用 `type` 字段：`/funds?type=all` 走 `get_funds_from_api("all")` 时
    subtype_map 取默认值 "etf"，4825 只全被标成 etf，靠它判断「ETF/LOF 混比」
    永远判不出来。代码段是可靠的：
      15x（159 等）= 深交所 ETF；51/52/56/58 = 上交所 ETF；
      16x / 50x（501/502/506）= LOF。
    """
    c = str(fund.get("code") or "")
    if c.startswith("159") or c[:2] in ("51", "52", "56", "58"):
        return "etf"
    if c.startswith("16") or c.startswith("50"):
        return "lof"
    return str(fund.get("type") or "other")


def _premium(fund: dict, basis: str) -> float | None:
    """取指定口径的溢价率；官方口径的 0 是缺值占位，不作为有效值。"""
    if basis == "est":
        v = fund.get("est_premium_pct")
        return float(v) if v is not None else None
    v = fund.get("premium_pct")
    if v is None:
        return None
    v = float(v)
    return None if v == 0.0 else v


def _keep_latest_nav_date(usable: list[dict], excluded: list[dict], warnings: list[str]) -> list[dict]:
    """组内只保留最新一个净值日的成员。

    官方溢价 = 价格/T-1净值 − 1，里面含当日涨跌 R。同指数组内 R 相同、相减能抵消，
    但净值日差一天（T-1 vs T-2）就会让 R 差一整个交易日 —— 那是 1~3pp 的假价差，
    比真实的折溢价差还大。宁可少几只，也不能让「昨天的涨跌」冒充「今天的套利空间」。
    """
    from collections import Counter

    dates = [str(x["fund"].get("nav_date") or "")[:10] for x in usable]
    dates = [d for d in dates if d]
    if not dates:
        return usable
    latest = Counter(dates).most_common(1)[0][0]
    kept: list[dict] = []
    for x in usable:
        d = str(x["fund"].get("nav_date") or "")[:10]
        if d and d != latest:
            excluded.append({
                "code": x["fund"].get("code"), "name": x["fund"].get("name"),
                "premium_pct": round(x["premium"], 2), "nav_date": d,
                "nav_lag_days": x["fund"].get("nav_lag_days"),
                "reason": f"净值日 {d} 与组内 {latest} 不一致",
            })
            continue
        kept.append(x)
    if len(kept) < len(usable):
        warnings.append(
            f"已剔除 {len(usable) - len(kept)} 只净值日滞后的成员（组内统一用 {latest}），"
            "避免一天的涨跌被算成折溢价差"
        )
    return kept


def _prune_outliers(usable: list[dict], group: dict, excluded: list[dict], warnings: list[str]) -> list[dict]:
    """剔除「偏离组内中位过远」的孤点成员。

    名称黑名单挡不住全部细分主题基金（创业板算力基础设施 / 中证500信息技术 / 沪深300自由现金流…），
    这类基金当日涨跌和本组指数差一个板块，会被算成几 pp 的假溢价——而且往往正好成为
    「最该买」的那一只。所以再按偏离中位剔除：同指数纯跟踪品种的真实折溢价离散度很小
    （A股常态 0.5pp 内，QDII 因限购可到 8pp），超出即视为不同标的或数据异常。
    """
    limit = _OUTLIER_PP_STRICT if group.get("strict") else _OUTLIER_PP_QDII
    cur = list(usable)
    dropped: list[tuple[str, str, float]] = []   # (code, name, 偏离pp)
    while len(cur) > 3:  # 剩 3 只时已无法判断谁是孤点，交给 warnings 提示
        vals = sorted(x["premium"] for x in cur)
        med = vals[len(vals) // 2]
        worst = max(cur, key=lambda x: abs(x["premium"] - med))
        dev = worst["premium"] - med
        if abs(dev) <= limit:
            break
        cur = [x for x in cur if x is not worst]
        code = str(worst["fund"].get("code"))
        name = str(worst["fund"].get("name"))
        dropped.append((code, name, dev))
        excluded.append({
            "code": code, "name": name,
            "premium_pct": round(worst["premium"], 2),
            "nav_date": worst["fund"].get("nav_date"),
            "nav_lag_days": worst["fund"].get("nav_lag_days"),
            "reason": f"偏离组内中位 {dev:+.2f}pp（阈值 {limit}pp）",
        })
    if dropped:
        # 同一批主题基金（如 10 只「创业板算力基础设施」同时上市）会一起被剔，
        # 逐条写会刷屏，合并成一条摘要，明细留在 excluded 里供前端展开
        head = "、".join(f"{c}({d:+.1f}pp)" for c, _, d in dropped[:3])
        more = f" 等 {len(dropped)} 只" if len(dropped) > 3 else ""
        warnings.append(
            f"已剔除偏离组内中位过远的成员：{head}{more}——同一指数纯跟踪品种的折溢价离散度很小，"
            "偏离这么大通常说明跟踪的不是同一指数（细分主题基金），明细见剔除列表"
        )
    return cur


def _pick_basis(members: list[dict]) -> str | None:
    """组内口径一致性：自算口径覆盖过半数就用自算，否则退官方口径。

    为什么不单纯「谁覆盖多就用谁」：官方 `premium_pct` 对 ETF 类系统性高于参考净值
    0.7~0.8pp（文档 5.2 实测），组内一旦混了 ETF 和 LOF，这个偏差会被当成价差。
    自算 `est_premium_pct` 对两类走同一套篮子公式，跨类型可比——所以只要它还能覆盖
    组内一半以上成员，就宁可少几只也要用同一个口径比。
    """
    total = len(members)
    n_est = sum(1 for f in members if _premium(f, "est") is not None)
    n_off = sum(1 for f in members if _premium(f, "official") is not None)
    if n_est >= 2 and n_est * 2 >= total:
        return "est"
    if n_off >= 2:
        return "official"
    return None


def _build_group(g: dict, members: list[dict]) -> dict | None:
    basis = _pick_basis(members)
    if basis is None:
        return None

    usable: list[dict] = []
    excluded: list[dict] = []
    warnings: list[str] = []
    for f in members:
        level = f.get("nav_stale_level")
        prem = _premium(f, basis)
        if prem is None:
            # 选了自算口径却没这只的 est → 说明它不在 QDII 篮子配置里或快照未就绪，
            # 记下来，别让用户以为「组里就只有这么几只」
            if basis == "est":
                excluded.append({
                    "code": f.get("code"), "name": f.get("name"),
                    "premium_pct": round(float(f.get("premium_pct") or 0), 2),
                    "nav_date": f.get("nav_date"), "nav_lag_days": f.get("nav_lag_days"),
                    "reason": "无自算估值口径",
                })
            continue
        if level == "stale":
            excluded.append({
                "code": f.get("code"), "name": f.get("name"),
                "premium_pct": round(prem, 2), "nav_date": f.get("nav_date"),
                "nav_lag_days": f.get("nav_lag_days"), "reason": "净值失效",
            })
            warnings.append(
                f"{f.get('code')} {f.get('name')} 净值停在 {f.get('nav_date')}"
                f"（落后 {f.get('nav_lag_days')} 个交易日），溢价不可比，已剔除"
            )
            continue
        usable.append({"fund": f, "premium": prem})

    if len(usable) < 2:
        return None

    # ---- 数据一致性防线（官方口径必做）----
    # 本项目的 iopv 字段实际就是 T-1 官方净值（fund_service: iopv = nav），
    # 所以「官方溢价」= 价格/T-1净值 − 1，里面混着当日涨跌 R：
    #     prem_official ≈ (1+真实溢价)(1+R) − 1
    # 同指数组内 R 相同 → 相减时抵消（只差一个 (1+R) 缩放），价差基本可用；
    # 但两种情况会让 R 不再抵消、直接冒充成溢价差，必须挡掉：
    #   ① 净值日不一致（T-1 vs T-2）→ R 差一天
    #   ② 混入细分主题基金（「创业板算力基础设施」跟的不是创业板指）→ R 差一个板块
    if basis == "official":
        usable = _keep_latest_nav_date(usable, excluded, warnings)
        if len(usable) < 2:
            return None
        usable = _prune_outliers(usable, g, excluded, warnings)
        if len(usable) < 2:
            return None

    # 退到官方口径时，若组内跨了 ETF/LOF，口径差会污染价差，必须点明
    if basis == "official":
        kinds = {_kind(x["fund"]) for x in usable}
        if len(kinds) > 1:
            if g.get("strict"):
                warnings.append(
                    "组内混用 " + "/".join(sorted(kinds)) + "：官方口径下两类都用 T-1 净值，"
                    "当日涨跌在组内抵消；但 LOF 折溢价还受申赎状态影响，价差需打折看"
                )
            else:
                warnings.append(
                    "组内混用 " + "/".join(sorted(kinds)) + "，官方口径对 ETF 系统性偏高约 0.7pp，"
                    "价差需打折看"
                )

    usable.sort(key=lambda x: x["premium"])
    lo, hi = usable[0], usable[-1]
    spread = hi["premium"] - lo["premium"]
    net = spread - SWITCH_COST_PCT

    def _row(x: dict) -> dict:
        f = x["fund"]
        return {
            "code": f.get("code"),
            "name": f.get("name"),
            "type": f.get("type"),
            "kind": _kind(f),
            "price": f.get("price"),
            "nav": f.get("nav"),
            "premium_pct": round(x["premium"], 2),
            "nav_date": f.get("nav_date"),
            "nav_lag_days": f.get("nav_lag_days"),
            "nav_stale_level": f.get("nav_stale_level"),
            "volume": f.get("volume"),
            "est_method": f.get("est_method"),
            "premium_gap": f.get("premium_gap"),
        }

    if spread > _SUSPICIOUS_PREMIUM:
        warnings.append(
            f"组内价差 {spread:.2f}pp 偏大，常见于流动性极差或限购品种，换仓前先看成交额"
        )
    elif g.get("strict") and spread > 5.0:
        # A 股同指数 ETF 的溢价离散度常态在 3pp 内；超过 5pp 多半是名称匹配吸进了
        # 细分指数产品（创业板200/300、自由现金流、A500红利等），名字识别不可能穷尽
        warnings.append(
            f"组内价差 {spread:.2f}pp 偏大（A股同指数 ETF 常态 3pp 内），"
            "可能混入了细分指数产品，换仓前请核对跟踪标的"
        )

    return {
        "group": g["key"],
        "group_name": g["name"],
        "premium_basis": basis,           # est=自算口径 / official=官方口径
        "count": len(usable),
        "premium_min": round(lo["premium"], 2),
        "premium_max": round(hi["premium"], 2),
        "premium_median": round(sorted(x["premium"] for x in usable)[len(usable) // 2], 2),
        "spread": round(spread, 2),
        "net_edge": round(net, 2),
        "action": "switch" if net >= _SWITCH_MIN_PCT else ("marginal" if net >= _MARGINAL_MIN_PCT else "none"),
        # 建议卖出高溢价的、买入低溢价的（同为多头敞口，不改变仓位方向）
        "sell": _row(hi),
        "buy": _row(lo),
        "members": [_row(x) for x in sorted(usable, key=lambda x: -x["premium"])],
        "excluded": excluded,
        "warnings": warnings,
    }


def _load_funds() -> list[dict]:
    """取全市场基金；`all` 不可用时降级为 etf + lof 合并（去重）。

    为什么需要降级：网关 `processed_data?subtype=all` 在多副本间不一致，
    实测约一半请求 404。轮动接口若直接依赖它就有一半概率空表。
    """
    from services.fund_service import get_funds

    funds, _meta = get_funds("all")
    if funds:
        return funds

    merged: list[dict] = []
    seen: set[str] = set()
    for st in ("etf", "lof"):
        part, _ = get_funds(st)
        for f in part or []:
            code = str(f.get("code") or "")
            if code and code not in seen:
                seen.add(code)
                merged.append(f)
    if merged:
        print(f"[FundRotation] all 不可用，降级 etf+lof 合并 {len(merged)} 只")
    return merged


def get_rotation_groups(force: bool = False) -> tuple[list[dict], dict]:
    """返回按「扣成本后价差」降序的同标的组，与统计 meta。"""
    now = time.time()
    with _lock:
        ts = float(_cache.get("ts") or 0)
        cached = _cache.get("data")
        if not force and cached is not None and (now - ts) < _CACHE_TTL:
            return cached, dict(_cache.get("meta") or {})  # type: ignore[return-value]

    # 陈旧度筛选依赖交易日历。日历未就绪时 nav_stale_level 全是 None，
    # 513800 那种「净值停半年前还挂着 14% 溢价」会混进组内把价差撑爆 ——
    # 所以宁愿明说「本轮没筛陈旧度」，也不能让用户以为已经是干净结果。
    calendar_ready = True
    try:
        from services import trading_calendar as tc

        calendar_ready = tc.is_loaded()
        if not calendar_ready:
            threading.Thread(target=tc.load_trading_days, name="tc-warm-rotation",
                             daemon=True).start()
    except Exception as e:
        calendar_ready = False
        print(f"[FundRotation] 交易日历检查失败（忽略）: {type(e).__name__}: {e}")

    funds = _load_funds()
    if not funds:
        # 网关缺 all 子集时仍可能给出 etf/lof —— 返回空比报错好，但要有痕迹
        print("[FundRotation] 全量基金列表为空（网关 fund_rank 不可用），本轮无分组")
    anchors = _load_basket_anchors()

    buckets: dict[str, tuple[dict, list[dict]]] = {}
    for f in funds or []:
        g = _match_group(f, anchors)
        if not g:
            continue
        buckets.setdefault(g["key"], (g, []))[1].append(f)

    groups: list[dict] = []
    for g, members in buckets.values():
        if len(members) < 2:
            continue
        try:
            built = _build_group(g, members)
        except Exception as e:
            print(f"[FundRotation] 组 {g['key']} 计算异常: {type(e).__name__}: {e}")
            continue
        if built:
            groups.append(built)

    groups.sort(key=lambda x: -x["net_edge"])
    meta = {
        "groups": len(groups),
        "switchable": sum(1 for g in groups if g["action"] == "switch"),
        "funds": sum(g["count"] for g in groups),
        "costPct": SWITCH_COST_PCT,
        "thresholds": {"switch": _SWITCH_MIN_PCT, "marginal": _MARGINAL_MIN_PCT},
        "staleFilter": calendar_ready,
        "warning": (
            None if calendar_ready else
            "交易日历未就绪，本轮未做净值陈旧度筛选（后台预热中），"
            "价差可能包含净值已失效的品种，请核对各成员净值日期后再换仓"
        ),
        "updateTime": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _lock:
        _cache["ts"] = time.time()
        _cache["data"] = groups
        _cache["meta"] = meta
    return groups, meta
