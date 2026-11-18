import sys
sys.path.insert(0, ".")
import json
from scripts.extract_placeholders_and_titles import placeholders, titles, confirms

with open("app/locales/fa.json", "r", encoding="utf-8") as f:
    fa = json.load(f)

missing_p = [p for p in placeholders if p not in fa]
missing_t = [t for t in titles if t not in fa]
missing_c = [c for c in confirms if c not in fa]

print(f"Missing placeholders ({len(missing_p)}):")
print(json.dumps(missing_p, ensure_ascii=False, indent=2))

print(f"\nMissing titles ({len(missing_t)}):")
print(json.dumps(missing_t, ensure_ascii=False, indent=2))

print(f"\nMissing confirms ({len(missing_c)}):")
print(json.dumps(missing_c, ensure_ascii=False, indent=2))
