"""
Централизованная логика управления Review Queue.

Этот модуль обеспечивает:
- Фильтрацию открытых записей (исключение resolved/dropped)
- Дедупликацию при повторной загрузке транскриптов
- Статистику и мониторинг Review Queue
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.constants import REVIEW_STATUS_PENDING
from app.gateways.notion_review import list_pending as _list_pending_raw

logger = logging.getLogger(__name__)

# Открытые статусы для Review Queue
OPEN_STATUSES = {"pending", "needs-review"}
CLOSED_STATUSES = {"resolved", "dropped"}


def list_open_reviews(limit: int = 5) -> list[dict[str, Any]]:
    """
    Возвращает список открытых элементов Review Queue.

    Фильтрует только записи со статусом 'pending' или 'needs-review',
    исключая resolved/dropped элементы.

    Args:
        limit: Максимальное количество элементов

    Returns:
        Список открытых Review элементов
    """
    try:
        # Используем обновленный list_pending из gateway
        items = _list_pending_raw(limit)

        # Дополнительная фильтрация на уровне приложения
        open_items = [item for item in items if _get_item_status(item) in OPEN_STATUSES]

        logger.info(f"Listed {len(open_items)} open reviews (filtered from {len(items)} total)")
        return open_items

    except Exception as e:
        logger.error(f"Error listing open reviews: {e}")
        return []


def _get_item_status(item: dict[str, Any]) -> str:
    """Извлекает статус из Review элемента."""
    status = item.get("status", REVIEW_STATUS_PENDING)
    return str(status) if status is not None else REVIEW_STATUS_PENDING


def is_review_closed(status: str) -> bool:
    """
    Проверяет, является ли Review запись закрытой.

    Args:
        status: Статус Review записи

    Returns:
        True если запись закрыта (resolved/dropped)
    """
    return status in CLOSED_STATUSES


def should_skip_duplicate(key: str, existing_reviews: list[dict[str, Any]]) -> bool:
    """
    Проверяет, нужно ли пропустить создание Review записи из-за дубликата.

    Пропускаем если уже есть запись с тем же ключом, которая НЕ закрыта.

    Args:
        key: Ключ новой записи
        existing_reviews: Список существующих открытых записей

    Returns:
        True если нужно пропустить создание
    """
    for review in existing_reviews:
        if review.get("key") == key:
            status = _get_item_status(review)
            if not is_review_closed(status):
                logger.debug(f"Skipping duplicate review with key: {key}")
                return True

    return False


def get_review_stats() -> dict[str, Any]:
    """
    Возвращает статистику Review Queue.

    Returns:
        Словарь со статистикой
    """
    try:
        # Получаем все открытые записи без лимита
        open_reviews = list_open_reviews(limit=100)

        # Группируем по статусам
        status_counts: dict[str, int] = {}
        for review in open_reviews:
            status = _get_item_status(review)
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "total_open": len(open_reviews),
            "status_breakdown": status_counts,
            "open_statuses": list(OPEN_STATUSES),
            "closed_statuses": list(CLOSED_STATUSES),
        }

    except Exception as e:
        logger.error(f"Error getting review stats: {e}")
        return {"total_open": 0, "status_breakdown": {}, "error": str(e)}


def validate_review_action(review_item: dict[str, Any], action: str) -> tuple[bool, str]:
    """
    Валидирует возможность выполнения действия над Review записью.

    Args:
        review_item: Данные Review записи
        action: Действие (confirm, delete, flip, assign)

    Returns:
        Tuple (is_valid, error_message)
    """
    if not review_item:
        return False, "Review запись не найдена"

    status = _get_item_status(review_item)

    # Проверяем, что запись не закрыта
    if is_review_closed(status):
        return False, f"Действие '{action}' недоступно для закрытой записи (статус: {status})"

    # Специфичные проверки для действий
    if action == "confirm":
        text = review_item.get("text", "").strip()
        if not text:
            return False, "Нельзя подтвердить запись без текста"

        direction = review_item.get("direction")
        if direction not in {"mine", "theirs"}:
            return False, f"Некорректное направление: {direction}"

    return True, ""


# Константы для экспорта
__all__ = [
    "list_open_reviews",
    "is_review_closed",
    "should_skip_duplicate",
    "get_review_stats",
    "validate_review_action",
    "OPEN_STATUSES",
    "CLOSED_STATUSES",
]
