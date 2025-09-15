import hashlib
from datetime import datetime
from pathlib import Path

import webvtt
from docx import Document
from pdfminer.high_level import extract_text as pdf_extract


def _ext(name: str) -> str:
    return Path(name).suffix.lower()


def _read_text(raw_bytes: bytes | None, text: str | None, filename: str) -> str:
    if text:
        return text
    ext = _ext(filename)
    if ext == ".pdf":
        return pdf_extract(fp=raw_bytes)
    if ext == ".docx":
        from io import BytesIO

        doc = Document(BytesIO(raw_bytes))
        return "\n".join([p.text for p in doc.paragraphs])
    if ext == ".vtt":
        from io import BytesIO, StringIO

        tmp = BytesIO(raw_bytes).read().decode("utf-8", errors="ignore")
        return "\n".join([c.text for c in webvtt.read_buffer(StringIO(tmp))])
    return raw_bytes.decode("utf-8", errors="ignore")


def run(raw_bytes: bytes | None, text: str | None, filename: str) -> dict:
    content = _read_text(raw_bytes, text, filename)
    clean = content.strip()
    sha = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    title = Path(filename).stem[:80] or "Meeting"
    date_iso = datetime.utcnow().date().isoformat()
    attendees = []  # v0: позже подтянем из текста
    return {
        "title": title,
        "date": date_iso,
        "attendees": attendees,
        "text": clean,
        "raw_hash": sha,
    }
