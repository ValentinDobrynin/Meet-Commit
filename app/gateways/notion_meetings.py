"""Helper функции для работы с Notion meetings для retag функциональности."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


def _create_client() -> httpx.Client:
    """Создает новый HTTP клиент для Notion API."""
    if not settings.notion_token or not settings.notion_db_meetings_id:
        raise RuntimeError("Notion credentials missing: NOTION_TOKEN or NOTION_DB_MEETINGS_ID")

    headers = {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    return httpx.Client(timeout=30, headers=headers)


def _parse_rich_text(prop: dict | None) -> str:
    """Парсит Notion rich_text property."""
    if not prop or prop.get("type") != "rich_text":
        return ""
    parts = prop.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in parts).strip()


def _parse_title(prop: dict | None) -> str:
    """Парсит Notion title property."""
    if not prop or prop.get("type") != "title":
        return ""
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts).strip()


def _parse_multi_select(prop: dict | None) -> list[str]:
    """Парсит Notion multi_select property."""
    if not prop or prop.get("type") != "multi_select":
        return []
    return [x.get("name", "") for x in prop.get("multi_select", []) if x.get("name")]


def fetch_meeting_page(page_id: str) -> dict[str, Any]:
    """
    Получает данные страницы встречи из Notion.

    Args:
        page_id: ID страницы встречи

    Returns:
        Словарь с данными страницы

    Raises:
        RuntimeError: При ошибках API или отсутствии страницы
    """
    # Очищаем page_id от лишних символов
    clean_page_id = page_id.replace("-", "").replace(" ", "")

    # Проверяем формат UUID
    if len(clean_page_id) != 32:
        raise ValueError(f"Invalid page ID format: {page_id}")

    # Форматируем в UUID
    formatted_id = (
        f"{clean_page_id[:8]}-{clean_page_id[8:12]}-{clean_page_id[12:16]}-"
        f"{clean_page_id[16:20]}-{clean_page_id[20:32]}"
    )

    client = _create_client()

    try:
        # Получаем страницу
        response = client.get(f"{NOTION_API}/pages/{formatted_id}")

        if response.status_code == 404:
            raise RuntimeError(f"Meeting page not found: {page_id}")
        elif response.status_code != 200:
            raise RuntimeError(f"Notion API error {response.status_code}: {response.text}")

        response.raise_for_status()
        page_data = response.json()

        # Парсим properties
        props = page_data.get("properties", {})

        return {
            "page_id": formatted_id,
            "title": _parse_title(props.get("Name")),
            "summary_md": _parse_rich_text(props.get("Summary MD")),
            "current_tags": _parse_multi_select(props.get("Tags")),
            "url": page_data.get("url", ""),
        }

    except Exception as e:
        logger.error(f"Error fetching meeting page {page_id}: {e}")
        raise RuntimeError(f"Failed to fetch meeting page: {e}") from e
    finally:
        client.close()


def update_meeting_tags(page_id: str, tags: list[str]) -> bool:
    """
    Обновляет теги страницы встречи.

    Args:
        page_id: ID страницы встречи
        tags: Новый список тегов

    Returns:
        True если успешно обновлено

    Raises:
        RuntimeError: При ошибках API
    """
    # Очищаем page_id
    clean_page_id = page_id.replace("-", "").replace(" ", "")

    if len(clean_page_id) != 32:
        raise ValueError(f"Invalid page ID format: {page_id}")

    # Форматируем в UUID
    formatted_id = (
        f"{clean_page_id[:8]}-{clean_page_id[8:12]}-{clean_page_id[12:16]}-"
        f"{clean_page_id[16:20]}-{clean_page_id[20:32]}"
    )

    client = _create_client()

    try:
        # Подготавливаем properties для обновления
        properties = {"Tags": {"multi_select": [{"name": tag} for tag in tags if tag]}}

        # Обновляем страницу
        response = client.patch(
            f"{NOTION_API}/pages/{formatted_id}", json={"properties": properties}
        )

        if response.status_code == 404:
            raise RuntimeError(f"Meeting page not found: {page_id}")
        elif response.status_code != 200:
            raise RuntimeError(f"Notion API error {response.status_code}: {response.text}")

        response.raise_for_status()

        logger.info(f"Updated tags for meeting {page_id}: {len(tags)} tags")
        return True

    except Exception as e:
        logger.error(f"Error updating meeting tags {page_id}: {e}")
        raise RuntimeError(f"Failed to update meeting tags: {e}") from e
    finally:
        client.close()


def validate_meeting_access(page_id: str) -> bool:
    """
    Проверяет доступность страницы встречи для retag операций.

    Args:
        page_id: ID страницы для проверки

    Returns:
        True если страница доступна для редактирования
    """
    try:
        # Простая проверка - попытаемся получить страницу
        fetch_meeting_page(page_id)
        return True
    except Exception as e:
        logger.warning(f"Meeting {page_id} not accessible for retag: {e}")
        return False
