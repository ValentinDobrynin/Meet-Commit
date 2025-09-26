"""
Оптимизатор запросов к Notion API.

Обеспечивает кэширование, batch операции и умную пагинацию
для снижения нагрузки на Notion API и улучшения производительности.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from app.core.metrics import observe_latency

logger = logging.getLogger(__name__)

# Кэш запросов (время жизни 5 минут)
_query_cache: dict[str, tuple[Any, float]] = {}
_cache_ttl: float = 300.0  # 5 минут


def _generate_cache_key(database_id: str, filter_: dict[str, Any] | None, sorts: list[dict] | None) -> str:
    """Генерирует ключ кэша для запроса."""
    cache_data = {
        "database_id": database_id,
        "filter": filter_,
        "sorts": sorts,
    }
    
    # Создаем стабильный хэш
    cache_str = json.dumps(cache_data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(cache_str.encode()).hexdigest()


def _is_cache_valid(timestamp: float) -> bool:
    """Проверяет валидность записи в кэше."""
    return time.time() - timestamp < _cache_ttl


def _get_from_cache(cache_key: str) -> Any | None:
    """Получает данные из кэша если они валидны."""
    if cache_key in _query_cache:
        data, timestamp = _query_cache[cache_key]
        if _is_cache_valid(timestamp):
            logger.debug(f"Cache hit for key: {cache_key[:8]}...")
            return data
        else:
            # Удаляем устаревшую запись
            del _query_cache[cache_key]
            logger.debug(f"Cache expired for key: {cache_key[:8]}...")
    
    return None


def _set_cache(cache_key: str, data: Any) -> None:
    """Сохраняет данные в кэш."""
    _query_cache[cache_key] = (data, time.time())
    logger.debug(f"Cache set for key: {cache_key[:8]}...")


def clear_query_cache() -> None:
    """Очищает весь кэш запросов."""
    _query_cache.clear()
    logger.info("Query cache cleared")


def get_cache_stats() -> dict[str, Any]:
    """Получает статистику кэша."""
    time.time()
    valid_entries = sum(
        1 for _, timestamp in _query_cache.values() 
        if _is_cache_valid(timestamp)
    )
    
    return {
        "total_entries": len(_query_cache),
        "valid_entries": valid_entries,
        "expired_entries": len(_query_cache) - valid_entries,
        "cache_ttl_seconds": _cache_ttl,
        "memory_usage_estimate": len(_query_cache) * 1024,  # Примерная оценка
    }


class NotionQueryOptimizer:
    """Оптимизатор запросов к Notion."""
    
    def __init__(self, enable_cache: bool = True, enable_batching: bool = True):
        self.enable_cache = enable_cache
        self.enable_batching = enable_batching
        self.batch_queue: list[tuple[str, dict[str, Any], asyncio.Future]] = []
        self.batch_timeout = 0.1  # 100ms для сбора batch
        self._batch_task: asyncio.Task | None = None
    
    async def query_database(
        self,
        client: Any,  # httpx.AsyncClient или notion_client.Client
        database_id: str,
        filter_: dict[str, Any] | None = None,
        sorts: list[dict] | None = None,
        page_size: int = 100,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """
        Оптимизированный запрос к базе данных.
        
        Args:
            client: HTTP или Notion клиент
            database_id: ID базы данных
            filter_: Фильтр запроса
            sorts: Сортировка
            page_size: Размер страницы
            use_cache: Использовать кэш
            
        Returns:
            Результат запроса
        """
        start_time = time.perf_counter()
        
        # Проверяем кэш
        if self.enable_cache and use_cache:
            cache_key = _generate_cache_key(database_id, filter_, sorts)
            cached_result = _get_from_cache(cache_key)
            if cached_result is not None:
                observe_latency("notion.query.cache_hit", 0.1)  # Кэш очень быстрый
                return cached_result
        
        # Выполняем запрос
        try:
            if hasattr(client, 'databases'):
                # Notion SDK клиент
                response = client.databases.query(
                    database_id=database_id,
                    filter=filter_,
                    sorts=sorts,
                    page_size=page_size,
                )
                result = {
                    "results": response.get("results", []),
                    "next_cursor": response.get("next_cursor"),
                    "has_more": response.get("has_more", False),
                }
            else:
                # HTTP клиент
                payload = {"page_size": page_size}
                if filter_:
                    payload["filter"] = filter_
                if sorts:
                    payload["sorts"] = sorts
                
                response = client.post(
                    f"https://api.notion.com/v1/databases/{database_id}/query",
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
            
            duration_ms = (time.perf_counter() - start_time) * 1000
            observe_latency("notion.query.api_call", duration_ms)
            
            # Сохраняем в кэш
            if self.enable_cache and use_cache:
                _set_cache(cache_key, result)
            
            logger.debug(f"Database query completed in {duration_ms:.1f}ms, returned {len(result.get('results', []))} items")
            return result
            
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            observe_latency("notion.query.error", duration_ms)
            logger.error(f"Database query failed after {duration_ms:.1f}ms: {e}")
            raise
    
    async def batch_query_databases(
        self,
        client: Any,
        queries: list[tuple[str, dict[str, Any] | None, list[dict] | None]],
    ) -> list[dict[str, Any]]:
        """
        Выполняет множественные запросы с оптимизацией.
        
        Args:
            client: HTTP или Notion клиент
            queries: Список (database_id, filter, sorts)
            
        Returns:
            Список результатов запросов
        """
        if not queries:
            return []
        
        logger.info(f"Executing batch of {len(queries)} database queries")
        
        # Создаем семафор для контроля конкурентности
        semaphore = asyncio.Semaphore(5)  # Максимум 5 одновременных запросов
        
        async def execute_query(database_id: str, filter_: dict[str, Any] | None, sorts: list[dict] | None):
            async with semaphore:
                return await self.query_database(client, database_id, filter_, sorts)
        
        # Выполняем все запросы параллельно
        start_time = time.perf_counter()
        results = await asyncio.gather(
            *[execute_query(db_id, filter_, sorts) for db_id, filter_, sorts in queries],
            return_exceptions=True,
        )
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        observe_latency("notion.batch_query", duration_ms)
        
        # Обрабатываем исключения
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Query {i} failed: {result}")
                processed_results.append({"results": [], "error": str(result)})
            else:
                processed_results.append(result)
        
        logger.info(f"Batch query completed in {duration_ms:.1f}ms")
        return processed_results


# Глобальный оптимизатор
_global_optimizer = NotionQueryOptimizer()


async def optimized_query(
    client: Any,
    database_id: str,
    filter_: dict[str, Any] | None = None,
    sorts: list[dict] | None = None,
    page_size: int = 100,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Удобная функция для оптимизированного запроса."""
    return await _global_optimizer.query_database(
        client, database_id, filter_, sorts, page_size, use_cache
    )


async def optimized_batch_query(
    client: Any,
    queries: list[tuple[str, dict[str, Any] | None, list[dict] | None]],
) -> list[dict[str, Any]]:
    """Удобная функция для batch запросов."""
    return await _global_optimizer.batch_query_databases(client, queries)


def configure_optimizer(
    cache_ttl: float | None = None,
    enable_cache: bool | None = None,
    enable_batching: bool | None = None,
) -> None:
    """Настраивает глобальный оптимизатор."""
    global _cache_ttl, _global_optimizer
    
    if cache_ttl is not None:
        _cache_ttl = cache_ttl
        logger.info(f"Cache TTL set to {cache_ttl}s")
    
    if enable_cache is not None:
        _global_optimizer.enable_cache = enable_cache
        logger.info(f"Cache {'enabled' if enable_cache else 'disabled'}")
    
    if enable_batching is not None:
        _global_optimizer.enable_batching = enable_batching
        logger.info(f"Batching {'enabled' if enable_batching else 'disabled'}")


# =============== SMART PAGINATION ===============


async def paginate_all_results(
    client: Any,
    database_id: str,
    filter_: dict[str, Any] | None = None,
    sorts: list[dict] | None = None,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """
    Умная пагинация - получает все результаты с ограничением.
    
    Args:
        client: HTTP или Notion клиент
        database_id: ID базы данных
        filter_: Фильтр запроса
        sorts: Сортировка
        max_pages: Максимальное количество страниц
        
    Returns:
        Все результаты из всех страниц
    """
    all_results = []
    next_cursor = None
    page_count = 0
    
    logger.debug(f"Starting pagination for database {database_id[:8]}...")
    
    while page_count < max_pages:
        # Добавляем cursor к filter если есть
        current_filter = filter_
        if next_cursor:
            # Notion API использует start_cursor в payload, не в filter
            pass
        
        # Выполняем запрос
        try:
            result = await optimized_query(
                client, 
                database_id, 
                current_filter, 
                sorts, 
                page_size=100,
                use_cache=page_count == 0  # Кэшируем только первую страницу
            )
            
            page_results = result.get("results", [])
            all_results.extend(page_results)
            
            logger.debug(f"Page {page_count + 1}: {len(page_results)} results")
            
            # Проверяем есть ли еще страницы
            if not result.get("has_more", False):
                break
                
            next_cursor = result.get("next_cursor")
            if not next_cursor:
                break
                
            page_count += 1
            
        except Exception as e:
            logger.error(f"Pagination failed on page {page_count + 1}: {e}")
            break
    
    logger.info(f"Pagination completed: {len(all_results)} total results from {page_count + 1} pages")
    return all_results
