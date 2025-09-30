"""Helper функции для работы с Notion meetings для retag функциональности."""

from __future__ import annotations

import logging
from typing import Any

from app.core.clients import get_notion_http_client
from app.gateways.error_handling import notion_update, notion_validation
from app.gateways.notion_parsers import (
    extract_page_fields,
)

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


# Используем общие парсеры из notion_parsers.py


@notion_update("fetch_meeting_page")  # Strict handling для критичных данных
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

    try:
        # Используем context manager для правильного lifecycle
        with get_notion_http_client() as client:
            # Получаем страницу
            response = client.get(f"{NOTION_API}/pages/{formatted_id}")

            if response.status_code == 404:
                raise RuntimeError(f"Meeting page not found: {page_id}")
            elif response.status_code != 200:
                raise RuntimeError(f"Notion API error {response.status_code}: {response.text}")

            response.raise_for_status()
            page_data = response.json()

            # Используем общие парсеры для автоматического извлечения полей
            field_mapping = {
                "title": ("Name", "title"),
                "summary_md": ("Summary MD", "rich_text"),
                "current_tags": ("Tags", "multi_select"),
            }

            result = extract_page_fields(page_data, field_mapping)
            result["page_id"] = formatted_id

            return result

    except Exception as e:
        logger.error(f"Error fetching meeting page {page_id}: {e}")
        raise RuntimeError(f"Failed to fetch meeting page: {e}") from e


@notion_update("update_meeting_tags")  # Strict handling для целостности данных
def update_meeting_tags(page_id: str, tags: list[str]) -> bool:
    """
    Обновляет теги страницы встречи.

    Args:
        page_id: ID страницы встречи
        tags: Новый список тегов

    Returns:
        True если успешно обновлено

    Raises:
        NotionAPIError: При ошибках API (strict handling для целостности данных)
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

    try:
        # Используем context manager для правильного lifecycle
        with get_notion_http_client() as client:
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


@notion_validation("validate_meeting_access")  # Graceful fallback на False
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
