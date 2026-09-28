import urllib.request, json

def fetch(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"curl/8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

for base in ["http://192.168.3.53:8000", "http://10.100.213.248:8000"]:
    print("==== BASE:", base, "====")
    st, body = fetch(base + "/api/project/info", 8)
    print("project/info:", st, (body[:500] if isinstance(body, str) else body))
