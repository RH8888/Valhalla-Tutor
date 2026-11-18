import glob
import re
import json

router_messages = set()

for path in glob.glob('app/routers/**/*.py', recursive=True):
    content = open(path, encoding='utf-8').read()
    # Find ?msg=... or &msg=... or ?err=... or &err=...
    for m in re.finditer(r'[?&](?:msg|err)=([^"\'&\s]+)', content):
        import urllib.parse
        msg = urllib.parse.unquote_plus(m.group(1))
        router_messages.add(msg)
    # Also find HTTPException(detail="...")
    for m in re.finditer(r'HTTPException\([^)]*detail=["\'](.*?)["\']', content):
        router_messages.add(m.group(1))

print(f"Found {len(router_messages)} router messages / details:")
print(json.dumps(sorted(list(router_messages)), ensure_ascii=False, indent=2))
