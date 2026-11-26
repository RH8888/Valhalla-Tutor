import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.responses import Response

from app.core.timezone import to_local
from app.core.i18n import (
    format_jalali,
    get_client_translations,
    get_locale_from_request,
    jinja_currency_format,
    jinja_cal_day,
    jinja_date_format,
    jinja_date_short,
    jinja_duration_format,
    jinja_get_locale,
    jinja_is_rtl,
    jinja_month_year,
    jinja_number_format,
    jinja_percent_format,
    jinja_persian_digits,
    jinja_role_format,
    jinja_status_format,
    jinja_translate,
    jinja_weekday,
    localize_html_content,
    to_persian_digits,
    translate,
)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class ValhallaTemplates(Jinja2Templates):
    def TemplateResponse(self, *args: Any, **kwargs: Any) -> Response:
        request = kwargs.get("request")
        if not request and args and hasattr(args[0], "scope"):
            request = args[0]

        locale = get_locale_from_request(request)

        context = kwargs.get("context")
        if context is None and len(args) > 1 and isinstance(args[1], dict):
            context = args[1]

        if locale == "fa" and isinstance(context, dict):
            for k in ("msg", "message", "error", "err", "success", "warning"):
                val = context.get(k)
                if val and isinstance(val, str):
                    context[k] = translate(val, locale="fa")

        resp = super().TemplateResponse(*args, **kwargs)

        if locale == "fa" and hasattr(resp, "body"):
            try:
                raw_html = resp.body.decode("utf-8")
                localized = localize_html_content(raw_html, locale="fa")
                resp.body = localized.encode("utf-8")
                if "content-length" in resp.headers:
                    resp.headers["content-length"] = str(len(resp.body))
            except Exception:
                pass

        # Ensure responses vary by Cookie so LTR/RTL pages aren't cross-cached
        existing_vary = resp.headers.get("Vary", "")
        if "Cookie" not in existing_vary:
            resp.headers["Vary"] = f"{existing_vary}, Cookie".strip(", ")

        return resp


templates = ValhallaTemplates(directory=str(TEMPLATES_DIR))
templates.env.autoescape = True


@pass_context
def format_local_dt(context: Any, dt: Optional[datetime], tz_name: Optional[str] = None, fmt: str = "%b %d, %Y %I:%M %p") -> str:
    if not dt:
        return ""
    local = to_local(dt, tz_name)
    if jinja_get_locale(context) == "fa":
        time_str = to_persian_digits(local.strftime("%H:%M"))
        return f"{format_jalali(local)} - {time_str}"
    return local.strftime(fmt)


@pass_context
def format_chat_time(context: Any, dt: Optional[datetime], tz_name: Optional[str] = None) -> str:
    if not dt:
        return ""
    local = to_local(dt, tz_name)
    now_local = to_local(datetime.now(), tz_name)
    if jinja_get_locale(context) == "fa":
        time_str = to_persian_digits(local.strftime("%H:%M"))
        if local.date() == now_local.date():
            return time_str
        return f"{format_jalali(local)} {time_str}"
    if local.date() == now_local.date():
        return local.strftime("%I:%M %p")
    if local.year == now_local.year:
        return local.strftime("%b %d, %I:%M %p")
    return local.strftime("%b %d, %Y %I:%M %p")


@pass_context
def client_i18n_data(context: Any) -> dict[str, str]:
    locale = jinja_get_locale(context)
    return get_client_translations(locale)


@pass_context
def client_i18n_json(context: Any) -> str:
    locale = jinja_get_locale(context)
    return json.dumps(get_client_translations(locale), ensure_ascii=False)


templates.env.filters["local_dt"] = format_local_dt
templates.env.filters["chat_time"] = format_chat_time
templates.env.filters["t"] = jinja_translate
templates.env.filters["fa_digits"] = jinja_persian_digits
templates.env.filters["smart_date"] = jinja_date_format
templates.env.filters["smart_date_short"] = jinja_date_short
templates.env.filters["smart_cal_day"] = jinja_cal_day
templates.env.filters["smart_weekday"] = jinja_weekday
templates.env.filters["smart_month_year"] = jinja_month_year
templates.env.filters["fa_num"] = jinja_number_format
templates.env.filters["fa_percent"] = jinja_percent_format
templates.env.filters["fa_duration"] = jinja_duration_format
templates.env.filters["fa_currency"] = jinja_currency_format
templates.env.filters["fa_role"] = jinja_role_format
templates.env.filters["fa_status"] = jinja_status_format

templates.env.globals["_"] = jinja_translate
templates.env.globals["get_locale"] = jinja_get_locale
templates.env.globals["is_rtl"] = jinja_is_rtl
templates.env.globals["client_i18n_data"] = client_i18n_data
templates.env.globals["client_i18n_json"] = client_i18n_json


