#!/bin/bash
B="http://127.0.0.1:8004/api/v1"
EPS=(
  "market/overview"
  "market/board-sectors"
  "market/fund-flows"
  "market/zt-stats"
  "market/fund-ranking"
  "market/indices"
  "market/macro/indicators"
  "etf/etfs"
  "etf/etfs/arbitrage"
  "cb/convertible-bonds"
  "reits/reits"
  "funds"
  "funds/closed/analysis"
  "market/monitor/dashboard"
  "ai/reports"
  "ai/config"
  "strategies"
  "alerts/rules"
  "favorites"
  "portfolios"
)
for ep in "${EPS[@]}"; do
  out=$(curl -s -m 150 "$B/$ep")
  echo "================ /$ep ================="
  echo "$out" | python3 -c "
import sys,json
raw=sys.stdin.read()
try:
    d=json.loads(raw)
    code=d.get('code'); msg=d.get('message'); meta=d.get('meta') or {}
    data=d.get('data'); im=meta.get('isMock')
    if isinstance(data,list):
        sz=len(data); head=str(data[0])[:120] if sz else ''
    elif isinstance(data,dict):
        sz='dict:'+str(list(data.keys())[:8]); head=str(list(data.keys())[:4])
    elif data is None:
        sz='None'; head=''
    else:
        sz=type(data).__name__; head=str(data)[:120]
    print(f'  code={code} | msg={msg} | isMock={im} | data={sz}')
    if head: print('  sample:', head)
except Exception as e:
    print('  [parse fail]', str(e)[:120], '| raw:', raw[:160])
"
done
