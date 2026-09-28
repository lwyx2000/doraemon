import urllib.request, json
BASE = "http://10.100.213.248:8000"
def fetch(url, timeout=25):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"curl/8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8","replace")[:300]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
# 10Y treasury
st, body = fetch(BASE + "/api/ak?method=bond_china_yield&start_date=20260101&end_date=20260928", 30)
print(f"[bond_china_yield] status={st}")
try:
    j = json.loads(body)
    print("  code:", j.get("code"), "len:", len(j.get("data") or []))
    if j.get("data"):
        print("  sample:", j["data"][-1])
except Exception as e:
    print("  parse err", e, body[:200])
# index-valuation list (sanity)
st2, body2 = fetch(BASE + "/api/index-valuation/list", 15)
print(f"[index-valuation/list] status={st2}")
try:
    j2 = json.loads(body2)
    print("  code:", j2.get("code"), "count:", len(j2.get("data") or []))
except Exception as e:
    print("  err", e, body2[:200])
