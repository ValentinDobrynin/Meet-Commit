"""
Унифицированная система обработки ошибок для gateway слоя.

Обеспечивает:
- Консистентную обработку HTTP ошибок
- Правильное логирование с контекстом
- Graceful fallback стратегии
- Метрики ошибок
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

import httpx

from app.core.metrics import inc

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class ErrorSeverity(Enum):
    """Уровни серьезности ошибок."""

    LOW = "low"  # Логируем как warning, возвращаем fallback
    MEDIUM = "medium"  # Логируем как error, возвращаем fallback
    HIGH = "high"  # Логируем как error, пробрасываем исключение
    CRITICAL = "critical"  # Логируем как critical, пробрасываем исключение


class NotionAPIError(Exception):
    """Базовое исключение для ошибок Notion API."""

    def __init__(
        self, message: str, status_code: int | None = None, response_text: str | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class NotionAccessError(NotionAPIError):
    """Ошибки доступа к Notion (401, 403, 404)."""

    pass


class NotionRateLimitError(NotionAPIError):
    """Ошибки превышения лимитов API (429)."""

    pass


class NotionServerError(NotionAPIError):
    """Серверные ошибки Notion (5xx)."""

    pass


def classify_http_error(response: httpx.Response) -> type[NotionAPIError]:
    """
    Классифицирует HTTP ошибку по статус коду.

    Args:
        response: HTTP ответ с ошибкой

    Returns:
        Класс исключения для данного типа ошибки
    """
    status_code = response.status_code

    if status_code in {401, 403, 404}:
        return NotionAccessError
    elif status_code == 429:
        return NotionRateLimitError
    elif 500 <= status_code < 600:
        return NotionServerError
    else:
        return NotionAPIError


def handle_http_error(
    response: httpx.Response, operation: str, severity: ErrorSeverity = ErrorSeverity.HIGH
) -> None:
    """
    Обрабатывает HTTP ошибку с правильной классификацией и логированием.

    Args:
        response: HTTP ответ с ошибкой
        operation: Название операции для контекста
        severity: Уровень серьезности ошибки

    Raises:
        NotionAPIError: Соответствующий тип исключения
    """
    status_code = response.status_code
    response_text = response.text[:500]  # Ограничиваем размер для логов

    # Создаем специфичное исключение
    error_class = classify_http_error(response)
    error_message = f"{operation} failed: HTTP {status_code}"
    error = error_class(error_message, status_code, response_text)

    # Логируем в зависимости от серьезности
    log_message = f"{error_message}. Response: {response_text}"

    if severity == ErrorSeverity.LOW:
        logger.warning(log_message)
    elif severity == ErrorSeverity.MEDIUM:
        logger.error(log_message)
    elif severity == ErrorSeverity.HIGH:
        logger.error(log_message, exc_info=True)
    else:  # CRITICAL
        logger.critical(log_message, exc_info=True)

    # Обновляем метрики ошибок
    inc(f"notion.errors.{status_code}")
    inc(f"notion.errors.{operation}")

    raise error


_NO_FALLBACK = object()  # Sentinel value для отличия None от отсутствия fallback


def with_error_handling(
    operation: str, severity: ErrorSeverity = ErrorSeverity.HIGH, fallback: Any = _NO_FALLBACK
):
    """
    Декоратор для унифицированной обработки ошибок в gateway функциях.

    Args:
        operation: Название операции для логирования
        severity: Уровень серьезности ошибок
        fallback: Значение для возврата при ошибках (если указано, включая None)

    Usage:
        @with_error_handling("fetch_meeting", ErrorSeverity.HIGH)
        def fetch_meeting_page(page_id: str) -> dict:
            # ... код функции
            pass
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)

            except httpx.HTTPStatusError as e:
                # HTTP ошибки обрабатываем специально
                handle_http_error(e.response, operation, severity)

            except httpx.RequestError as e:
                # Сетевые ошибки
                logger.error(f"Network error in {operation}: {e}")
                inc(f"notion.errors.network.{operation}")

                if fallback is not _NO_FALLBACK and severity in {
                    ErrorSeverity.LOW,
                    ErrorSeverity.MEDIUM,
                }:
                    return fallback
                raise NotionAPIError(f"Network error in {operation}: {e}") from e

            except Exception as e:
                # Все остальные ошибки
                log_message = f"Unexpected error in {operation}: {e}"

                if severity == ErrorSeverity.LOW:
                    logger.warning(log_message)
                else:
                    logger.error(log_message, exc_info=True)

                inc(f"notion.errors.unexpected.{operation}")

                if fallback is not _NO_FALLBACK and severity in {
                    ErrorSeverity.LOW,
                    ErrorSeverity.MEDIUM,
                }:
                    return fallback
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


# Готовые декораторы для типичных случаев


def notion_query(operation_name: str, fallback: Any = "DEFAULT"):
    """Декоратор для запросов к Notion (с настраиваемым fallback)."""
    if fallback == "DEFAULT":
        fallback = {"results": []}
    return with_error_handling(operation_name, ErrorSeverity.MEDIUM, fallback=fallback)


def notion_update(operation_name: str):
    """Декоратор для обновлений в Notion (строгая обработка ошибок)."""
    return with_error_handling(operation_name, ErrorSeverity.HIGH)


def notion_create(operation_name: str):
    """Декоратор для создания в Notion (строгая обработка ошибок)."""
    return with_error_handling(operation_name, ErrorSeverity.HIGH)


def notion_validation(operation_name: str):
    """Декоратор для валидации доступа (с fallback на False)."""
    return with_error_handling(operation_name, ErrorSeverity.LOW, fallback=False)


# Пример рефакторинга существующей функции


def example_refactored_gateway_function():
    """
    Пример рефакторинга gateway функции с новыми декораторами.

    БЫЛО:
        def fetch_meeting_page(page_id: str) -> dict[str, Any]:
            client = get_notion_http_client()
            try:
                response = client.get(f"/pages/{page_id}")
                if response.status_code != 200:
                    raise RuntimeError(f"API error {response.status_code}: {response.text}")
                return response.json()
            except Exception as e:
                logger.error(f"Error fetching meeting: {e}")
                raise RuntimeError(f"Failed to fetch meeting: {e}") from e
            finally:
                client.close()

    СТАЛО:
        @notion_api_call("fetch_meeting")
        def fetch_meeting_page(client, page_id: str) -> dict[str, Any]:
            response = client.get(f"/pages/{page_id}")
            response.raise_for_status()  # Автоматическая обработка ошибок
            return response.json()
    """
    pass


__all__ = [
    "ErrorSeverity",
    "NotionAPIError",
    "NotionAccessError",
    "NotionRateLimitError",
    "NotionServerError",
    # "with_notion_client",  # Определен в http_decorators
    "with_error_handling",
    "notion_query",
    "notion_update",
    "notion_create",
    "notion_validation",
    "handle_http_error",
]
