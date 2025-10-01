"""
Модуль дедупликации и объединения тегов v0/v1 с приоритетом v1.

Обеспечивает:
- Детерминированное объединение тегов с приоритетом v1
- Специальную обработку People/* тегов (сохранение всех уникальных)
- Стабильную сортировку по семействам тегов
- Детальные метрики процесса дедупликации
- Совместимость с существующей системой нормализации
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

# Порядок семейств тегов для детерминированной сортировки
FAMILIES = ("People/", "Business/", "Projects/", "Finance/", "Topic/")


def _family_priority(tag: str) -> int:
    """
    Определяет приоритет семейства тега для сортировки.

    Args:
        tag: Тег для анализа

    Returns:
        Числовой приоритет (меньше = выше приоритет)
    """
    for i, family in enumerate(FAMILIES):
        if tag.startswith(family):
            return i
    return len(FAMILIES)  # Неизвестные семейства в конец


class DedupMetrics:
    """Метрики процесса дедупликации тегов."""

    def __init__(self) -> None:
        # Входные данные
        self.total_v0 = 0
        self.total_v1 = 0

        # Результат
        self.unique_result = 0

        # Конфликты и разрешения
        self.conflicts_resolved = 0
        self.v1_priority_wins = 0
        self.v0_unique_kept = 0

        # Специальная обработка
        self.people_tags_preserved = 0

        # Производительность
        self.processing_time_ms = 0.0

    def as_dict(self) -> dict[str, Any]:
        """Возвращает метрики в виде словаря для логирования."""
        return {
            "input": {"v0_tags": self.total_v0, "v1_tags": self.total_v1},
            "output": {"unique_tags": self.unique_result},
            "conflicts": {"resolved": self.conflicts_resolved, "v1_wins": self.v1_priority_wins},
            "preserved": {
                "v0_unique": self.v0_unique_kept,
                "people_tags": self.people_tags_preserved,
            },
            "performance": {"processing_time_ms": round(self.processing_time_ms, 2)},
        }


def dedup_fuse(tags_v0: Iterable[str], tags_v1: Iterable[str]) -> tuple[list[str], DedupMetrics]:
    """
    Объединяет теги v0 и v1 с приоритетом v1 и специальной обработкой People/*.

    Алгоритм:
    1. Нормализация входных данных (фильтрация пустых строк)
    2. Разделение на обычные теги и People/* теги
    3. Дедупликация обычных тегов с приоритетом v1
    4. Сохранение всех уникальных People/* тегов
    5. Детерминированная сортировка по семействам

    Args:
        tags_v0: Теги от token-based тэггера
        tags_v1: Теги от regex-based тэггера (приоритет)

    Returns:
        Кортеж из финального списка тегов и метрик процесса
    """
    start_time = time.perf_counter()
    metrics = DedupMetrics()

    # Нормализуем входные данные - фильтруем пустые и невалидные, обрезаем пробелы
    v0_tags = [tag.strip() for tag in (tags_v0 or []) if isinstance(tag, str) and tag.strip()]
    v1_tags = [tag.strip() for tag in (tags_v1 or []) if isinstance(tag, str) and tag.strip()]

    metrics.total_v0 = len(v0_tags)
    metrics.total_v1 = len(v1_tags)

    # Импортируем существующую функцию нормализации для совместимости
    try:
        from app.core.tags import _normalize_for_comparison
    except ImportError:
        # Fallback если функция недоступна
        def _normalize_for_comparison(tag: str) -> str:
            return tag.lower().strip()

    # Индексы для дедупликации (исключая People/*)
    v0_index: dict[str, str] = {}
    v1_index: dict[str, str] = {}
    people_tags: set[str] = set()

    # Обрабатываем v1 теги (приоритет)
    for tag in v1_tags:
        if tag.startswith("People/"):
            people_tags.add(tag)
        else:
            normalized = _normalize_for_comparison(tag)
            v1_index[normalized] = tag

    # Обрабатываем v0 теги
    for tag in v0_tags:
        if tag.startswith("People/"):
            people_tags.add(tag)
        else:
            normalized = _normalize_for_comparison(tag)
            if normalized in v1_index:
                # Конфликт: v1 имеет приоритет
                metrics.conflicts_resolved += 1
                metrics.v1_priority_wins += 1
            else:
                # Уникальный v0 тег (не People/*)
                v0_index[normalized] = tag
                metrics.v0_unique_kept += 1

    # Собираем результат
    result_tags = list(v1_index.values()) + list(v0_index.values()) + sorted(people_tags)
    metrics.people_tags_preserved = len(people_tags)

    # Детерминированная сортировка по семействам, затем лексикографически
    result_tags.sort(key=lambda x: (_family_priority(x), x))

    metrics.unique_result = len(result_tags)
    metrics.processing_time_ms = (time.perf_counter() - start_time) * 1000

    return result_tags, metrics


def validate_tag_format(tag: str) -> bool:
    """
    Валидирует формат тега.

    Args:
        tag: Тег для проверки

    Returns:
        True если тег имеет правильный формат
    """
    if not isinstance(tag, str) or not tag.strip():
        return False

    # Проверяем формат Category/Subcategory
    parts = tag.split("/")
    if len(parts) != 2:
        return False

    category, subcategory = parts
    if not category.strip() or not subcategory.strip():
        return False

    # Проверяем, что категория из известных семейств
    known_categories = {family.rstrip("/") for family in FAMILIES}
    return category in known_categories


def get_tag_statistics(tags: list[str]) -> dict[str, Any]:
    """
    Возвращает статистику по тегам.

    Args:
        tags: Список тегов для анализа

    Returns:
        Словарь со статистикой
    """
    if not tags:
        return {"total": 0, "valid": 0, "invalid": 0, "by_family": {}}

    family_counts: dict[str, int] = {}
    invalid_count = 0

    for tag in tags:
        if not validate_tag_format(tag):
            invalid_count += 1
            continue

        family = tag.split("/")[0]
        family_counts[family] = family_counts.get(family, 0) + 1

    return {
        "total": len(tags),
        "valid": len(tags) - invalid_count,
        "invalid": invalid_count,
        "by_family": family_counts,
    }
