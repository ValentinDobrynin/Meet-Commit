"""
Единые клиенты для внешних API.

Модуль обеспечивает централизованное создание и управление клиентами
для всех внешних сервисов: Notion API, OpenAI API.

Преимущества:
- Единые настройки timeout'ов и connection limits
- Централизованное управление версиями API
- Кэширование клиентов для оптимизации
- Легкость изменения конфигурации
"""

from __future__ import annotations

import logging
from functools import lru_cache

import httpx
from notion_client import Client as NotionClient
from openai import AsyncOpenAI, OpenAI

# from app.core.smart_caching import get_client_manager, lru_cache_with_ttl  # Отключено из-за проблем с lifecycle
from app.core.types import ClientsInfo, NotionConfig, OpenAIConfig
from app.settings import settings

logger = logging.getLogger(__name__)

# Константы конфигурации
DEFAULT_TIMEOUT = 30.0
OPENAI_READ_TIMEOUT = 240.0  # 4 минуты для больших LLM ответов
OPENAI_PARSE_TIMEOUT = 60.0  # 1 минута для парсинга
NOTION_API_VERSION = "2022-06-28"
MAX_KEEPALIVE_CONNECTIONS = 10
MAX_CONNECTIONS = 20


class ClientError(Exception):
    """Базовое исключение для ошибок клиентов."""

    pass


class NotionClientError(ClientError):
    """Ошибки Notion клиента."""

    pass


class OpenAIClientError(ClientError):
    """Ошибки OpenAI клиента."""

    pass


# =============== NOTION CLIENTS ===============


@lru_cache(maxsize=1)
def get_notion_client() -> NotionClient:
    """
    Единый официальный Notion клиент для всего проекта.

    Использует notion-client SDK с автоматическим управлением соединениями.
    Рекомендуется для большинства операций.

    Returns:
        Notion SDK клиент с настроенной авторизацией

    Raises:
        NotionClientError: Если токен не настроен
    """
    if not settings.notion_token:
        raise NotionClientError("NOTION_TOKEN не настроен в переменных окружения")

    logger.debug("Creating cached Notion SDK client")
    return NotionClient(auth=settings.notion_token)


def _create_notion_http_client() -> httpx.Client:
    """
    Создает новый HTTP клиент для Notion API.

    Внутренняя функция для создания клиентов. Используется кэшированной версией.
    """
    if not settings.notion_token:
        raise NotionClientError("NOTION_TOKEN не настроен в переменных окружения")

    headers = {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(
        connect=10.0,
        read=DEFAULT_TIMEOUT,
        write=10.0,
        pool=5.0,
    )

    # Улучшенные лимиты для production
    limits = httpx.Limits(
        max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS * 2,  # Больше keep-alive соединений
        max_connections=MAX_CONNECTIONS * 2,  # Больше общих соединений
        keepalive_expiry=300.0,  # 5 минут keep-alive
    )

    logger.debug(f"Creating new Notion HTTP client with timeout={DEFAULT_TIMEOUT}s")
    return httpx.Client(timeout=timeout, headers=headers, limits=limits)


def get_notion_http_client() -> httpx.Client:
    """
    HTTP клиент для прямых вызовов Notion API с оптимизированным connection pooling.

    ВАЖНО: HTTP клиенты НЕ кэшируются из-за проблем с lifecycle (нельзя переиспользовать закрытые клиенты).
    Вместо этого используется улучшенный connection pooling для переиспользования TCP соединений.

    Используется когда нужен прямой контроль над HTTP запросами
    или когда notion-client SDK не подходит.

    Оптимизации:
    - Connection pooling: переиспользование TCP соединений
    - Keep-alive: 5 минут для соединений
    - Увеличенные лимиты: готовность к production нагрузкам
    - Правильный lifecycle: каждый клиент создается и закрывается корректно

    Returns:
        Новый httpx.Client с оптимизированными настройками

    Raises:
        NotionClientError: Если токен не настроен
    """
    return _create_notion_http_client()


# =============== OPENAI CLIENTS ===============


def get_openai_client(*, timeout: float | None = None) -> OpenAI:
    """
    Синхронный OpenAI клиент для блокирующих операций.

    Args:
        timeout: Timeout для чтения (по умолчанию 240s для LLM)

    Returns:
        Настроенный синхронный OpenAI клиент

    Raises:
        OpenAIClientError: Если API ключ не настроен
    """
    if not settings.openai_api_key:
        raise OpenAIClientError("OPENAI_API_KEY не настроен в переменных окружения")

    read_timeout = timeout or OPENAI_READ_TIMEOUT

    http_timeout = httpx.Timeout(
        connect=10.0,
        read=read_timeout,
        write=10.0,
        pool=5.0,
    )

    http_limits = httpx.Limits(
        max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
        max_connections=MAX_CONNECTIONS,
    )

    http_client = httpx.Client(timeout=http_timeout, limits=http_limits)

    logger.debug(f"Creating cached OpenAI sync client with read_timeout={read_timeout}s")
    return OpenAI(api_key=settings.openai_api_key, http_client=http_client)


def get_openai_parse_client() -> OpenAI:
    """
    Специализированный OpenAI клиент для быстрого парсинга.

    Оптимизирован для коротких запросов типа commit parsing
    с уменьшенным timeout'ом.

    Returns:
        OpenAI клиент с коротким timeout'ом для парсинга
    """
    return get_openai_client(timeout=OPENAI_PARSE_TIMEOUT)


async def get_async_openai_client(*, timeout: float | None = None) -> AsyncOpenAI:
    """
    Асинхронный OpenAI клиент для неблокирующих операций.

    Args:
        timeout: Timeout для чтения (по умолчанию 240s для LLM)

    Returns:
        Настроенный асинхронный OpenAI клиент

    Raises:
        OpenAIClientError: Если API ключ не настроен
    """
    if not settings.openai_api_key:
        raise OpenAIClientError("OPENAI_API_KEY не настроен в переменных окружения")

    read_timeout = timeout or OPENAI_READ_TIMEOUT

    http_timeout = httpx.Timeout(
        connect=10.0,
        read=read_timeout,
        write=10.0,
        pool=5.0,
    )

    http_limits = httpx.Limits(
        max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
        max_connections=MAX_CONNECTIONS,
    )

    http_client = httpx.AsyncClient(timeout=http_timeout, limits=http_limits)

    logger.debug(f"Creating async OpenAI client with read_timeout={read_timeout}s")
    return AsyncOpenAI(api_key=settings.openai_api_key, http_client=http_client)


# =============== UTILITY FUNCTIONS ===============


def validate_notion_config() -> NotionConfig:
    """
    Валидирует конфигурацию Notion.

    Returns:
        Словарь с информацией о конфигурации
    """
    config = {
        "token_configured": bool(settings.notion_token),
        "meetings_db_configured": bool(settings.notion_db_meetings_id),
        "commits_db_configured": bool(settings.commits_db_id),
        "review_db_configured": bool(settings.review_db_id),
        "agendas_db_configured": bool(settings.agendas_db_id),
        "api_version": NOTION_API_VERSION,
        "timeout": DEFAULT_TIMEOUT,
    }

    missing_configs = [
        key for key, value in config.items() if key.endswith("_configured") and not value
    ]
    config["missing_configs"] = missing_configs
    config["ready"] = len(missing_configs) == 0

    return config  # type: ignore[return-value]


def validate_openai_config() -> OpenAIConfig:
    """
    Валидирует конфигурацию OpenAI.

    Returns:
        Словарь с информацией о конфигурации
    """
    return {
        "api_key_configured": bool(settings.openai_api_key),
        "default_model": settings.summarize_model,
        "default_temperature": settings.summarize_temperature,
        "default_timeout": OPENAI_READ_TIMEOUT,
        "parse_timeout": OPENAI_PARSE_TIMEOUT,
        "ready": bool(settings.openai_api_key),
    }


def get_clients_info() -> ClientsInfo:
    """
    Возвращает информацию о всех клиентах для диагностики.

    Returns:
        Полная информация о конфигурации клиентов
    """
    return {
        "notion": validate_notion_config(),
        "openai": validate_openai_config(),
        "cache_info": {
            "notion_client": get_notion_client.cache_info(),
            "notion_http_client": "not_cached_due_to_lifecycle_issues",  # Не кэшируется из-за проблем с lifecycle
            "openai_client": "not_cached",  # OpenAI клиенты не кэшируются
            "openai_parse_client": "not_cached",  # OpenAI клиенты не кэшируются
        },
    }


def clear_clients_cache() -> None:
    """
    Очищает кэш клиентов.

    Полезно для принудительного пересоздания клиентов
    после изменения конфигурации.
    """
    logger.info("Clearing clients cache")
    get_notion_client.cache_clear()
    # HTTP клиенты теперь не кэшируются из-за проблем с lifecycle
    # Каждый вызов создает новый клиент, что безопаснее
