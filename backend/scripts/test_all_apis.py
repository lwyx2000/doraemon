#!/usr/bin/env python
"""
Automated API test script — tests all backend endpoints and reports results.
Usage: python backend/scripts/test_all_apis.py
"""
import json
import requests
import sys

BASE = "http://localhost:8001/api/v1"
TOKEN = None
results = []

def login():
    global TOKEN
    r = requests.post(f"{BASE}/auth/login", json={"username": "testbot", "password": "Test1234!"})
    data = r.json()
    if data.get("code") == 200:
        TOKEN = data["data"]["token"]
        return True
    r2 = requests.post(f"{BASE}/auth/register", json={"username": "testbot", "password": "Test1234!"})
    if r2.status_code == 200:
        TOKEN = r2.json().get("data", {}).get("token")
        if TOKEN:
            return True
    return False

def headers():
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

def test(name, method, path, body=None, expect_status=200, auth=True, timeout=15):
    url = f"{BASE}{path}"
    h = headers() if auth else {}
    h["Content-Type"] = "application/json"
    try:
        resp = requests.request(method, url, json=body, headers=h, timeout=timeout)
        ok = resp.status_code == expect_status
        try:
            j = resp.json()
            has_data = j.get("code") == 200 or j.get("data") is not None or isinstance(j, list)
        except:
            j = resp.text[:200]
            has_data = resp.status_code == 200

        status = "PASS" if (ok and has_data) else "FAIL"
        results.append({
            "name": name, "method": method, "path": path,
            "status": status, "http_code": resp.status_code,
            "detail": "OK" if ok else (str(j)[:300] if not ok else "OK")
        })
    except Exception as e:
        results.append({
            "name": name, "method": method, "path": path,
            "status": "ERROR", "http_code": 0, "detail": str(e)[:200]
        })

def main():
    if not login():
        print("FATAL: Cannot login")
        sys.exit(1)
    print(f"Login OK")

    # 1. Market / Dashboard
    test("market_overview", "GET", "/market/overview")
    test("market_board_sectors", "GET", "/market/board-sectors")
    test("market_fund_flows", "GET", "/market/fund-flows")
    test("market_zt_stats", "GET", "/market/zt-stats")
    test("market_fund_ranking", "GET", "/market/fund-ranking")
    test("market_macro_indicators", "GET", "/market/macro/indicators")
    test("market_status", "GET", "/market/status")
    test("market_sw_sectors", "GET", "/market/sw-sectors")
    test("market_sw_strength", "GET", "/market/sw-sectors/relative-strength")
    # 首次调用要打到本地 akshare（约 30s），超时需放宽
    test("market_sw_valuation", "GET", "/market/sw-sectors/valuation-history?sector_code=801010", timeout=180)
    test("market_precious_metals", "GET", "/market/precious-metals")

    # 2. Index Analysis (under /market/indices)
    test("market_indices_list", "GET", "/market/indices")
    test("market_index_history", "GET", "/market/indices/000300/history?days=30")

    # 3. Funds (LOF/QDII/Closed) — prefix /funds
    test("funds_all", "GET", "/funds")
    test("funds_lof", "GET", "/funds?type=lof")
    test("funds_qdii", "GET", "/funds?type=qdii")
    test("funds_closed", "GET", "/funds?type=closed")
    test("funds_closed_analysis", "GET", "/funds/closed/analysis")

    # 4. ETF — prefix /etf
    test("etf_list", "GET", "/etf/etfs")
    test("etf_arbitrage", "GET", "/etf/etfs/arbitrage")

    # 5. Convertible Bonds — prefix /cb
    test("cb_list", "GET", "/cb/convertible-bonds")

    # 6. REITs — prefix /reits
    test("reits_list", "GET", "/reits/reits")

    # 7. Strategy (custom)
    test("strategy_meta", "GET", "/strategies/meta")
    test("strategy_list", "GET", "/strategies")
    test("strategy_create", "POST", "/strategies", {
        "name": "test_auto",
        "target_asset": "cb",
        "rules": [
            {"field": "price", "operator": "<", "value": "130", "logic": "AND"},
            {"field": "premium_pct", "operator": "<", "value": "15", "logic": "AND"},
        ],
        "sort_by": "double_low_score",
        "sort_order": "asc",
        "limit_count": 5,
    })
    test("strategy_execute_1", "POST", "/strategies/1/execute")

    # 8. Strategy Library
    test("library_list", "GET", "/strategy-library/library")
    test("library_tracked", "GET", "/strategy-library/tracked")

    # 9. Signals
    test("signal_strategies", "GET", "/signals/strategies")
    test("signal_tracked", "GET", "/signals/tracked")

    # 10. Alert Center
    test("alert_rules", "GET", "/alerts/rules")
    test("alert_events", "GET", "/alerts/events")

    # 11. Broker Accounts
    test("broker_accounts", "GET", "/broker-accounts")
    test("account_names", "GET", "/account-names")

    # 12. Holdings
    test("holdings", "GET", "/holdings")
    test("holdings_snapshots", "GET", "/holdings/snapshots")

    # 13. Monitor / Cache / Notification
    test("monitor_dashboard", "GET", "/monitor/dashboard")
    test("notification_config", "GET", "/notifications/config")

    # 14. AI
    test("ai_config", "GET", "/ai/config")
    test("ai_reports", "GET", "/ai/reports")

    # Print Summary
    print("\n" + "=" * 80)
    print(f"API TEST RESULTS - {len(results)} tests")
    print("=" * 80)

    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]
    errors = [r for r in results if r["status"] == "ERROR"]

    print(f"\nPASS: {len(passed)}")
    print(f"FAIL: {len(failed)}")
    print(f"ERROR: {len(errors)}")

    if failed:
        print("\n--- FAILED TESTS ---")
        for r in failed:
            print(f"  [{r['method']}] {r['path']}")
            print(f"    Name: {r['name']}")
            print(f"    HTTP: {r['http_code']}")
            print(f"    Detail: {r['detail'][:200]}")

    if errors:
        print("\n--- ERROR TESTS ---")
        for r in errors:
            print(f"  [{r['method']}] {r['path']}")
            print(f"    Name: {r['name']}")
            print(f"    Error: {r['detail'][:200]}")

    print("\n" + "=" * 80)
    print("ALL RESULTS:")
    print("=" * 80)
    for r in results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL" if r["status"] == "FAIL" else "ERR "
        print(f"  {icon} [{r['method']:6s}] {r['path']:55s} HTTP {r['http_code']:3d}  {r['name']}")

if __name__ == "__main__":
    main()
