"""测试 valuation_service"""
import sys
sys.path.insert(0, '.')

from services.valuation_service import get_broad_index_valuation

data, meta = get_broad_index_valuation()
print(f"indices: {len(data)}")
print(f"meta: {meta}")
print()
for d in data:
    print(f"{d['name']:8s}: PB={d['pb']}, PE={d['pe_ttm']}, ROE={d['roe_mean']}%, "
          f"spread={d['spread']}%, val_pct={d['valuation_percentile']}, "
          f"crowding={d['crowding']}")
