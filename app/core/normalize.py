from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from io import BytesIO, StringIO
from pathlib import Path

import webvtt
from docx import Document
from pdfminer.high_level import extract_text as pdf_extract

from app.core.metrics import MetricNames, wrap_timer

DATE_PATTERNS = [
    r"(?P<d>\d{1,2})[._-](?P<m>\d{1,2})[._-](?P<y>\d{4})",
    r"(?P<y>\d{4})[._-](?P<m>\d{1,2})[._-](?P<d>\d{1,2})",
    r"(?P<d>\d{1,2})[._-](?P<m>\d{1,2})(?=[._-]|$)",  # без года, улучшенный
    # Добавляем поддержку русских месяцев
    r"(?P<d>\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(?P<y>\d{4})",
    r"(?P<d>\d{1,2})\s+(янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)\s+(?P<y>\d{4})",
]

MONTH_NAMES = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}

DICT_DIR = Path(__file__).resolve().parent.parent / "dictionaries"

# === NEW: Enhanced month maps for word-based date parsing ===
RU_MONTHS = {
    # именительный/родительный падежи и разговорные формы
    "январь": "01",
    "янв": "01",
    "января": "01",
    "январе": "01",
    "февраль": "02",
    "фев": "02",
    "февраля": "02",
    "феврале": "02",
    "март": "03",
    "мар": "03",
    "марта": "03",
    "марте": "03",
    "апрель": "04",
    "апр": "04",
    "апреля": "04",
    "апреле": "04",
    "май": "05",
    "мая": "05",
    "мае": "05",
    "июнь": "06",
    "июн": "06",
    "июня": "06",
    "июне": "06",
    "июль": "07",
    "июл": "07",
    "июля": "07",
    "июле": "07",
    "август": "08",
    "авг": "08",
    "августа": "08",
    "августе": "08",
    "сентябрь": "09",
    "сен": "09",
    "сентября": "09",
    "сентябре": "09",
    "октябрь": "10",
    "окт": "10",
    "октября": "10",
    "октябре": "10",
    "ноябрь": "11",
    "ноя": "11",
    "ноября": "11",
    "ноябре": "11",
    "декабрь": "12",
    "дек": "12",
    "декабря": "12",
    "декабре": "12",
}

EN_MONTHS = {
    "january": "01",
    "jan": "01",
    "february": "02",
    "feb": "02",
    "march": "03",
    "mar": "03",
    "april": "04",
    "apr": "04",
    "may": "05",
    "june": "06",
    "jun": "06",
    "july": "07",
    "jul": "07",
    "august": "08",
    "aug": "08",
    "september": "09",
    "sep": "09",
    "sept": "09",
    "october": "10",
    "oct": "10",
    "november": "11",
    "nov": "11",
    "december": "12",
    "dec": "12",
}

# === NEW: Word-based date patterns ===
# 25 марта 2025 / 25 мар 2025 / 25 March 2025 / Mar 25, 2025 / 25 Apr
PAT_WORD_RU = re.compile(
    r"\b(?P<d>\d{1,2})\s+(?P<m>[А-Яа-яЁё\.]+)\s*(?P<y>\d{4})?\b", re.IGNORECASE
)
PAT_WORD_EN_DMY = re.compile(
    r"\b(?P<d>\d{1,2})\s+(?P<m>[A-Za-z\.]+)\s*(?P<y>\d{4})?\b", re.IGNORECASE
)
PAT_WORD_EN_MDY = re.compile(
    r"\b(?P<m>[A-Za-z\.]+)\s+(?P<d>\d{1,2})(?:,)?\s*(?P<y>\d{4})?\b", re.IGNORECASE
)


def _load_people() -> list[dict]:
    """Загружает словарь людей из JSON файла."""
    p = DICT_DIR / "people.json"
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
            # Поддерживаем оба формата: новый [dict, ...] и старый {"people": [dict, ...]}
            if isinstance(data, list):
                return data  # Новый формат
            elif isinstance(data, dict) and "people" in data:
                people_data = data["people"]
                return people_data if isinstance(people_data, list) else []  # Старый формат
            else:
                return []
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


def _map_month(token: str) -> str | None:
    """Маппинг названия месяца в номер (01-12)."""
    t = token.strip(". ").lower()
    return RU_MONTHS.get(t) or EN_MONTHS.get(t)


def _infer_date_from_words(s: str) -> date | None:
    """Извлекает дату из текста используя названия месяцев."""

    def _mk(d: int, m_tok: str, y: int | None) -> date | None:
        mm = _map_month(m_tok)
        if not mm:
            return None

        try:
            if y is None:
                # без года → эвристика: текущий или прошлый, как и раньше
                today = date.today()
                cand = date(today.year, int(mm), d)
                if cand - today > timedelta(days=60):
                    cand = date(today.year - 1, int(mm), d)
                return cand
            return date(y, int(mm), d)
        except ValueError:
            return None

    # Пробуем разные паттерны
    for pat in (PAT_WORD_RU, PAT_WORD_EN_DMY, PAT_WORD_EN_MDY):
        m = pat.search(s)
        if m:
            gd = m.groupdict()
            try:
                d = int(gd["d"])
                y = int(gd["y"]) if gd.get("y") else None
                return _mk(d, gd["m"], y)
            except (ValueError, TypeError):
                continue
    return None


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
    # 1) по имени файла (числовые паттерны)
    filename_stem = Path(filename).stem
    dt = _infer_date_from_text(filename_stem)

    # 2) NEW: по тексту используя названия месяцев (приоритет)
    if not dt:
        dt = _infer_date_from_words(text[:6000])

    # 3) по тексту используя числовые паттерны (fallback)
    if not dt:
        dt = _infer_date_from_text(text[:5000])

    # 4) fallback: сегодня
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
        return pdf_extract(BytesIO(raw_bytes or b""))
    if ext == ".docx":
        doc = Document(BytesIO(raw_bytes or b""))
        return "\n".join(p.text for p in doc.paragraphs)
    if ext in {".vtt", ".webvtt"}:
        buf = (raw_bytes or b"").decode("utf-8", errors="ignore")
        return "\n".join(c.text for c in webvtt.read_buffer(StringIO(buf)))
    return (raw_bytes or b"").decode("utf-8", errors="ignore")


@wrap_timer(MetricNames.INGEST_EXTRACT)
def run(raw_bytes: bytes | None, text: str | None, filename: str) -> dict:
    content = _read_text(raw_bytes, text, filename)
    clean = content.strip()
    sha = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    title = (Path(filename).stem or "Meeting")[:80]
    date_iso = _infer_meeting_date(filename, clean)
    attendees = _extract_attendees_en(clean)  # английские канонические имена

    # Собираем кандидатов в новые имена для пополнения словаря
    from app.core.people_detect import mine_alias_candidates
    from app.core.people_store import bump_candidates

    unknown_aliases = mine_alias_candidates(clean)
    # Если есть новые кандидаты, добавляем их в очередь для ручной проверки
    if unknown_aliases:
        bump_candidates(unknown_aliases)

    return {
        "title": title,
        "date": date_iso,
        "attendees": attendees,
        "text": clean,
        "raw_hash": sha,
    }
