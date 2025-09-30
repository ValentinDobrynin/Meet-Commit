"""
People Miner v2: Улучшенная система управления кандидатами людей.

Основные возможности:
- Сбор кандидатов из текстов встреч с контекстом
- Система scoring на основе частоты, количества встреч и свежести
- Батч-операции для быстрой обработки
- Интеграция с существующим people_store.py

Архитектура:
- Совместимость с существующими системами
- Type safety через TypedDict
- Метрики и структурированное логирование
- Graceful error handling
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.core.metrics import MetricNames, inc, timer
from app.core.people_detect import mine_alias_candidates
from app.core.people_store import (
    load_people_raw,
    save_people_raw,
)
from app.core.types import CandidateData, CandidateListResult, CandidateStats
from app.gateways.error_handling import ErrorSeverity, with_error_handling

logger = logging.getLogger(__name__)

# Paths
DICT_DIR = Path(__file__).resolve().parent.parent / "dictionaries"
CANDIDATES_PATH = DICT_DIR / "people_candidates.json"

# Constants
DEFAULT_CONTEXT_LENGTH = 80
MAX_SAMPLES_PER_CANDIDATE = 5
RECENCY_BOOST_DAYS = 3
RECENCY_BOOST_SCORE = 2.0


def _load_candidates() -> dict[str, CandidateData]:
    """Загружает кандидатов из JSON файла."""
    if not CANDIDATES_PATH.exists():
        logger.debug(f"Candidates file {CANDIDATES_PATH} does not exist")
        return {}

    try:
        with open(CANDIDATES_PATH, encoding="utf-8") as f:
            data = json.load(f)

        # Валидируем и преобразуем данные
        validated_data: dict[str, CandidateData] = {}
        for alias, raw_data in data.items():
            if not isinstance(raw_data, dict):
                logger.warning(f"Invalid candidate data for {alias}: not a dict")
                continue

            # Преобразуем _meeting_ids из list обратно в set для работы
            if "_meeting_ids" in raw_data and isinstance(raw_data["_meeting_ids"], list):
                raw_data["_meeting_ids"] = set(raw_data["_meeting_ids"])

            validated_data[alias] = raw_data  # type: ignore[assignment]

        return validated_data

    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load candidates from {CANDIDATES_PATH}: {e}")
        return {}


def _save_candidates(data: dict[str, CandidateData]) -> None:
    """Сохраняет кандидатов в JSON файл."""
    try:
        # Подготавливаем данные для сериализации (set -> list)
        serializable_data = {}
        for alias, candidate in data.items():
            serializable_candidate = candidate.copy()
            if "_meeting_ids" in serializable_candidate:
                meeting_ids = serializable_candidate["_meeting_ids"]
                if isinstance(meeting_ids, set):
                    serializable_candidate["_meeting_ids"] = list(meeting_ids)  # type: ignore[typeddict-item]
            serializable_data[alias] = serializable_candidate

        CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
            json.dump(serializable_data, f, ensure_ascii=False, indent=2)

        logger.debug(f"Saved {len(data)} candidates to {CANDIDATES_PATH}")

    except OSError as e:
        logger.error(f"Failed to save candidates to {CANDIDATES_PATH}: {e}")
        raise


def _best_snippet(text: str, alias: str, context_length: int = DEFAULT_CONTEXT_LENGTH) -> str:
    """Извлекает лучший контекстный сниппет для алиаса."""
    # Ищем все вхождения алиаса (case insensitive)
    pattern = re.escape(alias)
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))

    if not matches:
        return ""

    # Берем первое вхождение (можно улучшить логику выбора)
    match = matches[0]
    start = max(0, match.start() - context_length)
    end = min(len(text), match.end() + context_length)

    snippet = text[start:end].strip()

    # Добавляем многоточия если текст обрезан
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""

    return f"{prefix}{snippet}{suffix}"


def _calculate_score(candidate: CandidateData) -> float:
    """Вычисляет score для ранжирования кандидата."""
    freq = candidate.get("freq", 0)
    meetings = candidate.get("meetings", 0)
    last_seen = candidate.get("last_seen", "1970-01-01")

    # Базовый score: частота + 0.5 * количество встреч
    base_score = freq + 0.5 * meetings

    # Бонус за свежесть
    recency_bonus = 0.0
    try:
        last_date = datetime.fromisoformat(last_seen).date()
        days_ago = (date.today() - last_date).days
        if days_ago <= RECENCY_BOOST_DAYS:
            recency_bonus = RECENCY_BOOST_SCORE
    except (ValueError, TypeError):
        pass  # Игнорируем некорректные даты

    return base_score + recency_bonus


def _is_known_person(alias: str) -> bool:
    """Проверяет, известен ли алиас в основном словаре людей."""
    people = load_people_raw()
    alias_lower = alias.lower()

    for person in people:
        # Проверяем каноническое имя
        name_en = person.get("name_en", "").lower()
        if name_en == alias_lower:
            return True

        # Проверяем алиасы
        aliases = person.get("aliases", [])
        if any(a.lower() == alias_lower for a in aliases):
            return True

    return False


def _is_valid_person_candidate(alias: str) -> bool:
    """Проверяет, является ли кандидат валидным именем человека."""
    alias_lower = alias.lower()

    # Исключаем очевидно неправильные кандидаты
    invalid_candidates = {
        "candidates",
        "участники",
        "встреча",
        "meeting",
        "проект",
        "project",
        "команда",
        "team",
        "отдел",
        "department",
        "компания",
        "company",
        "решение",
        "decision",
        "задача",
        "task",
        "вопрос",
        "question",
        "результат",
        "result",
        "отчет",
        "report",
        "план",
        "plan",
        "бюджет",
        "budget",
        "процесс",
        "process",
        "система",
        "system",
        "основные",
        "основных",
        "основной",
        "основная",
        "основное",
        "главные",
        "главных",
        "главный",
        "главная",
        "главное",
        "важные",
        "важных",
        "важный",
        "важная",
        "важное",
    }

    if alias_lower in invalid_candidates:
        logger.debug(f"Filtering out invalid candidate: {alias}")
        return False

    # Исключаем слишком короткие (меньше 2 символов)
    if len(alias) < 2:
        return False

    # Исключаем слишком длинные (больше 50 символов)
    if len(alias) > 50:
        return False

    return True


@with_error_handling("ingest_text", ErrorSeverity.MEDIUM, fallback=None)
def ingest_text(*, text: str, meeting_id: str, meeting_date: str) -> None:
    """
    Обрабатывает текст встречи и обновляет кандидатов.

    Args:
        text: Текст встречи для анализа
        meeting_id: Уникальный ID встречи
        meeting_date: Дата встречи в формате ISO (YYYY-MM-DD)
    """
    with timer(MetricNames.PEOPLE_MINER_INGEST):
        logger.info(f"Processing text for meeting {meeting_id} ({meeting_date})")

        # Извлекаем кандидатов из текста
        found_aliases = mine_alias_candidates(text, max_scan=min(20000, len(text)))
        logger.debug(f"Found {len(found_aliases)} potential aliases")

        if not found_aliases:
            return

        candidates = _load_candidates()
        updated_count = 0
        new_count = 0

        for alias in found_aliases:
            # Пропускаем уже известных людей
            if _is_known_person(alias):
                logger.debug(f"Skipping known person: {alias}")
                continue

            # Пропускаем невалидных кандидатов
            if not _is_valid_person_candidate(alias):
                logger.debug(f"Skipping invalid candidate: {alias}")
                continue

            # Получаем или создаем запись кандидата
            if alias in candidates:
                candidate = candidates[alias]
                updated_count += 1
            else:
                candidate = {
                    "first_seen": meeting_date,
                    "last_seen": meeting_date,
                    "freq": 0,
                    "meetings": 0,
                    "samples": [],
                    "_meeting_ids": set(),
                }
                new_count += 1

            # Обновляем статистику
            candidate["freq"] = candidate.get("freq", 0) + 1
            candidate["last_seen"] = max(candidate.get("last_seen", meeting_date), meeting_date)

            # Обновляем количество встреч
            meeting_ids_raw = candidate.get("_meeting_ids")
            if isinstance(meeting_ids_raw, set):
                meeting_ids = meeting_ids_raw
            else:
                # Может быть list после десериализации или None
                meeting_ids = set(meeting_ids_raw or [])

            if meeting_id not in meeting_ids:
                meeting_ids.add(meeting_id)
                candidate["meetings"] = len(meeting_ids)

            candidate["_meeting_ids"] = meeting_ids

            # Добавляем контекстный сниппет
            snippet = _best_snippet(text, alias)
            if snippet:
                samples = candidate.get("samples", [])
                samples.append({"meeting_id": meeting_id, "date": meeting_date, "snippet": snippet})
                # Оставляем только последние N сниппетов
                candidate["samples"] = samples[-MAX_SAMPLES_PER_CANDIDATE:]

            candidates[alias] = candidate

        # Сохраняем обновленных кандидатов
        _save_candidates(candidates)

        logger.info(
            f"Processed {len(found_aliases)} aliases: {new_count} new, {updated_count} updated"
        )
        inc(MetricNames.PEOPLE_MINER_CANDIDATES_ADDED, new_count)
        inc(MetricNames.PEOPLE_MINER_CANDIDATES_UPDATED, updated_count)


@with_error_handling("list_candidates", ErrorSeverity.LOW, fallback=([], 0))
def list_candidates(
    *, sort: str = "freq", page: int = 1, per_page: int = 10
) -> CandidateListResult:
    """
    Возвращает отсортированный список кандидатов с пагинацией.

    Args:
        sort: Тип сортировки ("freq" или "date")
        page: Номер страницы (начиная с 1)
        per_page: Количество элементов на странице

    Returns:
        Tuple (список кандидатов, общее количество)
    """
    with timer(MetricNames.PEOPLE_MINER_LIST):
        data = _load_candidates()

        # Преобразуем в список с вычисленным score
        items = []
        for alias, candidate_data in data.items():
            score = _calculate_score(candidate_data)

            item: dict[str, Any] = {
                "alias": alias,
                "freq": candidate_data.get("freq", 0),
                "meetings": candidate_data.get("meetings", 0),
                "first_seen": candidate_data.get("first_seen", ""),
                "last_seen": candidate_data.get("last_seen", ""),
                "score": score,
                "samples": candidate_data.get("samples", []),
            }
            items.append(item)

        # Сортировка
        if sort == "date":
            items.sort(key=lambda x: str(x.get("last_seen", "")), reverse=True)
        else:  # freq
            items.sort(key=lambda x: float(x["score"]), reverse=True)

        total = len(items)

        # Пагинация
        start = max(0, (page - 1) * per_page)
        end = start + per_page
        page_items = items[start:end]

        logger.debug(f"Listed {len(page_items)}/{total} candidates (page {page}, sort={sort})")
        return page_items, total  # type: ignore[return-value]


@with_error_handling("approve_candidate", ErrorSeverity.MEDIUM, fallback=False)
def approve_candidate(alias: str, *, name_en: str | None = None) -> bool:
    """
    Одобряет кандидата и добавляет в основной словарь людей.

    Args:
        alias: Алиас кандидата
        name_en: Каноническое английское имя (если None, будет сгенерировано)

    Returns:
        True если кандидат успешно добавлен
    """
    with timer(MetricNames.PEOPLE_MINER_APPROVE):
        alias = alias.strip()
        if not alias:
            return False

        logger.info(f"Approving candidate: {alias}")

        # Загружаем людей
        people = load_people_raw()

        # Проверяем, не является ли уже известным
        alias_lower = alias.lower()
        for person in people:
            existing_aliases = [a.lower() for a in person.get("aliases", [])]
            if alias_lower in existing_aliases:
                logger.info(f"Alias {alias} already exists for {person.get('name_en')}")
                _remove_candidate(alias)
                return True

        # Генерируем каноническое имя если не указано
        if not name_en:
            from app.core.people_detect import propose_name_en

            name_en = propose_name_en(alias)

        # Ищем существующую запись с таким name_en
        for person in people:
            if person.get("name_en", "").lower() == name_en.lower():
                # Расширяем алиасы
                aliases = list(dict.fromkeys([*person.get("aliases", []), alias]))
                person["aliases"] = aliases
                logger.info(f"Extended aliases for {name_en}: added {alias}")
                save_people_raw(people)
                _remove_candidate(alias)
                inc(MetricNames.PEOPLE_MINER_APPROVED)
                return True

        # Создаем новую запись
        people.append(
            {
                "name_en": name_en,
                "aliases": [alias],
                "meta": {"created_at": datetime.now().isoformat(), "source": "people_miner_v2"},
            }
        )

        save_people_raw(people)
        _remove_candidate(alias)

        logger.info(f"Created new person: {name_en} with alias {alias}")
        inc(MetricNames.PEOPLE_MINER_APPROVED)
        return True


@with_error_handling("reject_candidate", ErrorSeverity.LOW, fallback=False)
def reject_candidate(alias: str) -> bool:
    """
    Отклоняет кандидата (удаляет из списка).

    Args:
        alias: Алиас кандидата

    Returns:
        True если кандидат был найден и удален
    """
    success = _remove_candidate(alias)
    if success:
        inc(MetricNames.PEOPLE_MINER_REJECTED)
        logger.info(f"Rejected candidate: {alias}")
    return success


def _remove_candidate(alias: str) -> bool:
    """Удаляет кандидата из списка."""
    data = _load_candidates()
    if alias in data:
        del data[alias]
        _save_candidates(data)
        return True
    return False


@with_error_handling(
    "approve_batch", ErrorSeverity.MEDIUM, fallback={"selected": 0, "added": 0, "total": 0}
)
def approve_batch(top_n: int = 5, sort: str = "freq") -> dict[str, int]:
    """
    Одобряет топ-N кандидатов батчем.

    Args:
        top_n: Количество кандидатов для одобрения
        sort: Тип сортировки для выбора топа

    Returns:
        Статистика операции
    """
    with timer(MetricNames.PEOPLE_MINER_BATCH_APPROVE):
        page_items, total = list_candidates(sort=sort, page=1, per_page=top_n)

        added = 0
        for item in page_items:
            if approve_candidate(item["alias"]):
                added += 1

        logger.info(f"Batch approved: {added}/{len(page_items)} candidates")
        return {"selected": len(page_items), "added": added, "total": total}


@with_error_handling(
    "reject_batch", ErrorSeverity.LOW, fallback={"selected": 0, "removed": 0, "total": 0}
)
def reject_batch(top_n: int = 5, sort: str = "freq") -> dict[str, int]:
    """
    Отклоняет топ-N кандидатов батчем.

    Args:
        top_n: Количество кандидатов для отклонения
        sort: Тип сортировки для выбора топа

    Returns:
        Статистика операции
    """
    with timer(MetricNames.PEOPLE_MINER_BATCH_REJECT):
        page_items, total = list_candidates(sort=sort, page=1, per_page=top_n)

        removed = 0
        for item in page_items:
            if reject_candidate(item["alias"]):
                removed += 1

        logger.info(f"Batch rejected: {removed}/{len(page_items)} candidates")
        return {"selected": len(page_items), "removed": removed, "total": total}


@with_error_handling("get_candidate_stats", ErrorSeverity.LOW, fallback={})
def get_candidate_stats() -> CandidateStats:
    """Возвращает статистику кандидатов."""
    data = _load_candidates()

    if not data:
        return {
            "total": 0,
            "avg_freq": 0.0,
            "avg_meetings": 0.0,
            "freq_distribution": {"high": 0, "medium": 0, "low": 0},
            "recent_candidates": 0,
        }

    frequencies = [c.get("freq", 0) for c in data.values()]
    meetings = [c.get("meetings", 0) for c in data.values()]

    # Подсчитываем недавних кандидатов
    recent_count = 0
    cutoff_date = date.today().toordinal() - RECENCY_BOOST_DAYS

    for candidate in data.values():
        try:
            last_seen = candidate.get("last_seen", "1970-01-01")
            candidate_date = datetime.fromisoformat(last_seen).date()
            if candidate_date.toordinal() >= cutoff_date:
                recent_count += 1
        except (ValueError, TypeError):
            pass

    # Распределение по частоте
    freq_dist = {
        "high": len([f for f in frequencies if f >= 5]),
        "medium": len([f for f in frequencies if 2 <= f < 5]),
        "low": len([f for f in frequencies if f < 2]),
    }

    return {
        "total": len(data),
        "avg_freq": sum(frequencies) / len(frequencies),
        "avg_meetings": sum(meetings) / len(meetings),
        "freq_distribution": freq_dist,
        "recent_candidates": recent_count,
    }


def clear_candidates() -> None:
    """Очищает всех кандидатов (для тестирования)."""
    _save_candidates({})
    logger.info("Cleared all candidates")
