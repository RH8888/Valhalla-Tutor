import os
import uuid
from pathlib import Path
from typing import Tuple
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

BOOKLET_ALLOWED_EXTENSIONS = {".pdf"}
BOOKLET_ALLOWED_MIMES = {"application/pdf"}
BOOKLET_MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

REPORT_CARD_ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
REPORT_CARD_ALLOWED_MIMES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
}
REPORT_CARD_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def get_upload_base_path() -> Path:
    base = Path(settings.UPLOAD_DIR)
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_uploaded_file(
    file: UploadFile,
    subfolder: str,
    allowed_exts: set[str],
    allowed_mimes: set[str],
    max_size: int,
) -> Tuple[str, str]:
    """
    Validate and save uploaded file using a safe UUID filename.
    Returns (relative_storage_path, original_filename).
    """
    original_filename = file.filename or "uploaded_file"
    ext = os.path.splitext(original_filename)[1].lower()

    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File extension '{ext}' is not permitted. Allowed: {', '.join(sorted(allowed_exts))}",
        )

    content_type = (file.content_type or "").lower()
    if content_type and content_type not in allowed_mimes and "application/octet-stream" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File content type '{content_type}' is not allowed.",
        )

    # Read contents and check size
    contents = file.file.read()
    if len(contents) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed size of {max_size // (1024 * 1024)} MB.",
        )

    folder_path = get_upload_base_path() / subfolder
    folder_path.mkdir(parents=True, exist_ok=True)

    safe_filename = f"{uuid.uuid4().hex}{ext}"
    target_path = folder_path / safe_filename

    with open(target_path, "wb") as f:
        f.write(contents)

    relative_path = f"{subfolder}/{safe_filename}"
    return relative_path, original_filename


def get_absolute_file_path(relative_path: str) -> Path:
    return get_upload_base_path() / relative_path

