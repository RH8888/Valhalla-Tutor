import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union
from jinja2 import pass_context

LOCALE_COOKIE_NAME = "valhalla_locale"
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "fa")

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
_TRANSLATIONS: Dict[str, Dict[str, str]] = {}


def _load_translations() -> None:
    for lang in SUPPORTED_LOCALES:
        file_path = _LOCALES_DIR / f"{lang}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    _TRANSLATIONS[lang] = json.load(f)
            except Exception:
                _TRANSLATIONS[lang] = {}
        else:
            _TRANSLATIONS[lang] = {}


_load_translations()


def get_translations(locale: str = DEFAULT_LOCALE) -> Dict[str, str]:
    if not _TRANSLATIONS:
        _load_translations()
    return _TRANSLATIONS.get(locale, _TRANSLATIONS.get(DEFAULT_LOCALE, {}))


def get_locale_from_request(request: Optional[Any]) -> str:
    if request:
        cookies = getattr(request, "cookies", None)
        if cookies and hasattr(cookies, "get"):
            loc = cookies.get(LOCALE_COOKIE_NAME)
            if loc in SUPPORTED_LOCALES:
                return loc
    return DEFAULT_LOCALE




_PERSIAN_DIGITS_MAP = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_persian_digits(val: Union[int, float, str]) -> str:
    if val is None:
        return ""
    return str(val).translate(_PERSIAN_DIGITS_MAP)


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


def translate(key: str, locale: str = DEFAULT_LOCALE, **kwargs: Any) -> str:
    if not key:
        return ""
    if not _TRANSLATIONS:
        _load_translations()

    loc_dict = _TRANSLATIONS.get(locale, {})
    default_dict = _TRANSLATIONS.get(DEFAULT_LOCALE, {})

    text = loc_dict.get(key)
    if text is None:
        stripped = key.strip()
        text = loc_dict.get(stripped)

    if text is None and locale == "fa":
        for pat, fn in _DYNAMIC_PATTERNS:
            m = pat.match(key.strip())
            if m:
                text = fn(m)
                break

    if text is None:
        text = default_dict.get(key, default_dict.get(key.strip(), key))

    if kwargs and text:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text




def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Converts Gregorian date (gy, gm, gd) to Jalali (jy, jm, jd) using Borkowski's formula."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


_JALALI_MONTH_NAMES = [
    "",
    "فروردین", "اردیبهشت", "خرداد",
    "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر",
    "دی", "بهمن", "اسفند"
]


def format_jalali(dt: Union[date, datetime], show_month_name: bool = True) -> str:
    if not dt:
        return ""
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    if show_month_name and 1 <= jm <= 12:
        return f"{to_persian_digits(jd)} {_JALALI_MONTH_NAMES[jm]} {to_persian_digits(jy)}"
    return f"{to_persian_digits(jy)}/{to_persian_digits(f'{jm:02d}')}/{to_persian_digits(f'{jd:02d}')}"


# Jinja2 Context-Aware Helpers
@pass_context
def jinja_get_locale(context: Any) -> str:
    request = context.get("request")
    if request:
        loc = request.cookies.get(LOCALE_COOKIE_NAME)
        if loc in SUPPORTED_LOCALES:
            return loc
    return DEFAULT_LOCALE


@pass_context
def jinja_is_rtl(context: Any) -> bool:
    return jinja_get_locale(context) == "fa"


@pass_context
def jinja_translate(context: Any, key: str, **kwargs: Any) -> str:
    locale = jinja_get_locale(context)
    return translate(key, locale=locale, **kwargs)


@pass_context
def jinja_persian_digits(context: Any, val: Any) -> str:
    locale = jinja_get_locale(context)
    if locale == "fa":
        return to_persian_digits(val)
    return str(val) if val is not None else ""


@pass_context
def jinja_date_format(context: Any, dt: Union[date, datetime], show_month_name: bool = True) -> str:
    locale = jinja_get_locale(context)
    if not dt:
        return ""
    if locale == "fa":
        return format_jalali(dt, show_month_name=show_month_name)
    if isinstance(dt, datetime):
        return dt.strftime("%b %d, %Y")
    return dt.strftime("%b %d, %Y")


def localize_html_content(html: str, locale: str = DEFAULT_LOCALE) -> str:
    if locale != "fa" or not html:
        return html

    if not _TRANSLATIONS:
        _load_translations()
    fa_dict = _TRANSLATIONS.get("fa", {})

    # 1. Protect script and style tags
    preserved = []
    def preserve_tag(m: re.Match) -> str:
        preserved.append(m.group(0))
        return f"___VALHALLA_PROTECTED_{len(preserved)-1}___"

    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', preserve_tag, html, flags=re.DOTALL | re.IGNORECASE)

    # 2. Localize attributes: placeholder, title, aria-label
    def replace_attr(m: re.Match) -> str:
        attr_name = m.group(1)
        attr_val = m.group(2)
        trans = fa_dict.get(attr_val.strip())
        if trans:
            return f'{attr_name}="{trans}"'
        return m.group(0)

    html = re.sub(r'\b(placeholder|title|aria-label)="([^"]*)"', replace_attr, html)

    # 3. Localize confirm('...') dialogs
    def replace_confirm(m: re.Match) -> str:
        quote = m.group(1)
        msg = m.group(2)
        trans = fa_dict.get(msg.strip())
        if trans:
            return f"confirm({quote}{trans}{quote})"
        return m.group(0)

    html = re.sub(r'confirm\((["\'])(.*?)\1\)', replace_confirm, html)

    # 4. Localize text nodes between > and <
    def replace_text_node(m: re.Match) -> str:
        prefix = m.group(1)
        text = m.group(2)
        suffix = m.group(3)
        stripped = text.strip()
        if not stripped:
            return m.group(0)

        # Technical strings to preserve verbatim
        if '@' in stripped or 'http://' in stripped or 'https://' in stripped:
            return m.group(0)

        # Check catalog
        trans = fa_dict.get(stripped)
        if trans is None:
            # Check dynamic patterns
            for pat, fn in _DYNAMIC_PATTERNS:
                pm = pat.match(stripped)
                if pm:
                    trans = fn(pm)
                    break

        if trans is not None:
            l_ws = text[:len(text) - len(text.lstrip())]
            r_ws = text[len(text.rstrip()):]
            if re.search(r'[\u0600-\u06FF]', trans) or re.match(r'^[\s\d%—–\-\./\(\):•]+$', trans):
                trans = to_persian_digits(trans)
            return f"{prefix}{l_ws}{trans}{r_ws}{suffix}"

        # If already Persian text with ASCII digits, convert to Persian digits
        if re.search(r'[\u0600-\u06FF]', text) and re.search(r'\d', text):
            text = to_persian_digits(text)
            return f"{prefix}{text}{suffix}"

        return m.group(0)

    html = re.sub(r'(>)([^<]+)(<)', replace_text_node, html)

    # 5. Restore protected script and style tags
    for i, p in enumerate(preserved):
        html = html.replace(f"___VALHALLA_PROTECTED_{i}___", p)

    return html
