from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import (
    get_current_session,
    get_current_user,
    require_tutor,
    verify_csrf_token,
)
from app.core.templates import templates
from app.models.session import UserSession
from app.models.user import User
from app.services.telegram_backup_service import (
    create_and_deliver_manual_backup,
    get_or_create_telegram_settings,
    test_saved_telegram_connection,
    update_telegram_settings,
)

router = APIRouter(
    prefix="/tutor/settings",
    tags=["tutor_settings"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("/backup", response_class=HTMLResponse)
def get_telegram_backup_settings(
    request: Request,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    tg_settings = get_or_create_telegram_settings(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/settings/backup.html",
        context={
            "tg_settings": tg_settings,
            "has_token": bool(tg_settings.encrypted_bot_token),
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/backup")
def post_save_telegram_backup_settings(
    enabled: Optional[str] = Form(None),
    chat_id: Optional[str] = Form(None),
    bot_token: Optional[str] = Form(None),
    clear_bot_token: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    is_enabled = enabled in ("1", "true", "on", "yes")
    should_clear = clear_bot_token in ("1", "true", "on", "yes")

    update_telegram_settings(
        db,
        enabled=is_enabled,
        chat_id=chat_id,
        new_bot_token=bot_token,
        clear_bot_token=should_clear,
    )
    return RedirectResponse(
        url=f"/tutor/settings/backup?msg={quote('Telegram backup settings saved.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/backup/test")
def post_test_telegram_connection(db: Session = Depends(get_db)):
    ok, message = test_saved_telegram_connection(db)
    param = "msg" if ok else "err"
    return RedirectResponse(
        url=f"/tutor/settings/backup?{param}={quote(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/backup/run-now")
def post_run_telegram_backup_now(db: Session = Depends(get_db)):
    res = create_and_deliver_manual_backup(db)
    param = "msg" if res.delivered else "err"
    return RedirectResponse(
        url=f"/tutor/settings/backup?{param}={quote(res.message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
