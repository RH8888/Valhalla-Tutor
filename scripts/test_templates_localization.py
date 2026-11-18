import sys
sys.path.insert(0, ".")
import re
import json
from starlette.requests import Request
from app.core.templates import templates
from app.core.i18n import _load_translations, _TRANSLATIONS, to_persian_digits

_load_translations()
fa_dict = _TRANSLATIONS.get("fa", {})

_DYNAMIC_PATTERNS = [
    (re.compile(r'^Occurrence on (.+?) cancelled$', re.I), lambda m: f"نوبت مورخ {m.group(1)} لغو شد"),
    (re.compile(r'^Occurrence on (.+?) marked as No Exam \(skipped\)$', re.I), lambda m: f"نوبت مورخ {m.group(1)} به عنوان بدون آزمون ثبت شد"),
    (re.compile(r'^Occurrence on (.+?) restored to Scheduled$', re.I), lambda m: f"نوبت مورخ {m.group(1)} به وضعیت زمان‌بندی‌شده بازگردانده شد"),
    (re.compile(r'^Manual occurrence on (.+?) added$', re.I), lambda m: f"نوبت دستی مورخ {m.group(1)} اضافه شد"),
    (re.compile(r'^Academic grade updated to Grade (.+)$', re.I), lambda m: f"پایه تحصیلی به پایه {m.group(1)} بروزرسانی شد"),
    (re.compile(r'^Generated (\d+) scheduled occurrence\(s\)$', re.I), lambda m: f"{to_persian_digits(m.group(1))} نوبت آزمون با موفقیت تولید شد"),
    (re.compile(r'^Schedule extended: (\d+) new occurrences generated$', re.I), lambda m: f"زمان‌بندی تمدید شد: {to_persian_digits(m.group(1))} نوبت جدید تولید گردید"),
    (re.compile(r'^Assigned exam to (\d+) student\(s\)$', re.I), lambda m: f"آزمون به {to_persian_digits(m.group(1))} دانش‌آموز تخصیص یافت"),
    (re.compile(r'^Configured answer keys and scoring for (\d+) questions$', re.I), lambda m: f"کلید پاسخ و بارم‌بندی برای {to_persian_digits(m.group(1))} سوال تنظیم شد"),
    (re.compile(r'^Account successfully (activated|deactivated)$', re.I), lambda m: f"حساب کاربری با موفقیت {'فعال' if m.group(1).lower() == 'activated' else 'غیرفعال'} شد"),
    (re.compile(r"^PDF booklet '(.+?)' uploaded successfully$", re.I), lambda m: f"دفترچه PDF '{m.group(1)}' با موفقیت بارگذاری شد"),
    (re.compile(r"^Reporting group '(.+?)' created$", re.I), lambda m: f"گروه گزارش '{m.group(1)}' ایجاد شد"),
    (re.compile(r"^Subject '(.+?)' created successfully$", re.I), lambda m: f"درس '{m.group(1)}' با موفقیت ایجاد شد"),
    (re.compile(r"^Removed (\d+) student\(s\)$", re.I), lambda m: f"{to_persian_digits(m.group(1))} دانش‌آموز حذف شدند"),
    (re.compile(r"^Series assigned to (\d+) student\(s\)$", re.I), lambda m: f"مجموعه آزمون به {to_persian_digits(m.group(1))} دانش‌آموز تخصیص یافت"),
]

def localize_text(text: str) -> str:
    if not text:
        return ""
    stripped = text.strip()
    if not stripped:
        return text
    if stripped in fa_dict:
        l_ws = text[:len(text) - len(text.lstrip())]
        r_ws = text[len(text.rstrip()):]
        return f"{l_ws}{fa_dict[stripped]}{r_ws}"
    for pat, fn in _DYNAMIC_PATTERNS:
        m = pat.match(stripped)
        if m:
            l_ws = text[:len(text) - len(text.lstrip())]
            r_ws = text[len(text.rstrip()):]
            return f"{l_ws}{fn(m)}{r_ws}"
    return text

def localize_html_full(html: str) -> str:
    # 1. Protect script and style tags
    preserved = []
    def preserve_tag(m):
        preserved.append(m.group(0))
        return f"___VALHALLA_PROTECTED_{len(preserved)-1}___"
    
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
        prefix = m.group(1)
        text = m.group(2)
        suffix = m.group(3)
        return f"{prefix}{localize_text(text)}{suffix}"

    html = re.sub(r'(>)([^<]+)(<)', replace_text_node, html)

    # 5. Restore protected script and style tags
    for i, p in enumerate(preserved):
        html = html.replace(f"___VALHALLA_PROTECTED_{i}___", p)

    return html

# Test on a dummy request
scope = {
    "type": "http",
    "method": "GET",
    "path": "/login",
    "headers": [(b"cookie", b"valhalla_locale=fa")]
}
req = Request(scope)
resp = templates.TemplateResponse(request=req, name="auth/login.html", context={"msg": "Exam results updated successfully", "error": None})
raw_html = resp.body.decode("utf-8")
loc_html = localize_html_full(raw_html)

print("Check flash message localization:")
print("In raw:", "نتایج آزمون با موفقیت بروزرسانی شد" in raw_html)
print("In localized:", "نتایج آزمون با موفقیت بروزرسانی شد" in loc_html)
