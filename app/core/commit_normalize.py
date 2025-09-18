# app/core/commit_normalize.py
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from hashlib import sha256

from app.core.llm_extract_commits import ExtractedCommit
from app.core.people_store import load_people

# ====== Парсинг due ======

RU_MONTHS = {
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

# Паттерны для парсинга дат
PAT_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
PAT_DMY_DOTS = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
PAT_DMY_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
PAT_DMY_SHORT = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?!\d)\b")  # без года
PAT_WORD_RU = re.compile(r"\b(?P<d>\d{1,2})\s+(?P<m>[А-Яа-яЁё\.]+)\s*(?P<y>20\d{2})?\b")
PAT_WORD_EN_DMY = re.compile(r"\b(?P<d>\d{1,2})\s+(?P<m>[A-Za-z\.]+)\s*(?P<y>20\d{2})?\b")
PAT_WORD_EN_MDY = re.compile(r"\b(?P<m>[A-Za-z\.]+)\s+(?P<d>\d{1,2})(?:,)?\s*(?P<y>20\d{2})?\b")


def _map_month(token: str) -> str | None:
    """Маппинг названия месяца в номер (01-12)."""
    t = token.strip(". ").lower()
    return RU_MONTHS.get(t) or EN_MONTHS.get(t)


def _safe_date(year: int, month: int, day: int) -> str | None:
    """Безопасное создание ISO даты с валидацией."""
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _infer_year_for_partial(month: int, day: int, meeting_date: date) -> int:
    """
    Определяет год для частичной даты (день/месяц без года).

    Логика: берем год встречи, но если получилось сильно в будущем
    (60+ дней), откатываемся на прошлый год.
    """
    try:
        candidate = date(meeting_date.year, month, day)
        if candidate - meeting_date > timedelta(days=60):
            return meeting_date.year - 1
        return meeting_date.year
    except ValueError:
        # Если дата невалидна (например, 29 февраля), пробуем прошлый год
        return meeting_date.year - 1


def validate_date_iso(date_str: str | None) -> str | None:
    """
    Валидирует ISO дату, возвращает валидную дату или None.

    Args:
        date_str: Строка даты для валидации

    Returns:
        Валидная ISO дата (YYYY-MM-DD) или None

    Example:
        validate_date_iso("2024-12-31") -> "2024-12-31"
        validate_date_iso("31/12/2024") -> None
        validate_date_iso("") -> None
    """
    if not date_str:
        return None

    try:
        date.fromisoformat(date_str.strip())
        return date_str.strip()
    except ValueError:
        return None


def parse_due_iso(text: str, meeting_date_iso: str) -> str | None:
    """
    Извлекает дату дедлайна из текста.

    Args:
        text: Текст для парсинга (обычно commit.text + commit.context)
        meeting_date_iso: Дата встречи в формате YYYY-MM-DD

    Returns:
        ISO дата (YYYY-MM-DD) или None если дата не найдена

    Поддерживаемые форматы:
        - ISO: 2024-12-31
        - DMY с точками: 31.12.2024
        - DMY со слэшами: 31/12/2024
        - Словесные: "15 марта 2024", "Mar 15, 2024"
        - Частичные: "15.12" (без года)
    """
    if not text or not meeting_date_iso:
        return None

    # ISO формат: 2024-12-31
    match = PAT_ISO.search(text)
    if match:
        year, month, day = map(int, match.groups())
        return _safe_date(year, month, day)

    # D.M.Y формат: 31.12.2024
    match = PAT_DMY_DOTS.search(text)
    if match:
        day, month, year = map(int, match.groups())
        return _safe_date(year, month, day)

    # D/M/Y формат: 31/12/2024
    match = PAT_DMY_SLASH.search(text)
    if match:
        day, month, year = map(int, match.groups())
        return _safe_date(year, month, day)

    # Словесные форматы с месяцами
    for pattern in (PAT_WORD_RU, PAT_WORD_EN_DMY, PAT_WORD_EN_MDY):
        match = pattern.search(text)
        if match:
            groups = match.groupdict()
            day = int(groups["d"])
            year_str = groups.get("y")
            month_str = _map_month(groups["m"])

            if not month_str:
                continue

            if year_str is None:
                if not meeting_date_iso:
                    continue
                try:
                    meeting_date = date.fromisoformat(meeting_date_iso)
                except ValueError:
                    continue
                year = _infer_year_for_partial(int(month_str), day, meeting_date)
            else:
                year = int(year_str)

            return _safe_date(year, int(month_str), day)

    # D.M формат без года: 31.12
    match = PAT_DMY_SHORT.search(text)
    if match:
        if not meeting_date_iso:
            return None
        try:
            meeting_date = date.fromisoformat(meeting_date_iso)
        except ValueError:
            return None
        day, month = map(int, match.groups())
        year = _infer_year_for_partial(month, day, meeting_date)
        return _safe_date(year, month, day)

    return None


# ====== Нормализация исполнителей ======


def _build_alias_index() -> dict[str, str]:
    """
    Строит индекс алиасов для быстрого поиска канонических имен.

    Returns:
        Словарь {alias_lower -> canonical_name_en}
    """
    index: dict[str, str] = {}

    for person in load_people():
        name_en = (person.get("name_en") or "").strip()
        if not name_en:
            continue

        # Добавляем каноническое имя
        index[name_en.lower()] = name_en

        # Добавляем все алиасы
        for alias in person.get("aliases", []):
            if alias and alias.strip():
                index[alias.strip().lower()] = name_en

    return index


def normalize_assignees(assignees: Iterable[str], attendees_en: Iterable[str]) -> list[str]:
    """
    Нормализует список исполнителей к каноническим английским именам.

    Args:
        assignees: Список исполнителей (может содержать алиасы)
        attendees_en: Список участников встречи (фильтр)

    Returns:
        Отфильтрованный и дедуплицированный список канонических имен

    Логика:
        1. Преобразует алиасы к каноническим именам через people.json
        2. Фильтрует людей, не участвовавших во встрече
        3. Удаляет дубликаты
    """
    alias_index = _build_alias_index()
    attendees_list = list(attendees_en) if attendees_en else []
    allowed_names = {name.lower() for name in attendees_list} if attendees_list else set()

    result: list[str] = []
    seen: set[str] = set()

    for assignee in assignees or []:
        if not assignee or not assignee.strip():
            continue

        key = assignee.strip().lower()
        canonical_name = alias_index.get(key)

        if not canonical_name:
            # Если не найден в индексе, пробуем использовать как есть с капитализацией
            canonical_name = assignee.strip().title()

        # Проверяем, что человек участвовал во встрече (только если есть список участников)
        if attendees_list and canonical_name.lower() not in allowed_names:
            continue

        # Дедупликация
        if canonical_name.lower() in seen:
            continue

        seen.add(canonical_name.lower())
        result.append(canonical_name)

    return result


# ====== Формирование title и key ======


def build_title(direction: str, text: str, assignees: list[str], due_iso: str | None) -> str:
    """
    Формирует заголовок коммита для отображения в Notion.

    Format: "{Owner}: {Text} [due {Date}]"
    """
    # Определяем владельца
    if assignees:
        owner = assignees[0]
    elif direction == "mine":
        owner = "Valentin"
    else:
        owner = "Unassigned"

    # Очищаем и обрезаем текст
    clean_text = text.strip().replace("\n", " ")[:80]

    # Добавляем дедлайн если есть
    suffix = f" [due {due_iso}]" if due_iso else ""

    return f"{owner}: {clean_text}{suffix}"


def build_key(text: str, assignees: list[str], due_iso: str | None) -> str:
    """
    Генерирует уникальный ключ для коммита для upsert операций.

    Ключ основан на нормализованном тексте, исполнителях и дедлайне.
    Это позволяет избежать дубликатов при повторной обработке.
    """
    # Нормализуем текст: lowercase, убираем лишние пробелы
    normalized_text = " ".join(text.lower().split())

    # Сортируем исполнителей для детерминированности
    normalized_assignees = ",".join(sorted(assignee.lower() for assignee in assignees))

    # Формируем payload для хеширования
    payload = f"{normalized_text}|{normalized_assignees}|{due_iso or ''}"

    return sha256(payload.encode("utf-8")).hexdigest()


# ====== Публичный интерфейс ======


@dataclass
class NormalizedCommit:
    """
    Нормализованный коммит, готовый для сохранения в Notion.

    Содержит все поля из ExtractedCommit плюс:
    - title: Заголовок для отображения
    - key: Уникальный ключ для upsert
    - tags: Теги (заполняются на уровне выше)
    """

    text: str
    direction: str
    assignees: list[str]
    due_iso: str | None
    confidence: float
    flags: list[str]
    context: str | None
    reasoning: str | None
    title: str
    key: str
    tags: list[str]  # заполняется позже в пайплайне
    status: str = "open"  # статус по умолчанию


def normalize_commits(
    commits: list[ExtractedCommit],
    attendees_en: list[str],
    meeting_date_iso: str,
    *,
    fill_mine_owner: str = "Valentin",
) -> list[NormalizedCommit]:
    """
    Нормализует список коммитов от LLM к формату для сохранения в Notion.

    Args:
        commits: Сырые коммиты от llm_extract_commits
        attendees_en: Список участников встречи (канонические EN имена)
        meeting_date_iso: Дата встречи в формате YYYY-MM-DD
        fill_mine_owner: Имя владельца для коммитов direction="mine" без assignees

    Returns:
        Список нормализованных коммитов с title, key и другими полями

    Обработка включает:
        1. Нормализацию исполнителей через people.json
        2. Парсинг дедлайнов из текста и контекста
        3. Генерацию заголовков и ключей
        4. Подстановку владельца для "mine" коммитов без исполнителей
    """
    result: list[NormalizedCommit] = []

    for commit in commits:
        # Нормализуем исполнителей
        normalized_assignees = normalize_assignees(commit.assignees, attendees_en)

        # Если это "мой" коммит без исполнителей - подставляем владельца
        if not normalized_assignees and commit.direction == "mine" and fill_mine_owner:
            normalized_assignees = [fill_mine_owner]

        # Парсим дедлайн из текста и контекста
        due = commit.due_iso or parse_due_iso(
            commit.text + " " + (commit.context or ""), meeting_date_iso
        )

        # Генерируем заголовок и ключ
        title = build_title(commit.direction, commit.text, normalized_assignees, due)
        key = build_key(commit.text, normalized_assignees, due)

        result.append(
            NormalizedCommit(
                text=commit.text,
                direction=commit.direction,
                assignees=normalized_assignees,
                due_iso=due,
                confidence=commit.confidence,
                flags=commit.flags or [],
                context=commit.context,
                reasoning=commit.reasoning,
                title=title,
                key=key,
                tags=[],  # будет заполнено на уровне выше при upsert
            )
        )

    return result


def as_dict_list(items: list[NormalizedCommit]) -> list[dict]:
    """
    Конвертирует список NormalizedCommit в список словарей для передачи в gateway.

    Используется для совместимости с notion_commits.upsert_commits().
    """
    return [asdict(item) for item in items]
