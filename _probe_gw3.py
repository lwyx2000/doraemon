import urllib.request, json

def fetch(url, timeout=25):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

BASE = "http://10.100.213.248:8000"

def probe(method, params=None, label=""):
    q = f"?method={method}"
    if params:
        for k, v in params.items():
            q += f"&{k}={v}"
    st, body = fetch(BASE + "/api/ak" + q, 25)
    print(f"\n=== {label or method} -> status {st} ===")
    if st == 200:
        try:
            j = json.loads(body)
            if isinstance(j, dict) and "data" in j:
                d = j["data"]
                print("data type:", type(d).__name__, "len:", len(d) if hasattr(d, "__len__") else "n/a")
                if isinstance(d, list) and d:
                    print("nrows:", len(d))
                    print("cols:", list(d[0].keys()) if isinstance(d[0], dict) else d[0])
                    print("row0:", json.dumps(d[0], ensure_ascii=False)[:600])
            else:
                print("keys:", list(j.keys()) if isinstance(j, dict) else type(j))
                print(body[:300])
        except Exception as e:
            print("parse err:", e, body[:300])
    else:
        print(body[:300])

probe("sw_index_first_info", label="申万一级行业PE/PB(当日)")
probe("index_realtime_sw", {"symbol": "一级行业"}, label="申万一级行业实时行情")
probe("index_hist_sw", {"symbol": "801010", "period": "day"}, label="申万行业历史日线(801010)")
probe("index_analysis_daily_sw", {"symbol": "一级行业", "start_date": "20260901", "end_date": "20260928"}, label="行业PE/PB历史(死上游验证)")
