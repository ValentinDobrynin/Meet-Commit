"""
Декораторы для упрощения HTTP операций с автоматическим управлением клиентами.

Обеспечивает:
- Автоматическое управление lifecycle клиентов
- Единообразную обработку ошибок
- Логирование операций
- Метрики производительности
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from app.core.clients import get_notion_http_client
from app.core.metrics import timer

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def with_notion_client(operation_name: str | None = None):
    """
    Декоратор для автоматического управления Notion HTTP клиентом.

    Args:
        operation_name: Имя операции для метрик (опционально)

    Usage:
        @with_notion_client("fetch_meeting")
        def fetch_meeting_page(client, page_id: str) -> dict:
            response = client.get(f"/pages/{page_id}")
            return response.json()
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Определяем имя операции
            metric_name = operation_name or f"notion.{func.__name__}"

            with timer(metric_name):
                try:
                    # Используем context manager для правильного lifecycle
                    with get_notion_http_client() as client:
                        # Передаем клиент как первый аргумент
                        return func(client, *args, **kwargs)

                except Exception as e:
                    logger.error(f"Error in {func.__name__}: {e}")
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator


def with_graceful_fallback(fallback_value: Any = None):
    """
    Декоратор для graceful fallback при ошибках API.

    Args:
        fallback_value: Значение для возврата при ошибке

    Usage:
        @with_graceful_fallback([])
        def query_items() -> list:
            # ... API запрос
            pass
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Graceful fallback in {func.__name__}: {e}")
                return fallback_value

        return wrapper  # type: ignore[return-value]

    return decorator


def with_retry(max_attempts: int = 3, backoff_factor: float = 1.0):
    """
    Декоратор для повторных попыток при временных ошибках.

    Args:
        max_attempts: Максимальное количество попыток
        backoff_factor: Фактор увеличения задержки

    Usage:
        @with_retry(max_attempts=3)
        def api_call():
            # ... API запрос
            pass
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import time

            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Логируем попытку
                    if attempt < max_attempts - 1:
                        delay = backoff_factor * (2**attempt)
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_attempts} failed in {func.__name__}: {e}. "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_attempts} attempts failed in {func.__name__}")

            # Если все попытки неудачны, поднимаем последнее исключение
            if last_exception:
                raise last_exception
            else:
                raise RuntimeError(f"All {max_attempts} attempts failed in {func.__name__}")

        return wrapper  # type: ignore[return-value]

    return decorator


# Комбинированные декораторы для часто используемых паттернов


def notion_api_call(operation_name: str | None = None, fallback: Any = None):
    """
    Комбинированный декоратор для Notion API вызовов.

    Включает:
    - Автоматическое управление клиентом
    - Метрики производительности
    - Graceful fallback при необходимости

    Args:
        operation_name: Имя операции для метрик
        fallback: Значение fallback (если None, то исключения пробрасываются)

    Usage:
        @notion_api_call("query_commits", fallback=[])
        def query_commits(client, filter_: dict) -> list:
            response = client.post("/databases/query", json=filter_)
            return response.json()["results"]
    """

    def decorator(func: F) -> F:
        # Применяем декораторы в правильном порядке
        decorated = with_notion_client(operation_name)(func)

        if fallback is not None:
            decorated = with_graceful_fallback(fallback)(decorated)

        return decorated  # type: ignore[no-any-return]

    return decorator


def robust_notion_api_call(
    operation_name: str | None = None, fallback: Any = None, max_attempts: int = 2
):
    """
    Максимально надежный декоратор для критичных Notion API операций.

    Включает:
    - Автоматическое управление клиентом
    - Повторные попытки при временных ошибках
    - Graceful fallback
    - Детальные метрики

    Args:
        operation_name: Имя операции для метрик
        fallback: Значение fallback при всех неудачных попытках
        max_attempts: Максимальное количество попыток

    Usage:
        @robust_notion_api_call("critical_update", max_attempts=3)
        def update_critical_data(client, data: dict) -> bool:
            response = client.patch("/pages/id", json=data)
            return response.status_code == 200
    """

    def decorator(func: F) -> F:
        # Применяем декораторы в правильном порядке
        decorated = with_notion_client(operation_name)(func)
        decorated = with_retry(max_attempts)(decorated)

        if fallback is not None:
            decorated = with_graceful_fallback(fallback)(decorated)

        return decorated  # type: ignore[no-any-return]

    return decorator


# Примеры использования для рефакторинга существующего кода


def example_refactored_function():
    """
    Пример как можно рефакторить существующие функции.

    БЫЛО:
        def fetch_data(page_id: str):
            client = get_notion_http_client()
            try:
                response = client.get(f"/pages/{page_id}")
                return response.json()
            finally:
                client.close()

    СТАЛО:
        @notion_api_call("fetch_data")
        def fetch_data(client, page_id: str):
            response = client.get(f"/pages/{page_id}")
            return response.json()
    """
    pass


__all__ = [
    "with_notion_client",
    "with_graceful_fallback",
    "with_retry",
    "notion_api_call",
    "robust_notion_api_call",
]
