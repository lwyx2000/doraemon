import requests
BASE = "http://localhost:8001/api/v1"

# Try register first
r = requests.post(f"{BASE}/auth/register", json={"username":"testbot","password":"Test1234!"})
print("Register:", r.status_code, r.text[:200])

# Login
r = requests.post(f"{BASE}/auth/login", json={"username":"testbot","password":"Test1234!"})
print("Login:", r.status_code)
token = ""
try:
    j = r.json()
    print("Login resp:", j)
    token = j.get("data",{}).get("token","")
except:
    pass

if not token:
    print("No token, abort")
    exit(1)

h = {"Authorization": f"Bearer {token}"}

# Test strategies
r2 = requests.get(f"{BASE}/strategies", headers=h, timeout=15)
print("Strategies:", r2.status_code)
if r2.status_code != 200:
    print("Body:", r2.text[:500])
else:
    print("Data:", r2.json())

# Test strategy create
r3 = requests.post(f"{BASE}/strategies", headers=h, json={
    "name": "test_auto",
    "target_asset": "cb",
    "rules": [{"field": "price", "operator": "<", "value": "130", "logic": "AND"}],
    "sort_by": "double_low_score",
    "sort_order": "asc",
    "limit_count": 5,
}, timeout=15)
print("Create:", r3.status_code)
if r3.status_code != 200:
    print("Body:", r3.text[:500])
else:
    print("Created:", r3.json())

# Test execute
r4 = requests.post(f"{BASE}/strategies/1/execute", headers=h, timeout=15)
print("Execute:", r4.status_code)
if r4.status_code != 200:
    print("Body:", r4.text[:500])
else:
    print("Result:", r4.json())
