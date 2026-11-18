import glob
import re
import json

patterns = set()

for path in glob.glob('app/routers/**/*.py', recursive=True):
    content = open(path, encoding='utf-8').read()
    # Find redirect url strings or msg=...
    for m in re.finditer(r'["\'][^"\']*[?&]msg=([^"\'\n]+)["\']', content):
        patterns.add(m.group(0))
    for m in re.finditer(r'["\'][^"\']*[?&]err=([^"\'\n]+)["\']', content):
        patterns.add(m.group(0))

print("Found URL patterns:", json.dumps(sorted(list(patterns)), ensure_ascii=False, indent=2))
