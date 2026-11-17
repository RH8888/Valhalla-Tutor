import json
import os
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


def translate(key: str, locale: str = DEFAULT_LOCALE, **kwargs: Any) -> str:
    if not key:
        return ""
    if not _TRANSLATIONS:
        _load_translations()

    loc_dict = _TRANSLATIONS.get(locale, {})
    default_dict = _TRANSLATIONS.get(DEFAULT_LOCALE, {})

    text = loc_dict.get(key)
    if text is None:
        text = default_dict.get(key, key)

    if kwargs and text:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


_PERSIAN_DIGITS_MAP = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_persian_digits(val: Union[int, float, str]) -> str:
    if val is None:
        return ""
    return str(val).translate(_PERSIAN_DIGITS_MAP)


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
