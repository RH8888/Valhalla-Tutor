import pytest
from fastapi import HTTPException
from pathlib import Path

from app.core.storage import (
    FilePathTraversalError,
    get_absolute_file_path,
    get_upload_base_path,
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
