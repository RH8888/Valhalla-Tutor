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
        state = getattr(request, "state", None)
        if state is not None:
            state_loc = getattr(state, "locale", None)
            if state_loc in SUPPORTED_LOCALES:
                return state_loc
        cookies = getattr(request, "cookies", None)
        if cookies and hasattr(cookies, "get"):
            loc = cookies.get(LOCALE_COOKIE_NAME)
            if loc in SUPPORTED_LOCALES:
                return loc
    return DEFAULT_LOCALE




_PERSIAN_DIGITS_MAP = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_ASCII_DIGITS_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def to_persian_digits(val: Union[int, float, str, None]) -> str:
    if val is None:
        return ""
    return str(val).translate(_PERSIAN_DIGITS_MAP)


def to_ascii_digits(val: Union[int, float, str, None]) -> str:
    if val is None:
        return ""
    return str(val).translate(_ASCII_DIGITS_MAP)


_ROLE_LABELS = {
    "fa": {
        "TUTOR": "مدرس",
        "STUDENT": "دانش‌آموز",
    },
    "en": {
        "TUTOR": "Tutor",
        "STUDENT": "Student",
    },
}

_STATUS_LABELS = {
    "fa": {
        "SCHEDULED": "زمان‌بندی‌شده",
        "COMPLETED": "تکمیل‌شده",
        "CANCELLED": "لغو شده",
        "STUDENT_ABSENT": "غیبت دانش‌آموز",
        "ONLINE": "آنلاین",
        "OFFLINE": "حضوری",
        "DRAFT": "پیش‌نویس",
        "PUBLISHED": "منتشرشده",
        "ARCHIVED": "بایگانی‌شده",
        "PENDING": "در انتظار",
        "ACCEPTED": "پذیرفته‌شده",
        "REJECTED": "رد شده",
        "APPROVED": "تأییدشده",
        "DISMISSED": "رد شده",
        "OPEN": "باز",
        "CLOSED": "بسته",
        "GRADED": "تصحیح‌شده",
        "SUBMITTED": "ثبت‌شده",
        "IN_PROGRESS": "در حال انجام",
        "ABSENT": "غایب",
        "NO_EXAM": "بدون آزمون",
        "ACTIVE": "فعال",
        "INACTIVE": "غیرفعال",
    },
    "en": {
        "SCHEDULED": "Scheduled",
        "COMPLETED": "Completed",
        "CANCELLED": "Cancelled",
        "STUDENT_ABSENT": "Student Absent",
        "ONLINE": "Online",
        "OFFLINE": "Offline",
        "DRAFT": "Draft",
        "PUBLISHED": "Published",
        "ARCHIVED": "Archived",
        "PENDING": "Pending",
        "ACCEPTED": "Accepted",
        "REJECTED": "Rejected",
        "APPROVED": "Approved",
        "DISMISSED": "Dismissed",
        "OPEN": "Open",
        "CLOSED": "Closed",
        "GRADED": "Graded",
        "SUBMITTED": "Submitted",
        "IN_PROGRESS": "In Progress",
        "ABSENT": "Absent",
        "NO_EXAM": "No Exam",
        "ACTIVE": "Active",
        "INACTIVE": "Inactive",
    },
}

_WEEKDAY_FA = {
    "monday": "دوشنبه",
    "mon": "دوشنبه",
    "tuesday": "سه‌شنبه",
    "tue": "سه‌شنبه",
    "wednesday": "چهارشنبه",
    "wed": "چهارشنبه",
    "thursday": "پنج‌شنبه",
    "thu": "پنج‌شنبه",
    "friday": "جمعه",
    "fri": "جمعه",
    "saturday": "شنبه",
    "sat": "شنبه",
    "sunday": "یکشنبه",
    "sun": "یکشنبه",
}

_PYTHON_WEEKDAY_TO_FA = [
    "دوشنبه",   # 0 = Monday
    "سه‌شنبه",  # 1 = Tuesday
    "چهارشنبه", # 2 = Wednesday
    "پنج‌شنبه", # 3 = Thursday
    "جمعه",     # 4 = Friday
    "شنبه",     # 5 = Saturday
    "یکشنبه",   # 6 = Sunday
]

_PYTHON_WEEKDAY_TO_EN = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def translate_role(role: Optional[str], locale: str = DEFAULT_LOCALE) -> str:
    if not role:
        return ""
    key = str(role).split(".")[-1].upper()
    return _ROLE_LABELS.get(locale, _ROLE_LABELS["en"]).get(key, key)


def translate_status(status_val: Optional[str], locale: str = DEFAULT_LOCALE) -> str:
    if not status_val:
        return ""
    key = str(status_val).split(".")[-1].upper()
    return _STATUS_LABELS.get(locale, _STATUS_LABELS["en"]).get(key, key.replace("_", " ").title())


def translate_weekday(day: Union[str, int, date, datetime, None], locale: str = DEFAULT_LOCALE) -> str:
    if day is None:
        return ""
    if isinstance(day, (date, datetime)):
        idx = day.weekday()
        return _PYTHON_WEEKDAY_TO_FA[idx] if locale == "fa" else _PYTHON_WEEKDAY_TO_EN[idx]
    if isinstance(day, int) and 0 <= day <= 6:
        return _PYTHON_WEEKDAY_TO_FA[day] if locale == "fa" else _PYTHON_WEEKDAY_TO_EN[day]
    s = str(day).strip()
    if locale == "fa":
        return _WEEKDAY_FA.get(s.lower(), s)
    return s


def format_persian_number(val: Union[int, float, str, None], decimals: Optional[int] = None, grouping: bool = True) -> str:
    if val is None or val == "":
        return ""
    try:
        num = float(val)
        if decimals is not None:
            formatted = f"{num:,.{decimals}f}" if grouping else f"{num:.{decimals}f}"
        elif isinstance(val, int) or num.is_integer():
            formatted = f"{int(round(num)):,}" if grouping else f"{int(round(num))}"
        else:
            formatted = f"{num:,.2f}".rstrip("0").rstrip(".") if grouping else f"{num:.2f}".rstrip("0").rstrip(".")
        formatted = formatted.replace(",", "٬").replace(".", "٫")
        return to_persian_digits(formatted)
    except Exception:
        return to_persian_digits(str(val))


def format_persian_percent(val: Union[int, float, str, None], decimals: Optional[int] = None) -> str:
    if val is None or val == "":
        return ""
    num_str = format_persian_number(val, decimals=decimals, grouping=False)
    return f"{num_str}٪"


def format_persian_duration(minutes: Union[int, float, str, None], locale: str = "fa") -> str:
    if minutes is None or minutes == "":
        return ""
    try:
        total = int(round(float(minutes)))
    except Exception:
        return str(minutes)
    hrs, mins = divmod(max(total, 0), 60)
    if locale != "fa":
        if hrs and mins:
            return f"{hrs}h {mins}m"
        if hrs:
            return f"{hrs}h"
        return f"{mins}m"
    if hrs and mins:
        return f"{to_persian_digits(hrs)} ساعت و {to_persian_digits(mins)} دقیقه"
    if hrs:
        return f"{to_persian_digits(hrs)} ساعت"
    return f"{to_persian_digits(mins)} دقیقه"


def format_persian_currency(amount: Union[int, float, str, None], unit: str = "تومان") -> str:
    if amount is None or amount == "":
        return ""
    return f"{format_persian_number(amount)} {unit}"


_DYNAMIC_PATTERNS = [
    (re.compile(r'^Too many failed login attempts\. Please try again in (\d+) seconds\.$', re.I), lambda m: f"تلاش‌های ناموفق بیش از حد مجاز بوده است. لطفاً پس از {to_persian_digits(m.group(1))} ثانیه دوباره تلاش کنید."),
    (re.compile(r'^Occurrence on (.+?) cancelled$', re.I), lambda m: f"نوبت مورخ {m.group(1)} لغو شد"),
    (re.compile(r'^Occurrence on (.+?) marked as No Exam \(skipped\)$', re.I), lambda m: f"نوبت مورخ {m.group(1)} به عنوان بدون آزمون ثبت شد"),
    (re.compile(r'^Occurrence on (.+?) restored to Scheduled$', re.I), lambda m: f"نوبت مورخ {m.group(1)} به وضعیت زمان‌بندی‌شده بازگردانده شد"),
    (re.compile(r'^Manual occurrence on (.+?) added$', re.I), lambda m: f"نوبت دستی مورخ {m.group(1)} اضافه شد"),
    (re.compile(r'^Academic grade updated to Grade (.+)$', re.I), lambda m: f"پایه تحصیلی به پایه {to_persian_digits(m.group(1))} بروزرسانی شد"),
    (re.compile(r'^Generated (\d+) scheduled occurrence\(s\)$', re.I), lambda m: f"{to_persian_digits(m.group(1))} نوبت آزمون با موفقیت تولید شد"),
    (re.compile(r'^Schedule extended: (\d+) new occurrences generated$', re.I), lambda m: f"زمان‌بندی تمدید شد: {to_persian_digits(m.group(1))} نوبت جدید تولید گردید"),
    (re.compile(r'^Assigned exam to (\d+) student\(s\)$', re.I), lambda m: f"آزمون به {to_persian_digits(m.group(1))} دانش‌آموز تخصیص یافت"),
    (re.compile(r'^Configured answer keys and scoring for (\d+) questions$', re.I), lambda m: f"کلید پاسخ و بارم‌بندی برای {to_persian_digits(m.group(1))} سوال تنظیم شد"),
    (re.compile(r'^Account successfully (activated|deactivated)$', re.I), lambda m: f"حساب کاربری با موفقیت {'فعال' if m.group(1).lower() == 'activated' else 'غیرفعال'} شد"),
    (re.compile(r"^PDF booklet '(.+?)' uploaded successfully$", re.I), lambda m: f"دفترچه PDF «{m.group(1)}» با موفقیت بارگذاری شد"),
    (re.compile(r"^Reporting group '(.+?)' created$", re.I), lambda m: f"گروه گزارش «{m.group(1)}» ایجاد شد"),
    (re.compile(r"^Subject '(.+?)' created successfully$", re.I), lambda m: f"درس «{m.group(1)}» با موفقیت ایجاد شد"),
    (re.compile(r"^Subject '(.+?)' updated successfully$", re.I), lambda m: f"درس «{m.group(1)}» با موفقیت بروزرسانی شد"),
    (re.compile(r"^Subject '(.+?)' already exists\.$", re.I), lambda m: f"درس «{m.group(1)}» از قبل وجود دارد."),
    (re.compile(r"^Academic track '(.+?)' already exists\.$", re.I), lambda m: f"رشته تحصیلی «{m.group(1)}» از قبل وجود دارد."),
    (re.compile(r"^Cannot delete track '(.+?)'.*$", re.I), lambda m: f"امکان حذف رشته «{m.group(1)}» وجود ندارد زیرا به دانش‌آموزان یا آزمون‌ها متصل است."),
    (re.compile(r"^Username '(.+?)' is already taken\.$", re.I), lambda m: f"نام کاربری «{m.group(1)}» قبلاً انتخاب شده است."),
    (re.compile(r"^Email '(.+?)' is already in use\.$", re.I), lambda m: f"ایمیل «{m.group(1)}» قبلاً استفاده شده است."),
    (re.compile(r"^Invalid grade '(.+?)'.*$", re.I), lambda m: f"پایه تحصیلی «{m.group(1)}» نامعتبر است. پایه‌های مجاز: ۱۰، ۱۱، ۱۲."),
    (re.compile(r"^Removed (\d+) student\(s\)(?: from future occurrences \((\d+) assignments cancelled\)\. Past results strictly preserved\.)?$", re.I), lambda m: f"{to_persian_digits(m.group(1))} دانش‌آموز از نوبت‌های آتی حذف شدند" + (f" ({to_persian_digits(m.group(2))} تکلیف لغو شد). سوابق قبلی کاملاً حفظ شده‌اند." if m.group(2) else "")),
    (re.compile(r"^Series assigned to (\d+) student\(s\)(?: successfully)?$", re.I), lambda m: f"مجموعه آزمون با موفقیت به {to_persian_digits(m.group(1))} دانش‌آموز تخصیص یافت"),
    (re.compile(r"^Meeting overlaps with an existing meeting scheduled from (.+)$", re.I), lambda m: f"این زمان با جلسه دیگری در بازه {to_persian_digits(m.group(1))} تداخل دارد."),
    (re.compile(r"^Rescheduled slot overlaps with an existing meeting scheduled from (.+)$", re.I), lambda m: f"زمان جدید با جلسه دیگری در بازه {to_persian_digits(m.group(1))} تداخل دارد."),
    (re.compile(r"^Cannot publish a study plan with status '(.+?)'\. Only DRAFT plans can be published\.$", re.I), lambda m: f"برنامه مطالعاتی با وضعیت «{translate_status(m.group(1), 'fa')}» قابل انتشار نیست. تنها برنامه‌های پیش‌نویس قابل انتشار هستند."),
    (re.compile(r"^Scheduled date (.+?) falls outside the plan date range.*$", re.I), lambda m: f"تاریخ انتخاب‌شده ({to_persian_digits(m.group(1))}) خارج از بازه زمانی برنامه مطالعاتی است."),
    (re.compile(r"^Ending test number \((\d+)\) exceeds available tests \((\d+)\) in chapter '(.+?)'\.$", re.I), lambda m: f"شماره تست پایان ({to_persian_digits(m.group(1))}) از تعداد تست‌های موجود ({to_persian_digits(m.group(2))}) در فصل «{m.group(3)}» بیشتر است."),
    (re.compile(r"^Question (.+?) has a subject selected, but no answer key \(1, 2, 3, or 4\) was selected\.$", re.I), lambda m: f"برای سوال {to_persian_digits(m.group(1))} درس انتخاب شده اما کلید پاسخ (۱ تا ۴) مشخص نشده است."),
    (re.compile(r"^Question (.+?) has an answer key selected, but no subject was chosen\.$", re.I), lambda m: f"برای سوال {to_persian_digits(m.group(1))} کلید پاسخ انتخاب شده اما درس مشخص نشده است."),
    (re.compile(r"^Question range (\d+)[–-](\d+) overlaps with booklet '(.+?)'\.$", re.I), lambda m: f"بازه سوالات {to_persian_digits(m.group(1))} تا {to_persian_digits(m.group(2))} با دفترچه «{m.group(3)}» هم‌پوشانی دارد."),
    (re.compile(r"^Duplicate question number (\d+) in exam configuration\.$", re.I), lambda m: f"شماره سوال {to_persian_digits(m.group(1))} در تنظیمات آزمون تکراری است."),
    (re.compile(r"^Question (\d+) correct choice must be 1, 2, 3, or 4\.$", re.I), lambda m: f"گزینه صحیح سوال {to_persian_digits(m.group(1))} باید ۱، ۲، ۳ یا ۴ باشد."),
    (re.compile(r"^Question (\d+) belongs to another booklet and cannot be modified\.$", re.I), lambda m: f"سوال {to_persian_digits(m.group(1))} متعلق به دفترچه دیگری است و قابل تغییر نیست."),
    (re.compile(r"^Question (\d+) does not exist in this practice exam\.$", re.I), lambda m: f"سوال {to_persian_digits(m.group(1))} در این آزمون وجود ندارد."),
    (re.compile(r"^Question (\d+) is outside the question range for this booklet \((.+?)\)\.$", re.I), lambda m: f"سوال {to_persian_digits(m.group(1))} خارج از بازه سوالات این دفترچه ({to_persian_digits(m.group(2))}) است."),
    (re.compile(r"^Cannot schedule (.+?) on ([A-Za-z]+) \((.+?)\).*$", re.I), lambda m: f"امکان زمان‌بندی برای {m.group(1)} در روز {translate_weekday(m.group(2), 'fa')} ({to_persian_digits(m.group(3))}) وجود ندارد."),
    (re.compile(r"^No available (\d+)-minute slot on ([A-Za-z]+) \((.+?)\).*$", re.I), lambda m: f"بازه آزاد {to_persian_digits(m.group(1))} دقیقه‌ای در روز {translate_weekday(m.group(2), 'fa')} ({to_persian_digits(m.group(3))}) یافت نشد."),
    (re.compile(r"^Cannot assign series to incompatible students: (.+)$", re.I), lambda m: f"امکان تخصیص مجموعه آزمون به دانش‌آموزان ناسازگار وجود ندارد: {m.group(1)}"),
    (re.compile(r"^(?:Student|Plan|Exam|Exam series|Exam session|Session|Result|Book|Course|Subject|Academic track|Practice exam|Assignment|Course chapter|Book chapter) (?:with id )?(.+?) not found\.?$", re.I), lambda m: "مورد درخواستی یافت نشد."),
    (re.compile(r"^Subject with id (.+?) does not exist\.$", re.I), lambda m: "درس انتخاب‌شده وجود ندارد."),
    (re.compile(r"^Percentage for subject '(.+?)' .*", re.I), lambda m: f"درصد درس «{m.group(1)}» باید عدد معتبری بین ۰ تا ۱۰۰ باشد."),
    (re.compile(r"^Grade '(.+?)' .*", re.I), lambda m: f"پایه تحصیلی «{m.group(1)}» با تنظیمات درس مطابقت ندارد."),
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


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Converts Jalali date (jy, jm, jd) to Gregorian (gy, gm, gd)."""
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    sal_a = [0, 31, 29 if ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd


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


def format_jalali_short(dt: Union[date, datetime]) -> str:
    if not dt:
        return ""
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    if 1 <= jm <= 12:
        return f"{to_persian_digits(jd)} {_JALALI_MONTH_NAMES[jm]}"
    return format_jalali(dt, show_month_name=False)


def format_jalali_month_year(dt: Union[date, datetime]) -> str:
    if not dt:
        return ""
    jy, jm, _ = gregorian_to_jalali(dt.year, dt.month, dt.day)
    if 1 <= jm <= 12:
        return f"{_JALALI_MONTH_NAMES[jm]} {to_persian_digits(jy)}"
    return to_persian_digits(jy)


# Jinja2 Context-Aware Helpers
@pass_context
def jinja_get_locale(context: Any) -> str:
    return get_locale_from_request(context.get("request"))


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
    if val is None:
        return ""
    if locale == "fa":
        return to_persian_digits(val)
    return str(val)


@pass_context
def jinja_date_format(context: Any, dt: Union[date, datetime, str, None], show_month_name: bool = True) -> str:
    locale = jinja_get_locale(context)
    if not dt:
        return ""
    if isinstance(dt, str):
        try:
            dt = date.fromisoformat(dt[:10])
        except ValueError:
            return to_persian_digits(dt) if locale == "fa" else dt
    if locale == "fa":
        return format_jalali(dt, show_month_name=show_month_name)
    return dt.strftime("%b %d, %Y")


@pass_context
def jinja_date_short(context: Any, dt: Union[date, datetime, str, None]) -> str:
    locale = jinja_get_locale(context)
    if not dt:
        return ""
    if isinstance(dt, str):
        try:
            dt = date.fromisoformat(dt[:10])
        except ValueError:
            return to_persian_digits(dt) if locale == "fa" else dt
    if locale == "fa":
        return format_jalali_short(dt)
    return dt.strftime("%b %d")


@pass_context
def jinja_cal_day(context: Any, dt: Union[date, datetime, None]) -> str:
    locale = jinja_get_locale(context)
    if not dt:
        return ""
    if locale == "fa":
        _, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
        if jd == 1 and 1 <= jm <= 12:
            return f"{to_persian_digits(jd)} {_JALALI_MONTH_NAMES[jm]}"
        return to_persian_digits(jd)
    return str(dt.day)


@pass_context
def jinja_weekday(context: Any, day: Any) -> str:
    return translate_weekday(day, locale=jinja_get_locale(context))


@pass_context
def jinja_month_year(context: Any, dt: Union[date, datetime, None]) -> str:
    locale = jinja_get_locale(context)
    if not dt:
        return ""
    if locale == "fa":
        return format_jalali_month_year(dt)
    return dt.strftime("%B %Y")


@pass_context
def jinja_number_format(context: Any, val: Any, decimals: Optional[int] = None) -> str:
    locale = jinja_get_locale(context)
    if val is None or val == "":
        return ""
    if locale == "fa":
        return format_persian_number(val, decimals=decimals)
    if decimals is not None:
        try:
            return f"{float(val):,.{decimals}f}"
        except Exception:
            return str(val)
    return str(val)


@pass_context
def jinja_percent_format(context: Any, val: Any, decimals: Optional[int] = None) -> str:
    locale = jinja_get_locale(context)
    if val is None or val == "":
        return ""
    if locale == "fa":
        return format_persian_percent(val, decimals=decimals)
    if decimals is not None:
        try:
            return f"{float(val):.{decimals}f}%"
        except Exception:
            return f"{val}%"
    return f"{val}%"


@pass_context
def jinja_duration_format(context: Any, minutes: Any) -> str:
    return format_persian_duration(minutes, locale=jinja_get_locale(context))


@pass_context
def jinja_currency_format(context: Any, amount: Any, unit: Optional[str] = None) -> str:
    locale = jinja_get_locale(context)
    if locale == "fa":
        return format_persian_currency(amount, unit=unit or "تومان")
    return f"{amount} {unit}" if unit else str(amount)


@pass_context
def jinja_role_format(context: Any, role: Any) -> str:
    return translate_role(role, locale=jinja_get_locale(context))


@pass_context
def jinja_status_format(context: Any, status_val: Any) -> str:
    return translate_status(status_val, locale=jinja_get_locale(context))


def get_client_translations(locale: str = DEFAULT_LOCALE) -> Dict[str, str]:
    """Return curated JS-accessible translations for dynamic client-side interactions."""
    keys = [
        "error",
        "loading",
        "saving",
        "saved",
        "cancel",
        "confirm",
        "close",
        "delete",
        "edit",
        "add",
        "search",
        "no_results",
        "network_error",
        "session_expired",
        "js_enter_start_time",
        "js_could_not_move_meeting",
        "js_confirm_delete",
        "js_score_label",
        "js_percentage_label",
        "js_average_label",
        "js_exam_timer_warning",
        "js_submit_exam_confirm",
        "js_time_remaining",
        "js_unanswered_warning",
        "js_minutes_short",
        "js_hours_short",
        "js_tasks_count",
        "js_drag_drop_error",
        "js_plan_saved",
        "js_copy_success",
        "js_saving_answer",
        "js_all_answers_saved",
        "js_failed_to_save",
        "js_booklet_locked_advancing",
        "js_network_reverting",
        "js_advancing_next_section",
        "js_avg_pct_achieved",
        "js_total_correct",
        "js_total_incorrect",
        "js_add_task_prefix",
        "js_select_chapter_opt",
        "js_select_course_opt",
        "js_select_book_opt",
        "js_confirm_delete_subject",
        "js_confirm_delete_chapter",
        "js_confirm_delete_book",
        "js_paste_keys_alert",
        "js_applied_keys_alert",
        "js_select_subject_first",
        "js_applied_subject_range",
    ]
    return {k: translate(k, locale=locale) for k in keys}


def localize_html_content(html: str, locale: str = DEFAULT_LOCALE) -> str:
    if locale != "fa" or not html:
        return html

    if not _TRANSLATIONS:
        _load_translations()
    fa_dict = _TRANSLATIONS.get("fa", {})

    # 1. Protect script, style, code, and pre tags
    preserved = []
    def preserve_tag(m: re.Match) -> str:
        preserved.append(m.group(0))
        return f"___VALHALLA_PROTECTED_{len(preserved)-1}___"

    html = re.sub(r'<(script|style|code|pre)[^>]*>.*?</\1>', preserve_tag, html, flags=re.DOTALL | re.IGNORECASE)

    # 2. Localize attributes: placeholder, title, aria-label, hx-confirm, data-confirm
    def replace_attr(m: re.Match) -> str:
        attr_name = m.group(1)
        attr_val = m.group(2)
        trans = fa_dict.get(attr_val.strip())
        if trans:
            return f'{attr_name}="{trans}"'
        return m.group(0)

    html = re.sub(r'\b(placeholder|title|aria-label|hx-confirm|data-confirm)="([^"]*)"', replace_attr, html)

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

    # 5. Restore protected tags
    for i, p in enumerate(preserved):
        html = html.replace(f"___VALHALLA_PROTECTED_{i}___", p)

    return html
