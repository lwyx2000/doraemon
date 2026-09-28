import urllib.request, json

BASE = "http://10.100.213.248:8000"

def fetch(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"curl/8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8","replace")[:500]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

# 1) enumerate routes via openapi
st, body = fetch(BASE + "/openapi.json", 10)
print("OPENAPI status:", st)
if st == 200:
    try:
        spec = json.loads(body)
        paths = sorted(spec.get("paths", {}).keys())
        print("PATH COUNT:", len(paths))
        for p in paths:
            if any(k in p for k in ["project","index-val","index_val","ak","sw","sector","industry","valuation"]):
                print("  ", p, list(spec["paths"][p].keys()))
    except Exception as e:
        print("parse err", e)
else:
    print("body:", body[:300])

print("---- direct probes ----")
probes = [
    "/api/project/info",
    "/api/index-valuation/000985/history",
    "/api/ak?method=macro_china_cpi",
    "/api/ak?method=index_analysis_daily_sw&symbol=%E4%B8%80%E7%BA%A7%E8%A1%8C%E4%B8%9A&start_date=20260901&end_date=20260928",
]
for p in probes:
    st, body = fetch(BASE + p, 25)
    print(f"[{st}] {p}\n   {body[:400]}")
