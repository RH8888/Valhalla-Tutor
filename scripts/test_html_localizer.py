import sys
sys.path.insert(0, ".")
import re
import json
from starlette.requests import Request
from app.core.templates import templates
from app.core.i18n import _load_translations, _TRANSLATIONS, to_persian_digits

_load_translations()
fa_dict = _TRANSLATIONS.get("fa", {})

print(f"Loaded {len(fa_dict)} Persian translations.")

def localize_html(html: str) -> str:
    # 1. Protect script and style tags
    preserved = []
    def preserve_tag(m):
        preserved.append(m.group(0))
        return f"___PROTECTED_{len(preserved)-1}___"
    
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', preserve_tag, html, flags=re.DOTALL | re.IGNORECASE)

    # 2. Localize attributes: placeholder, title, aria-label
    def replace_attr(m):
        attr_name = m.group(1)
        attr_val = m.group(2)
        trans = fa_dict.get(attr_val.strip())
        if trans:
            return f'{attr_name}="{trans}"'
        return m.group(0)

    html = re.sub(r'\b(placeholder|title|aria-label)="([^"]*)"', replace_attr, html)

    # 3. Localize confirm('...') dialogs
    def replace_confirm(m):
        quote = m.group(1)
        msg = m.group(2)
        trans = fa_dict.get(msg.strip())
        if trans:
            return f"confirm({quote}{trans}{quote})"
        return m.group(0)

    html = re.sub(r'confirm\((["\'])(.*?)\1\)', replace_confirm, html)

    # 4. Localize text nodes between > and <
    def replace_text_node(m):
        prefix = m.group(1) # '>'
        text = m.group(2)
        suffix = m.group(3) # '<'
        
        stripped = text.strip()
        if not stripped:
            return m.group(0)
            
        # Exact match in catalog
        if stripped in fa_dict:
            l_ws = text[:len(text) - len(text.lstrip())]
            r_ws = text[len(text.rstrip()):]
            return f"{prefix}{l_ws}{fa_dict[stripped]}{r_ws}{suffix}"
            
        return m.group(0)

    html = re.sub(r'(>)([^<]+)(<)', replace_text_node, html)

    # 5. Restore protected script and style tags
    for i, p in enumerate(preserved):
        html = html.replace(f"___PROTECTED_{i}___", p)

    return html

# Test on login page
headers = [(b"cookie", b"valhalla_locale=fa")]
scope = {"type": "http", "method": "GET", "path": "/login", "headers": headers}
req = Request(scope)
resp = templates.TemplateResponse(request=req, name="auth/login.html", context={"msg": None, "err": None})
raw_html = resp.body.decode("utf-8")
localized_html = localize_html(raw_html)

print("=== CHECKING AUTH LOGIN OUTPUT ===")
for test_phrase in ["Sign In", "Password", "Username or Email", "Academic Planner", "Remember me"]:
    in_raw = test_phrase in raw_html
    in_loc = test_phrase in localized_html
    print(f"'{test_phrase}': in raw = {in_raw}, in localized = {in_loc}")

for fa_phrase in ["ورود به حساب کاربری", "کلمه عبور", "نام کاربری یا ایمیل", "برنامه‌ریز تحصیلی هوشمند"]:
    print(f"'{fa_phrase}': in localized = {fa_phrase in localized_html}")
