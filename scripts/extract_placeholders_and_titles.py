import glob
import re
import json

placeholders = set()
titles = set()
aria_labels = set()
confirms = set()

for path in glob.glob('app/templates/**/*.html', recursive=True):
    content = open(path, encoding='utf-8').read()
    for m in re.finditer(r'placeholder=["\'](.*?)["\']', content):
        p = m.group(1).strip()
        if p and not p.startswith('{{'):
            placeholders.add(p)
    for m in re.finditer(r'title=["\'](.*?)["\']', content):
        t = m.group(1).strip()
        if t and not t.startswith('{{'):
            titles.add(t)
    for m in re.finditer(r'aria-label=["\'](.*?)["\']', content):
        a = m.group(1).strip()
        if a and not a.startswith('{{'):
            aria_labels.add(a)
    for m in re.finditer(r'confirm\(["\'](.*?)["\']\)', content):
        c = m.group(1).strip()
        if c and not c.startswith('{{'):
            confirms.add(c)

print(f"Unique placeholders: {len(placeholders)}")
print("Placeholders:", json.dumps(list(placeholders), ensure_ascii=False, indent=2))

print(f"\nUnique titles: {len(titles)}")
print("Titles:", json.dumps(list(titles), ensure_ascii=False, indent=2))

print(f"\nUnique confirms: {len(confirms)}")
print("Confirms:", json.dumps(list(confirms), ensure_ascii=False, indent=2))
