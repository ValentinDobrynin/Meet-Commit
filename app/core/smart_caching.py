"""
Умное кэширование с TTL для HTTP клиентов.

Обеспечивает:
- Автоматическую очистку просроченных клиентов
- Переиспользование соединений
- Мониторинг производительности кэша
- Graceful shutdown при завершении приложения
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class CacheEntry:
    """Запись в кэше с TTL."""

    value: Any
    created_at: float
    last_accessed: float
    access_count: int = 0

    def is_expired(self, ttl_seconds: float) -> bool:
        """Проверяет истек ли TTL."""
        return time.time() - self.created_at > ttl_seconds

    def touch(self) -> None:
        """Обновляет время последнего доступа."""
        self.last_accessed = time.time()
        self.access_count += 1


class TTLCache:
    """Кэш с автоматической очисткой по TTL."""

    def __init__(self, maxsize: int = 128, ttl_seconds: float = 300.0):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

        # Регистрируем очистку при завершении
        atexit.register(self.clear)

    def get(self, key: str) -> Any | None:
        """Получает значение из кэша."""
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired(self.ttl_seconds):
                # Удаляем просроченную запись
                del self._cache[key]
                self._misses += 1
                logger.debug(f"Cache entry expired and removed: {key}")
                return None

            # Обновляем статистику доступа
            entry.touch()
            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any) -> None:
        """Сохраняет значение в кэш."""
        with self._lock:
            # Проверяем лимит размера
            if len(self._cache) >= self.maxsize:
                self._evict_lru()

            # Создаем новую запись
            now = time.time()
            self._cache[key] = CacheEntry(
                value=value, created_at=now, last_accessed=now, access_count=1
            )
            logger.debug(f"Cache entry created: {key}")

    def _evict_lru(self) -> None:
        """Удаляет наименее недавно использованную запись."""
        if not self._cache:
            return

        # Находим запись с наименьшим last_accessed
        lru_key = min(self._cache.keys(), key=lambda k: self._cache[k].last_accessed)
        del self._cache[lru_key]
        logger.debug(f"Cache LRU eviction: {lru_key}")

    def cleanup_expired(self) -> int:
        """Очищает все просроченные записи. Возвращает количество удаленных."""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() if entry.is_expired(self.ttl_seconds)
            ]

            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)

    def clear(self) -> None:
        """Очищает весь кэш."""
        with self._lock:
            # Закрываем все HTTP клиенты если они есть
            for entry in self._cache.values():
                if hasattr(entry.value, "close"):
                    try:
                        entry.value.close()
                    except Exception as e:
                        logger.warning(f"Error closing cached client: {e}")

            self._cache.clear()
            logger.info("Cache cleared")

    def stats(self) -> dict[str, Any]:
        """Возвращает статистику кэша."""
        with self._lock:
            total_accesses = self._hits + self._misses
            hit_ratio = (self._hits / total_accesses) if total_accesses > 0 else 0.0

            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": hit_ratio,
                "ttl_seconds": self.ttl_seconds,
                "entries": [
                    {
                        "key": key,
                        "age_seconds": time.time() - entry.created_at,
                        "access_count": entry.access_count,
                        "expires_in": self.ttl_seconds - (time.time() - entry.created_at),
                    }
                    for key, entry in self._cache.items()
                ],
            }


def lru_cache_with_ttl(maxsize: int = 128, ttl_seconds: float = 300.0):
    """
    Декоратор для кэширования с TTL и LRU eviction.

    Args:
        maxsize: Максимальный размер кэша
        ttl_seconds: Время жизни записей в секундах

    Returns:
        Декорированная функция с TTL кэшем
    """

    def decorator(func: F) -> F:
        cache = TTLCache(maxsize=maxsize, ttl_seconds=ttl_seconds)

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Создаем ключ из аргументов
            key = _make_cache_key(func.__name__, args, kwargs)

            # Пытаемся получить из кэша
            cached_value = cache.get(key)
            if cached_value is not None:
                return cached_value

            # Вычисляем значение
            result = func(*args, **kwargs)

            # Сохраняем в кэш
            cache.set(key, result)

            return result

        # Добавляем методы для управления кэшем
        wrapper.cache_info = cache.stats  # type: ignore[attr-defined]
        wrapper.cache_clear = cache.clear  # type: ignore[attr-defined]
        wrapper.cleanup_expired = cache.cleanup_expired  # type: ignore[attr-defined]

        return wrapper  # type: ignore[return-value]

    return decorator


def _make_cache_key(func_name: str, args: tuple, kwargs: dict) -> str:
    """Создает ключ кэша из аргументов функции."""
    # Простая реализация - для HTTP клиентов аргументы обычно одинаковые
    key_parts = [func_name]

    # Добавляем значимые аргументы
    for arg in args:
        if isinstance(arg, str | int | float | bool):
            key_parts.append(str(arg))

    for k, v in sorted(kwargs.items()):
        if isinstance(v, str | int | float | bool):
            key_parts.append(f"{k}={v}")

    return "|".join(key_parts)


class ClientManager:
    """
    Менеджер для автоматического управления жизненным циклом HTTP клиентов.

    Обеспечивает:
    - Умное кэширование клиентов
    - Автоматическую очистку просроченных клиентов
    - Connection pooling
    - Мониторинг производительности
    """

    def __init__(self):
        self._client_cache = TTLCache(maxsize=5, ttl_seconds=300.0)  # 5 минут
        self._cleanup_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
        self._start_background_cleanup()

    def _start_background_cleanup(self) -> None:
        """Запускает фоновую очистку просроченных клиентов."""

        def cleanup_worker():
            while not self._shutdown_event.wait(60.0):  # Проверяем каждую минуту
                try:
                    cleaned = self._client_cache.cleanup_expired()
                    if cleaned > 0:
                        logger.debug(f"Background cleanup removed {cleaned} expired clients")
                except Exception as e:
                    logger.error(f"Error in background cleanup: {e}")

        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self._cleanup_thread.start()
        logger.info("Started background client cleanup thread")

    def get_client(self, client_factory: Callable[[], Any], cache_key: str = "default") -> Any:
        """
        Получает клиент из кэша или создает новый.

        Args:
            client_factory: Функция создания клиента
            cache_key: Ключ для кэширования

        Returns:
            HTTP клиент (кэшированный или новый)
        """
        cached_client = self._client_cache.get(cache_key)
        if cached_client is not None:
            return cached_client

        # Создаем новый клиент
        new_client = client_factory()
        self._client_cache.set(cache_key, new_client)

        return new_client

    def stats(self) -> dict[str, Any]:
        """Возвращает статистику менеджера клиентов."""
        return {
            "cache_stats": self._client_cache.stats(),
            "background_cleanup_active": self._cleanup_thread is not None
            and self._cleanup_thread.is_alive(),
        }

    def shutdown(self) -> None:
        """Graceful shutdown менеджера."""
        logger.info("Shutting down client manager...")

        # Останавливаем фоновую очистку
        self._shutdown_event.set()
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5.0)

        # Очищаем кэш (закрывает все клиенты)
        self._client_cache.clear()

        logger.info("Client manager shutdown completed")


# Глобальный менеджер клиентов
_client_manager = ClientManager()

# Регистрируем graceful shutdown
atexit.register(_client_manager.shutdown)


def get_client_manager() -> ClientManager:
    """Получает глобальный менеджер клиентов."""
    return _client_manager


__all__ = [
    "TTLCache",
    "lru_cache_with_ttl",
    "ClientManager",
    "get_client_manager",
]
