"""Minimal valid PDF generator for demo booklets and report cards."""
import os
import uuid
from pathlib import Path
from app.core.storage import get_upload_base_path, FilePathTraversalError


def create_minimal_pdf_bytes(title: str, subtitle: str = "") -> bytes:
    """Generate valid binary PDF-1.4 content with text."""
    safe_title = title.encode("ascii", "replace").decode("ascii")
    safe_sub = subtitle.encode("ascii", "replace").decode("ascii")
    content_stream = f"BT /F1 18 Tf 50 720 Td ({safe_title}) Tj ET\n"
    if safe_sub:
        content_stream += f"BT /F1 12 Tf 50 690 Td ({safe_sub}) Tj ET\n"
    stream_bytes = content_stream.encode("latin-1")
    length = len(stream_bytes)

    objects = [
        b"%PDF-1.4\n",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        f"5 0 obj\n<< /Length {length} >>\nstream\n".encode("ascii") + stream_bytes + b"\nendstream\nendobj\n",
    ]

    offsets = []
    current_offset = 0
    body = b""
    for i, obj in enumerate(objects):
        if i == 0:
            current_offset += len(obj)
            body += obj
            continue
        offsets.append(current_offset)
        current_offset += len(obj)
        body += obj

    xref = f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode("ascii")
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode("ascii")

    trailer = f"trailer\n<< /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{current_offset}\n%%EOF\n".encode("ascii")
    return body + xref + trailer


def save_demo_pdf(subfolder: str, filename_prefix: str, title: str, subtitle: str = "") -> tuple[str, str]:
    """Save demo PDF to upload directory and return (relative_path, display_name)."""
    upload_base = get_upload_base_path().resolve()

    if not subfolder or not isinstance(subfolder, str) or not subfolder.strip():
        raise FilePathTraversalError("Invalid subfolder.")

    subfolder_path = Path(subfolder.strip())
    if subfolder_path.is_absolute() or ".." in subfolder_path.parts:
        raise FilePathTraversalError("Path traversal or absolute paths are not permitted in subfolder.")

    folder_path = (upload_base / subfolder_path).resolve()
    if not folder_path.is_relative_to(upload_base):
        raise FilePathTraversalError("Subfolder path escapes upload directory.")

    folder_path.mkdir(parents=True, exist_ok=True)

    safe_prefix = os.path.basename(filename_prefix.strip()).replace("/", "").replace("\\", "")
    if not safe_prefix or ".." in safe_prefix:
        safe_prefix = "demo"

    file_uuid = uuid.uuid4().hex
    storage_name = f"demo_{safe_prefix}_{file_uuid}.pdf"
    target_path = (folder_path / storage_name).resolve()

    if not target_path.is_relative_to(upload_base) or not target_path.is_relative_to(folder_path):
        raise FilePathTraversalError("Target path escapes upload directory.")

    pdf_data = create_minimal_pdf_bytes(title, subtitle)
    with open(target_path, "wb") as f:
        f.write(pdf_data)

    rel_path = str(target_path.relative_to(upload_base)).replace("\\", "/")
    display_name = f"{safe_prefix}.pdf"
    return rel_path, display_name
