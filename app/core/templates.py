from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi.templating import Jinja2Templates

from app.core.timezone import to_local
from app.core.i18n import (
    jinja_date_format,
    jinja_get_locale,
    jinja_is_rtl,
    jinja_persian_digits,
    jinja_translate,
)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.autoescape = True


def format_local_dt(dt: Optional[datetime], tz_name: Optional[str] = None, fmt: str = "%b %d, %Y %I:%M %p") -> str:
    if not dt:
        return ""
    local = to_local(dt, tz_name)
    return local.strftime(fmt)


def format_chat_time(dt: Optional[datetime], tz_name: Optional[str] = None) -> str:
    if not dt:
        return ""
    local = to_local(dt, tz_name)
    now_local = to_local(datetime.now(), tz_name)
    if local.date() == now_local.date():
        return local.strftime("%I:%M %p")
    if local.year == now_local.year:
        return local.strftime("%b %d, %I:%M %p")
    return local.strftime("%b %d, %Y %I:%M %p")


templates.env.filters["local_dt"] = format_local_dt
templates.env.filters["chat_time"] = format_chat_time
templates.env.filters["t"] = jinja_translate
templates.env.filters["fa_digits"] = jinja_persian_digits
templates.env.filters["smart_date"] = jinja_date_format

templates.env.globals["_"] = jinja_translate
templates.env.globals["get_locale"] = jinja_get_locale
templates.env.globals["is_rtl"] = jinja_is_rtl


