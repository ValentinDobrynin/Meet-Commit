"""
Асинхронные версии Notion Commits gateway функций.

Модуль содержит async версии ключевых функций для устранения
run_in_executor и улучшения производительности.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.metrics import MetricNames, async_timer, track_batch_operation
from app.gateways.notion_commits import _map_commit_page, _props_commit
from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


async def upsert_commits_async(meeting_page_id: str, commits: list[dict]) -> dict[str, list[str]]:
    """
    Асинхронная версия upsert_commits.
    
    Создает или обновляет коммиты в Notion с дедупликацией по ключу.
    
    Args:
        meeting_page_id: ID страницы встречи в Notion
        commits: Список коммитов для сохранения
        
    Returns:
        Словарь с ID созданных и обновленных коммитов
    """
    async with async_timer(MetricNames.NOTION_UPSERT_COMMITS):
        if not commits:
            logger.debug("No commits to upsert")
            return {"created": [], "updated": []}

        if not settings.commits_db_id:
            raise RuntimeError("COMMITS_DB_ID не настроен")

        logger.info(f"Processing {len(commits)} commits for meeting {meeting_page_id}")

        # Создаем асинхронный HTTP клиент
        timeout = httpx.Timeout(30.0)
        headers = {
            "Authorization": f"Bearer {settings.notion_token}",
            "Notion-Version": "2022-06-28", 
            "Content-Type": "application/json",
        }
        
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            created: list[str] = []
            updated: list[str] = []

            # Обрабатываем коммиты параллельно (но ограничиваем concurrency)
            semaphore = asyncio.Semaphore(5)  # Максимум 5 одновременных запросов
            
            async def process_commit(commit: dict) -> tuple[str, str | None]:
                """Обрабатывает один коммит, возвращает (operation, page_id)."""
                async with semaphore:
                    try:
                        # Проверяем существование по ключу
                        existing_page_id = await _query_by_key_async(client, commit["key"])
                        
                        # Подготавливаем properties
                        props = _props_commit(commit, meeting_page_id)
                        
                        if existing_page_id:
                            # Обновляем существующий
                            response = await client.patch(
                                f"{NOTION_API}/pages/{existing_page_id}",
                                json={"properties": props}
                            )
                            response.raise_for_status()
                            logger.debug(f"Updated commit: {commit['key']}")
                            return ("updated", existing_page_id)
                        else:
                            # Создаем новый
                            payload = {
                                "parent": {"database_id": settings.commits_db_id},
                                "properties": props,
                            }
                            response = await client.post(f"{NOTION_API}/pages", json=payload)
                            response.raise_for_status()
                            
                            page_data = response.json()
                            page_id = page_data["id"]
                            logger.debug(f"Created commit: {commit['key']}")
                            return ("created", page_id)
                            
                    except Exception as e:
                        logger.error(f"Error processing commit {commit.get('key', 'unknown')}: {e}")
                        return ("error", None)

            # Запускаем обработку всех коммитов параллельно
            tasks = [process_commit(commit) for commit in commits]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Собираем результаты
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Commit {i} failed: {result}")
                    continue
                    
                operation, page_id = result
                if operation == "created" and page_id:
                    created.append(page_id)
                elif operation == "updated" and page_id:
                    updated.append(page_id)

        # Отслеживаем метрики
        track_batch_operation("commits.upsert", len(commits), len(created) + len(updated))
        
        logger.info(f"Commits processing completed: {len(created)} created, {len(updated)} updated")
        return {"created": created, "updated": updated}


async def _query_by_key_async(client: httpx.AsyncClient, key: str) -> str | None:
    """
    Асинхронная версия поиска коммита по ключу.
    
    Args:
        client: Асинхронный HTTP клиент
        key: Уникальный ключ коммита
        
    Returns:
        ID страницы если найдена, иначе None
    """
    try:
        payload = {
            "filter": {"property": "Key", "rich_text": {"equals": key}},
            "page_size": 1,
        }
        
        response = await client.post(
            f"{NOTION_API}/databases/{settings.commits_db_id}/query",
            json=payload
        )
        response.raise_for_status()
        
        results = response.json().get("results", [])
        if results:
            return results[0]["id"]
        return None
        
    except Exception as e:
        logger.warning(f"Error querying by key '{key}': {e}")
        return None


async def query_commits_async(
    filter_: dict[str, Any] | None = None,
    sorts: list[dict] | None = None,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    """
    Асинхронная версия запроса коммитов из Notion.
    
    Args:
        filter_: Фильтр для запроса
        sorts: Сортировка
        page_size: Размер страницы
        
    Returns:
        Список коммитов в стандартном формате
    """
    async with async_timer(MetricNames.NOTION_QUERY_COMMITS):
        if not settings.commits_db_id:
            logger.warning("COMMITS_DB_ID не настроен, возвращаем пустой список")
            return []

        timeout = httpx.Timeout(30.0)
        headers = {
            "Authorization": f"Bearer {settings.notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        
        payload: dict[str, Any] = {"page_size": page_size}
        if filter_:
            payload["filter"] = filter_
        if sorts:
            payload["sorts"] = sorts
        else:
            payload["sorts"] = [{"property": "Due", "direction": "ascending"}]

        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            try:
                response = await client.post(
                    f"{NOTION_API}/databases/{settings.commits_db_id}/query",
                    json=payload
                )
                response.raise_for_status()
                
                data = response.json()
                results = data.get("results", [])
                
                logger.debug(f"Query returned {len(results)} commits")
                
                # Преобразуем в стандартный формат
                commits = [_map_commit_page(page) for page in results]
                return commits
                
            except Exception as e:
                logger.error(f"Error querying commits: {e}")
                return []


async def update_commit_status_async(commit_id: str, status: str) -> bool:
    """
    Асинхронная версия обновления статуса коммита.
    
    Args:
        commit_id: ID коммита в Notion
        status: Новый статус (open, done, dropped)
        
    Returns:
        True если обновление успешно
    """
    async with async_timer(MetricNames.NOTION_UPDATE_COMMIT_STATUS):
        timeout = httpx.Timeout(30.0)
        headers = {
            "Authorization": f"Bearer {settings.notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        
        payload = {
            "properties": {
                "Status": {"select": {"name": status}}
            }
        }
        
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            try:
                response = await client.patch(
                    f"{NOTION_API}/pages/{commit_id}",
                    json=payload
                )
                response.raise_for_status()
                
                logger.info(f"Updated commit {commit_id} status to {status}")
                return True
                
            except Exception as e:
                logger.error(f"Error updating commit status: {e}")
                return False
