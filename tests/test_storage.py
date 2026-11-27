import io
import pytest
from fastapi import HTTPException, UploadFile
from pathlib import Path
from starlette.datastructures import Headers

from app.core.storage import (
    BOOKLET_ALLOWED_EXTENSIONS,
    BOOKLET_ALLOWED_MIMES,
    REPORT_CARD_ALLOWED_EXTENSIONS,
    REPORT_CARD_ALLOWED_MIMES,
    FilePathTraversalError,
    get_absolute_file_path,
    get_upload_base_path,
    save_uploaded_file,
    validate_magic_bytes,
)


def test_get_absolute_file_path_valid():
    base = get_upload_base_path().resolve()
    
    path1 = get_absolute_file_path("practice_booklets/mock_b1.pdf")
    assert path1 == base / "practice_booklets" / "mock_b1.pdf"
    assert path1.is_relative_to(base)

    path2 = get_absolute_file_path("report_cards/sub/result.png")
    assert path2 == base / "report_cards" / "sub" / "result.png"
    assert path2.is_relative_to(base)


@pytest.mark.parametrize(
    "traversal_path",
    [
        "../secret.txt",
        "../../etc/passwd",
        "booklets/../../secret.txt",
        "booklets/../booklets/test.pdf",
    ],
)
def test_get_absolute_file_path_rejects_traversal(traversal_path):
    with pytest.raises(FilePathTraversalError) as exc_info:
        get_absolute_file_path(traversal_path)
    assert exc_info.value.status_code == 400
    assert isinstance(exc_info.value, HTTPException)
    assert isinstance(exc_info.value, ValueError)


@pytest.mark.parametrize(
    "abs_path",
    [
        "/etc/passwd",
        "/report_cards/sample.png",
        "C:/Windows/win.ini",
        "C:\\Windows\\system32",
        "\\\\server\\share\\data",
    ],
)
def test_get_absolute_file_path_rejects_absolute_paths(abs_path):
    with pytest.raises(FilePathTraversalError) as exc_info:
        get_absolute_file_path(abs_path)
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    "invalid_path",
    [
        "",
        "   ",
        None,
        ".",
        "file\x00name.pdf",
    ],
)
def test_get_absolute_file_path_rejects_empty_and_malformed(invalid_path):
    with pytest.raises(FilePathTraversalError) as exc_info:
        get_absolute_file_path(invalid_path)
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    "ext,payload,content_type",
    [
        (".pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "application/pdf"),
        (".pdf", b"%PDF-1.4\nbody", "application/octet-stream"),
        (".png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image/png"),
        (".jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
        (".jpeg", b"\xff\xd8\xff\xe1\x00\x18Exif", "image/jpeg"),
        (".webp", b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image/webp"),
    ],
)
def test_save_uploaded_file_accepts_valid_magic_bytes(tmp_path, monkeypatch, ext, payload, content_type):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    upload = UploadFile(
        file=io.BytesIO(payload),
        filename=f"valid{ext}",
        headers=Headers({"content-type": content_type}),
    )
    allowed_exts = BOOKLET_ALLOWED_EXTENSIONS if ext == ".pdf" else REPORT_CARD_ALLOWED_EXTENSIONS
    allowed_mimes = BOOKLET_ALLOWED_MIMES if ext == ".pdf" else REPORT_CARD_ALLOWED_MIMES

    rel_path, orig = save_uploaded_file(
        upload,
        subfolder="test_uploads",
        allowed_exts=allowed_exts,
        allowed_mimes=allowed_mimes,
        max_size=1024 * 1024,
    )
    assert orig == f"valid{ext}"
    saved = tmp_path / rel_path
    assert saved.exists()
    assert saved.read_bytes() == payload


@pytest.mark.parametrize(
    "filename,payload,content_type",
    [
        ("evil.pdf", b"<html><script>alert(1)</script></html>", "application/pdf"),
        ("fake.pdf", b"MZ\x90\x00\x03\x00\x00\x00", "application/octet-stream"),
        ("fake.png", b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/png"),
        ("fake.jpg", b"\x89PNG\r\n\x1a\n\x00\x00", "image/jpeg"),
        ("fake.webp", b"RIFF\x00\x00\x00\x00AVI ", "image/webp"),
        ("empty.pdf", b"", "application/pdf"),
    ],
)
def test_save_uploaded_file_rejects_spoofed_or_empty_files(tmp_path, monkeypatch, filename, payload, content_type):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    upload = UploadFile(
        file=io.BytesIO(payload),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )
    with pytest.raises(HTTPException) as exc_info:
        save_uploaded_file(
            upload,
            subfolder="test_uploads",
            allowed_exts=REPORT_CARD_ALLOWED_EXTENSIONS,
            allowed_mimes=REPORT_CARD_ALLOWED_MIMES,
            max_size=1024 * 1024,
        )
    assert exc_info.value.status_code == 400
    assert list((tmp_path / "test_uploads").glob("*")) == []


def test_validate_magic_bytes_unknown_extension():
    assert validate_magic_bytes(b"%PDF-1.4", ".exe") is False
