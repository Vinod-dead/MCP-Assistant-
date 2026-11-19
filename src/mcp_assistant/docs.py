"""Text extraction for the document-reading tools (txt/md/code/csv/pdf/docx)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

MAX_BYTES = 5_000_000
_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".sql", ".html",
    ".css", ".xml", ".sh", ".ipynb",
}


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTS | {".pdf", ".docx"}


def extract_text(path: Path) -> str:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"File too large (> {MAX_BYTES // 1_000_000} MB).")
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n\n".join(f"[page {i + 1}]\n{(page.extract_text() or '').strip()}" for i, page in enumerate(reader.pages))
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    raw = path.read_bytes()
    if b"\x00" in raw[:2048]:
        raise ValueError("This looks like a binary file; only text, PDF and DOCX files can be read.")
    return raw.decode("utf-8", errors="replace")
