"""Fund service — LOF/QDII/closed-end fund data with arbitrage analysis.

真实数据来源：AkShare WebAPI 的 fund_rank 加工接口（新浪/同花顺基金涨跌排行，
覆盖 ETF/LOF/封闭式基金的 代码/名称/最新价/涨跌幅/成交额）。取数失败时返回空列表，
不使用 mock 数据。

说明：iopv / 溢价率 / 折溢价分位 / 套利收益 需要基金净值(NAV)源，当前 akshare 通用接口
未直接提供，故置 0（表示“暂无该数据源”，而非虚构数值），由分析层据此标注。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime

import requests

from core.config import AKSHARE_API_BASE, USE_MOCK_DATA
from utils.arbitrage import analyze_arbitrage
from utils.closed_fund import analyze_closed_fund
import mock_data


def _processed_data_request(category: str, params: dict | None = None, retries: int = 3) -> dict | list | None:
    """调用加工数据统一入口 (/api/processed_data)"""
    url = f"{AKSHARE_API_BASE}/api/processed_data"
    request_params = {"category": category}
    if params:
        request_params.update(params)

    for attempt in range(retries):
        try:
            print(f"[Fund Service] 调用 {category} (尝试 {attempt + 1}/{retries})...")
            response = requests.get(url, params=request_params, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 200:
                print(f"[Fund Service] {category} 返回错误: {result.get('message')}")
                return None

            data = result.get("data")
            data_info = len(data) if isinstance(data, list) else '对象'
            print(f"[Fund Service] {category} 成功，返回 {data_info} 数据")
            return data

        except requests.exceptions.Timeout:
            print(f"[Fund Service] {category} 超时 (attempt {attempt + 1}/{retries})")
        except requests.exceptions.ConnectionError as e:
            print(f"[Fund Service] {category} 连接错误: {e} (attempt {attempt + 1}/{retries})")
        except Exception as e:
            print(f"[Fund Service] {category} 错误: {e} (attempt {attempt + 1}/{retries})")

        if attempt < retries - 1:
            time.sleep(1)

    print(f"[Fund Service] {category} 所有重试失败")
    return None


def _pick(row: dict, *keys: str, default=None):
    """按候选键名取值（兼容新浪/同花顺等不同列名）。"""
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def _safe_float(value, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def get_funds_from_api(fund_subtype: str = "etf") -> list[dict]:
    """从真实 API 获取基金排行数据。

    Args:
        fund_subtype: etf / lof / closed / all
    """
    data = _processed_data_request("fund_rank", {"subtype": fund_subtype})

    if not data or not isinstance(data, list):
        print(f"[Fund Service] 获取 {fund_subtype} 失败，返回空列表")
        return []

    funds = []
    for item in data:
        subtype_map = {
            "etf": "etf",
            "lof": "lof",
            "closed": "closed",
        }
        fund_type = subtype_map.get(fund_subtype, "etf")

        name = str(_pick(item, "名称", "基金名称", default=""))
        code = str(_pick(item, "代码", "基金代码", default=""))
        if not code:
            continue

        # 53 fund_rank 已直接提供 净值 / 溢价率 / 净值日期（实测为真实值），
        # 无需自算。此前因硬编码 0 导致 ETF/LOF 套利页整表 No Data（A 类根因）。
        nav = _safe_float(_pick(item, "净值"))
        premium_pct = _safe_float(_pick(item, "溢价率"))
        # IOPV 对 ETF≈NAV；LOF 无 IOPV 概念，统一以 NAV 近似供前端展示。
        iopv = nav if nav else 0.0

        funds.append({
            "name": name,
            "code": code,
            "type": fund_type,
            "price": _safe_float(_pick(item, "最新价", "实时价", "当前单位净值")),
            "iopv": iopv,
            "premium_pct": premium_pct,
            "premium_percentile": 50,
            # 折溢价套利毛收益 = 溢价率（折价为负即反向套利空间），供 analyze_arbitrage 判定可行性。
            "net_arbitrage_yield": premium_pct,
            "nav": nav,
            "nav_date": _pick(item, "净值日期"),
            # 53 fund_rank 无成交额列 → 恒为 0（上游缺字段，非代码问题，属 C 类）。
            "volume": _safe_int(_pick(item, "成交额")),
            "category": "industry",
            "val_category": "normal",
            "change_pct": _safe_float(_pick(item, "涨跌幅", "增长率")),
        })

    print(f"[Fund Service] 成功获取 {len(funds)} 个 {fund_subtype}")
    return funds


def get_funds(
    fund_type: str | None = None,
    min_premium: float | None = None,
    feasibility: str | None = None,
    date: str | None = None,
    use_api: bool = True,
) -> list[dict]:
    """Return funds with attached arbitrage analysis (真实数据优先).

    Filters:
        fund_type:   match ``fund["type"]`` (etf/lof/qdii/closed).
        min_premium: include only funds with ``premium_pct >= min_premium``.
        feasibility: match ``arbitrage_analysis["feasibility"]``.
        date:        accepted for API compatibility (no-op).
        use_api:     保留参数以兼容旧调用；始终尝试真实取数。
    """
    if USE_MOCK_DATA:
        funds_data = mock_data.MOCK_FUNDS
        result: list[dict] = []
        for fund in funds_data:
            if fund_type and fund.get("type") != fund_type:
                continue
            if min_premium is not None and fund.get("premium_pct", 0) < min_premium:
                continue
            analysis = analyze_arbitrage(fund)
            if feasibility and analysis["feasibility"] != feasibility:
                continue
            result.append({**fund, "arbitrage_analysis": analysis})
        return result

    subtype_map = {
        "etf": "etf",
        "lof": "lof",
        "qdii": "etf",
        "closed": "closed",
    }
    if fund_type == "closed":
        # 封基走专用富集路径（腾讯补全场内价/成交额 + 折价率计算），
        # 避免列表页 premium_pct/volume 恒为 0（A 类根因）。
        funds_data = get_closed_funds_real() if use_api else []
    else:
        subtype = subtype_map.get(fund_type, "all")
        funds_data = get_funds_from_api(subtype) if use_api else []

    # 应用过滤和分析
    result: list[dict] = []
    for fund in funds_data:
        if min_premium is not None and fund.get("premium_pct", 0) < min_premium:
            continue

        analysis = analyze_arbitrage(fund)
        if feasibility and analysis["feasibility"] != feasibility:
            continue

        item = {**fund, "arbitrage_analysis": analysis}
        result.append(item)

    return result


def _get_closed_quotes_tencent(codes: list[str]) -> dict[str, dict]:
    """通过腾讯 qt.gtimg.cn 获取封闭基金场内实时行情（现价/涨跌幅/成交额）。

    53 的 fund_rank(closed) 仅给净值与收益率，无场内交易价；东方财富的
    fund_closed_end_em 在 53 上被掐，故用腾讯源降级。深交所代码前缀 sz、
    上交所前缀 sh。返回 {6位代码: {price, change_pct, volume(元)}}。
    """
    if not codes:
        return {}
    # 腾讯代码前缀：上交所 50/51 开头用 sh，其余 sz
    tencent_codes = [
        ("sh" if c.startswith(("50", "51")) else "sz") + c for c in codes
    ]
    result: dict[str, dict] = {}
    for i in range(0, len(tencent_codes), 8):
        batch = tencent_codes[i:i + 8]
        try:
            resp = requests.get(
                "https://qt.gtimg.cn/q=" + ",".join(batch),
                timeout=10,
            )
            text = resp.content.decode("gbk", "ignore")
        except Exception as e:
            print(f"[Closed Fund] 腾讯行情请求失败: {e}")
            continue
        for m in re.finditer(r'v_(\w+)="([^"]*)"', text):
            body = m.group(2)
            if not body or "none_match" in body:
                continue
            f = body.split("~")
            if len(f) < 36:
                continue
            code6 = f[2]
            price = _safe_float(f[3])
            if price <= 0:
                continue
            change_pct = _safe_float(f[32])
            # f[35] 形如 "成交额(万元)/成交量(手)/..."，封闭基金专用格式
            amount_part = f[35].split("/")[0] if len(f) > 35 and f[35] else ""
            amount_wan = _safe_float(amount_part)  # 万元
            result[code6] = {
                "price": price,
                "change_pct": change_pct,
                "volume": int(amount_wan * 10000),  # 折算为元
            }
    print(f"[Closed Fund] 腾讯行情命中 {len(result)}/{len(codes)} 只")
    return result


# 天天基金净值缓存（净值日频，缓存 1 小时足够）
_NAV_CACHE: dict[str, tuple[float, str, float]] = {}  # code -> (nav, nav_date, expire_ts)
_NAV_TTL = 3600


def get_fund_nav_eastmoney(code: str) -> dict | None:
    """天天基金净值源 (fund.eastmoney.com pingzhongdata)。

    53 的 fund_rank(closed) 仅部分基金给净值，且东方财富基金净值接口
    (fund_open_fund_info_em 等) 在 53 上被掐。天天基金 CDN 对本机直连可用，
    返回 Data_netWorthTrend（含最新单位净值与日期）。缓存避免重复请求。
    """
    now = time.time()
    cached = _NAV_CACHE.get(code)
    if cached and cached[2] > now:
        return {"nav": cached[0], "nav_date": cached[1]}
    try:
        resp = requests.get(
            f"https://fund.eastmoney.com/pingzhongdata/{code}.js",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://fundf10.eastmoney.com/",
            },
            timeout=12,
        )
        m = re.search(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", resp.text, re.S)
        if not m:
            return None
        arr = json.loads(m.group(1))
        if not arr:
            return None
        last = arr[-1]
        nav = _safe_float(last.get("y"))
        if not nav:
            return None
        ts = last.get("x", 0) / 1000
        nav_date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        _NAV_CACHE[code] = (nav, nav_date, now + _NAV_TTL)
        return {"nav": nav, "nav_date": nav_date}
    except Exception as e:
        print(f"[Closed Fund] 天天基金净值获取失败 {code}: {e}")
        return None


def _norm_code(code: str) -> str:
    """归一化基金代码为末 6 位数字，便于跨源匹配（集思录/53/腾讯可能带交易所前缀）"""
    digits = re.sub(r"\D", "", str(code))
    return digits[-6:] if len(digits) >= 6 else digits


def _fetch_jisilu_closed_nav() -> dict:
    """集思录封闭基金净值/折价率映射（归一化 code -> record）。

    作为更高优先级净值源补充；需 53 部署 akshareWebApi 的 jisilu 路由并配置 cookie（静态或动态）。
    任意失败（未部署/无 cookie/超时/网络异常）一律返回空 dict，不动现有 53+天天基金+硬编码兜底。
    """
    try:
        raw = _processed_data_request("jisilu", {"subtype": "closed_fund"}, retries=1)
        if not raw or not isinstance(raw, list):
            return {}
        # 打印一次列名，方便 53 实测校准中英文键名映射
        if raw:
            print(f"[Closed Fund] 集思录封闭基金列名样本: {list(raw[0].keys())}")
        mapping = {}
        for it in raw:
            code = _norm_code(_pick(it, "fund_id", "代码", "基金代码", default=""))
            if code:
                mapping[code] = it
        if mapping:
            print(f"[Closed Fund] 集思录封闭基金 {len(mapping)} 只已加载为净值补充源")
        return mapping
    except Exception as exc:
        print(f"[Closed Fund] 集思录净值源获取失败，回退现有源: {exc}")
        return {}


def _build_closed_funds_from_jisilu() -> list[dict]:
    """集思录封基列表（53 jisilu/closed_fund 路由 → /data/cf/cf_list + bond_list）。

    直接给出 现价/净值/折价率(discount_rt)/剩余年限(left_year)/年化折价率/
    到期日(maturity_dt)，#2 字段齐全。游客态约 20 只；53 配 jisilu cookie 返回全量。
    失败或空时返回 []，由调用方回退 53+腾讯路径。
    """
    try:
        raw = _processed_data_request("jisilu", {"subtype": "closed_fund"}, retries=1)
    except Exception as exc:
        print(f"[Closed Fund] 集思录封基列表获取异常: {exc}")
        return []
    if not raw or not isinstance(raw, list) or not raw:
        return []

    funds: list[dict] = []
    for rec in raw:
        code = str(_norm_code(_pick(rec, "fund_id", "代码", "基金代码", default="")))
        if not code:
            continue
        nav = _safe_float(_pick(rec, "fund_nav", "net_value", "净值", "单位净值"))
        price = _safe_float(_pick(rec, "price", "现价"))
        # 集思录 discount_rt 为正=折价；本项目 premium_pct 负=折价 → 取负。
        # 部分封基(临近到期/定开) discount_rt 为 "-"：回退按 (价-净值)/净值 计算。
        disc = _safe_float(_pick(rec, "discount_rt", "折价率", "折价"))
        if disc:
            premium = round(-disc, 2)
        elif nav and price:
            premium = round((price - nav) / nav * 100, 2)
        else:
            premium = 0.0
        left_year = _safe_float(_pick(rec, "left_year", "剩余年限", "剩余期限"))
        annualized = _safe_float(_pick(rec, "annualized", "annualize_dscnt_rt", "年化", "年化折价率"))
        end_date = _pick(rec, "end_date", "maturity_dt", "到期日", "到期时间")
        change = _safe_float(_pick(rec, "increase_rt", "涨跌幅"))
        vol = _safe_float(_pick(rec, "volume", "成交额"))
        # 集思录 volume 单位为万元 → 折算为元（与腾讯源口径一致）
        volume = int(vol * 10000) if vol else 0
        funds.append({
            "name": str(_pick(rec, "fund_nm", "名称", "基金名称", default="")),
            "code": code,
            "type": "closed",
            "price": price or 0,
            "iopv": 0,
            "premium_pct": premium,
            "premium_percentile": 50,
            "net_arbitrage_yield": premium,
            "volume": volume,
            # 剩余年限统一为 parse_remaining_days 可解析的 "X Years" 字符串
            "remaining_term": f"{left_year} Years" if left_year else None,
            "annualized": annualized or None,
            "est_ytm": None,
            "maturity": end_date or None,
            "nav": nav,
            "nav_date": _pick(rec, "nav_dt", "nav_date", "净值日期"),
            "credit_rating": _pick(rec, "rate", "评级", "信用评级") or None,
            "underlying_type": None,
            "is_lof_convertible": None,
            "change_pct": change,
        })
    return funds


def _build_closed_funds_from_rank() -> list[dict]:
    """回退路径：53 fund_rank(closed) 给列表与净值，腾讯补全场内行情。

    53 的 closed 列表仅含净值/收益率（无场内价、无成交额、无剩余期限/到期日）。
    - 场内价/成交额/涨跌幅：腾讯 qt.gtimg.cn 降级
    - 折价率：有净值时按 (场内价-净值)/净值 计算，否则为 0（诚实置 0 非虚构）
    - remaining_term/maturity/credit_rating/underlying_type/is_lof_convertible：
      53 现有源不提供，置 None（前端容错显示空）
    """
    raw = _processed_data_request("fund_rank", {"subtype": "closed"})
    if not raw or not isinstance(raw, list):
        print("[Closed Fund] fund_rank(closed) 取数失败，返回空列表")
        return []

    # 集思录封闭基金净值源（更高优先级净值/折价率/剩余年限等，失败静默回退现有源）
    jsl_nav_map = _fetch_jisilu_closed_nav()

    funds: list[dict] = []
    jsl_premium_by_code: dict[str, float] = {}  # 集思录折价率(已转成本项目符号：负=折价)
    for item in raw:
        code = str(_pick(item, "代码", "基金代码", default=""))
        if not code:
            continue
        nav = _safe_float(_pick(item, "净值"), None)  # mairui 净值，可能为空
        nav_date = None
        # 53 未给净值时，用天天基金净值源降级补全
        if not nav:
            nav_info = get_fund_nav_eastmoney(code)
            if nav_info:
                nav = nav_info["nav"]
                nav_date = nav_info["nav_date"]
        # 集思录净值优先覆盖（最高优先级净值源）。LOF 端点仅提供 fund_nav(净值)/nav_dt(净值日期)/
        # discount_rt(折价率)；剩余年限/年化回报/到期日/评级等字段 LOF 不提供，保持 None 由现有源/前端容错。
        jsl = jsl_nav_map.get(_norm_code(code))
        jsl_nav = _safe_float(_pick(jsl, "fund_nav", "nav", "净值", "单位净值")) if jsl else None
        if jsl_nav:
            nav = jsl_nav
            jsl_nav_dt = _pick(jsl, "nav_dt", "nav_date", "净值日期") if jsl else None
            if jsl_nav_dt:
                nav_date = jsl_nav_dt
        # 集思录字段提取：剩余年限/年化/到期日/评级/折价率。
        # 路由可用时填充，否则保持 None（由前端容错显示空，不虚构）。
        # 集思录 discount_rt 为正=折价，与本项目 premium_pct(负=折价) 符号相反，故取负。
        jsl_discount = _safe_float(_pick(jsl, "discount_rt", "折价率", "折价")) if jsl else None
        jsl_left_year = _safe_float(_pick(jsl, "left_year", "剩余年限", "剩余期限")) if jsl else None
        jsl_annualized = _safe_float(_pick(jsl, "annualized", "年化", "年化收益")) if jsl else None
        jsl_end_date = _pick(jsl, "end_date", "到期日", "到期时间") if jsl else None
        jsl_rate = _pick(jsl, "rate", "评级", "信用评级") if jsl else None
        if jsl_discount:
            jsl_premium_by_code[code] = round(-jsl_discount, 2)
        # 剩余年限统一为 parse_remaining_days 可解析的 "X Years" 字符串
        remaining_term = f"{jsl_left_year} Years" if jsl_left_year else None
        funds.append({
            "name": str(_pick(item, "名称", "基金名称", default="")),
            "code": code,
            "type": "closed",
            "price": _safe_float(_pick(item, "最新价")) or 0,
            "iopv": 0,
            "premium_pct": 0,
            "premium_percentile": 50,
            "net_arbitrage_yield": 0,
            "volume": 0,
            "remaining_term": remaining_term,
            "annualized": jsl_annualized or None,
            "est_ytm": None,
            "maturity": jsl_end_date,
            "nav": nav,
            "nav_date": nav_date,
            "credit_rating": jsl_rate,
            "underlying_type": None,
            "is_lof_convertible": None,
            "change_pct": _safe_float(_pick(item, "涨跌幅", "增长率")),
        })

    # 腾讯补全场内价 + 成交额 + 涨跌幅，并据净值算折价率
    quotes = _get_closed_quotes_tencent([f["code"] for f in funds])
    result: list[dict] = []
    for f in funds:
        q = quotes.get(f["code"])
        # 仅保留有真实场内交易的基金（腾讯未命中的多为场外 C 类，非场内封基）
        if not q or q["price"] <= 0:
            continue
        f["price"] = q["price"]
        f["volume"] = q["volume"]
        f["change_pct"] = q["change_pct"]
        jp = jsl_premium_by_code.get(f["code"])
        if jp is not None:
            # 集思录权威折价率优先
            f["premium_pct"] = jp
        elif f["nav"]:
            f["premium_pct"] = round((f["price"] - f["nav"]) / f["nav"] * 100, 2)
        result.append(f)

    print(f"[Closed Fund] 真实数据 {len(result)} 只（含腾讯行情补全，已过滤无场内交易品种）")
    return result


def get_closed_funds_real() -> list[dict]:
    """封闭基金真实数据。

    优先用集思录封基列表（53 jisilu/closed_fund 路由 → /data/cf/cf_list + bond_list）：
    直接给出 现价/净值/折价率/剩余年限/年化折价率/到期日，#2 字段齐全。
    游客态返回约 20 只；53 配 jisilu cookie 后返回全量（覆盖更多封基）。
    当集思录不可用（路由 500/空）时，回退 53 fund_rank(closed) + 腾讯行情补全。
    """
    jsl_funds = _build_closed_funds_from_jisilu()
    if jsl_funds:
        print(f"[Closed Fund] 集思录封基 {len(jsl_funds)} 只（#2 字段齐全）")
        return jsl_funds
    print("[Closed Fund] 集思录不可用，回退 53 fund_rank(closed) + 腾讯行情")
    return _build_closed_funds_from_rank()


def get_closed_fund_analysis(use_api: bool = True) -> list[dict]:
    """Return closed-end fund analysis, sorted by score descending (真实数据优先)."""
    if USE_MOCK_DATA:
        funds_data = [f for f in mock_data.MOCK_FUNDS if f.get("type") == "closed"]
        result: list[dict] = []
        for fund in funds_data:
            result.append(analyze_closed_fund(fund))
        result.sort(key=lambda x: x.get("score", 0), reverse=True)
        return result
    funds_data = get_closed_funds_real() if use_api else []

    result: list[dict] = []
    for fund in funds_data:
        analysis = analyze_closed_fund(fund)
        result.append(analysis)

    result.sort(key=lambda x: x.get("score", 0), reverse=True)
    return result
