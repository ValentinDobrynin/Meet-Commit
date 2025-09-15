from __future__ import annotations
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path

import webvtt
from docx import Document
from pdfminer.high_level import extract_text as pdf_extract

DATE_PATTERNS = [
    r"(?P<d>\d{1,2})[._-](?P<m>\d{1,2})[._-](?P<y>\d{4})",
    r"(?P<y>\d{4})[._-](?P<m>\d{1,2})[._-](?P<d>\d{1,2})",
    r"(?P<d>\d{1,2})[._-](?P<m>\d{1,2})(?=[._-]|$)",  # без года, улучшенный
    # Добавляем поддержку русских месяцев
    r"(?P<d>\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(?P<y>\d{4})",
    r"(?P<d>\d{1,2})\s+(янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)\s+(?P<y>\d{4})",
]

MONTH_NAMES = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "июн": 6, "июл": 7,
    "авг": 8, "сен": 9, "окт": 10, "ноя": 11,     "дек": 12,
}

DICT_DIR = Path(__file__).resolve().parent.parent / "dictionaries"

def _load_people() -> list[dict]:
    """Загружает словарь людей из JSON файла."""
    p = DICT_DIR / "people.json"
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("people", [])
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def _extract_attendees_en(text: str, max_scan: int = 8000) -> list[str]:
    """Извлекает участников встречи и возвращает их канонические английские имена."""
    people = _load_people()
    hay = text[:max_scan].lower()
    found: list[str] = []
    
    for person in people:
        name_en = (person.get("name_en") or "").strip()
        if not name_en:
            continue
            
        aliases = person.get("aliases", [])
        for alias in aliases:
            alias_clean = (alias or "").strip().lower()
            if alias_clean and alias_clean in hay:
                if name_en not in found:
                    found.append(name_en)
                break  # Нашли этого человека, переходим к следующему
    
    return found

def _infer_date_from_text(s: str) -> date | None:
    """Извлекает дату из текста используя различные паттерны."""
    s = s.strip()
    
    # Сначала пробуем числовые паттерны
    for pat in DATE_PATTERNS[:3]:  # только числовые
        m = re.search(pat, s, re.IGNORECASE)
        if not m:
            continue
        gd = m.groupdict()
        d = int(gd["d"]) if "d" in gd else None
        mth = int(gd["m"])
        y = int(gd["y"]) if "y" in gd else None
        
        if d and y:
            try:
                return date(y, mth, d)
            except ValueError:
                continue
        if d and not y:
            today = date.today()
            try:
                cand = date(today.year, mth, d)
                # если «будущее» далеко (более 60 дней), считаем прошлый год
                if cand - today > timedelta(days=60):
                    cand = date(today.year - 1, mth, d)
                return cand
            except ValueError:
                continue
    
    # Затем пробуем текстовые паттерны с русскими месяцами
    for pat in DATE_PATTERNS[3:]:
        m = re.search(pat, s, re.IGNORECASE)
        if not m:
            continue
        gd = m.groupdict()
        d = int(gd["d"])
        y = int(gd["y"])
        
        # Находим название месяца в тексте
        month_text = None
        for month_name in MONTH_NAMES:
            if month_name.lower() in s.lower():
                month_text = month_name
                break
        
        if month_text:
            mth = MONTH_NAMES[month_text]
            try:
                return date(y, mth, d)
            except ValueError:
                continue
    
    return None

def _infer_meeting_date(filename: str, text: str) -> str:
    """Определяет дату встречи из имени файла или текста."""
    # 1) по имени файла
    filename_stem = Path(filename).stem
    dt = _infer_date_from_text(filename_stem)
    
    # 2) по тексту (первые 5000 символов достаточно)
    if not dt:
        dt = _infer_date_from_text(text[:5000])
    
    # 3) fallback: сегодня
    if not dt:
        dt = date.today()
    
    return dt.isoformat()

def _ext(name: str) -> str:
    return Path(name).suffix.lower()

def _read_text(raw_bytes: bytes | None, text: str | None, filename: str) -> str:
    if text:
        return text
    ext = _ext(filename)
    if ext == ".pdf":
        return pdf_extract(fp=BytesIO(raw_bytes or b""))
    if ext == ".docx":
        doc = Document(BytesIO(raw_bytes or b""))
        return "\n".join(p.text for p in doc.paragraphs)
    if ext in {".vtt", ".webvtt"}:
        buf = (raw_bytes or b"").decode("utf-8", errors="ignore")
        return "\n".join(c.text for c in webvtt.read_buffer(StringIO(buf)))
    return (raw_bytes or b"").decode("utf-8", errors="ignore")

def run(raw_bytes: bytes | None, text: str | None, filename: str) -> dict:
    content = _read_text(raw_bytes, text, filename)
    clean = content.strip()
    sha = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    title = (Path(filename).stem or "Meeting")[:80]
    date_iso = _infer_meeting_date(filename, clean)
    attendees = _extract_attendees_en(clean)  # английские канонические имена
    return {"title": title, "date": date_iso, "attendees": attendees, "text": clean, "raw_hash": sha}
