"""Gateway для синхронизации правил тегирования с Notion Tag Catalog.

Обеспечивает централизованное управление правилами тегирования через Notion
с fallback на локальные YAML файлы при недоступности Notion.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.clients import get_notion_http_client
from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


# Удалено: используем единый клиент из app.core.clients


def _parse_rich_text(prop: dict | None) -> str:
    """Парсит Notion rich_text property."""
    if not prop or not prop.get("rich_text"):
        return ""

    # Собираем текст из всех блоков
    text_parts = []
    for block in prop["rich_text"]:
        if block.get("text", {}).get("content"):
            text_parts.append(block["text"]["content"])

    return "\n".join(text_parts)


def _parse_select(prop: dict | None) -> str:
    """Парсит Notion select property."""
    if not prop or not prop.get("select"):
        return ""
    return prop["select"].get("name", "")


def _parse_number(prop: dict | None) -> float:
    """Парсит Notion number property."""
    if not prop or prop.get("number") is None:
        return 1.0
    return float(prop["number"])


def _parse_checkbox(prop: dict | None) -> bool:
    """Парсит Notion checkbox property."""
    if not prop:
        return False
    return bool(prop.get("checkbox", False))


def _parse_title(prop: dict | None) -> str:
    """Парсит Notion title property."""
    if not prop or not prop.get("title"):
        return ""

    # Собираем текст из всех блоков title
    text_parts = []
    for block in prop["title"]:
        if block.get("text", {}).get("content"):
            text_parts.append(block["text"]["content"])

    return "".join(text_parts)


def fetch_tag_catalog() -> list[dict[str, Any]]:
    """
    Скачивает все активные правила из базы Tag Catalog в Notion.

    Returns:
        Список правил в формате для tagger_v1_scored

    Raises:
        RuntimeError: При ошибках API или отсутствии базы
    """
    if not settings.notion_sync_enabled:
        raise RuntimeError("Notion sync is disabled in settings")

    client = get_notion_http_client()

    try:
        # Запрашиваем только активные правила
        query_payload = {
            "filter": {"property": "Active", "checkbox": {"equals": True}},
            "sorts": [
                {"property": "Kind", "direction": "ascending"},
                {"property": "Name", "direction": "ascending"},
            ],
        }

        response = client.post(
            f"{NOTION_API}/databases/{settings.notion_db_tag_catalog_id}/query", json=query_payload
        )

        if response.status_code != 200:
            raise RuntimeError(f"Notion API error {response.status_code}: {response.text}")

        response.raise_for_status()
        results = response.json().get("results", [])

        rules = []
        kind_counts: dict[str, int] = {}

        for row in results:
            try:
                props = row.get("properties", {})

                # Парсим основные поля
                name = _parse_title(props.get("Name"))
                kind = _parse_select(props.get("Kind"))
                patterns_text = _parse_rich_text(props.get("Pattern(s)"))
                exclude_text = _parse_rich_text(props.get("Exclude"))
                weight = _parse_number(props.get("Weight"))
                active = _parse_checkbox(props.get("Active"))

                if not name or not kind or not patterns_text:
                    logger.warning(f"Skipping incomplete rule: name='{name}', kind='{kind}'")
                    continue

                if not active:
                    logger.debug(f"Skipping inactive rule: {name}")
                    continue

                # Парсим паттерны (по одному на строку)
                # Обрабатываем как реальные переносы строк, так и \\n в тексте
                patterns_normalized = patterns_text.replace("\\n", "\n")
                patterns = [
                    line.strip() for line in patterns_normalized.splitlines() if line.strip()
                ]

                exclude_patterns = []
                if exclude_text:
                    exclude_normalized = exclude_text.replace("\\n", "\n")
                    exclude_patterns = [
                        line.strip() for line in exclude_normalized.splitlines() if line.strip()
                    ]

                if not patterns:
                    logger.warning(f"Skipping rule without patterns: {name}")
                    continue

                # Формируем полное имя тега
                tag_name = f"{kind}/{name}"

                rule_data = {
                    "id": row["id"],
                    "tag": tag_name,
                    "patterns": patterns,
                    "exclude": exclude_patterns,
                    "weight": weight,
                }

                rules.append(rule_data)
                kind_counts[kind] = kind_counts.get(kind, 0) + 1

                logger.debug(f"Parsed rule: {tag_name} with {len(patterns)} patterns")

            except Exception as e:
                logger.error(f"Error parsing rule from row {row.get('id', 'unknown')}: {e}")
                continue

        logger.info(
            f"Fetched {len(rules)} active rules from Tag Catalog. "
            f"By kind: {dict(sorted(kind_counts.items()))}"
        )

        return rules

    except Exception as e:
        logger.error(f"Error fetching tag catalog: {e}")
        raise RuntimeError(f"Failed to fetch tag catalog: {e}") from e
    finally:
        client.close()


def validate_tag_catalog_access() -> bool:
    """
    Проверяет доступность базы Tag Catalog.

    Returns:
        True если база доступна
    """
    if not settings.notion_sync_enabled:
        return False

    if not settings.notion_token or not settings.notion_db_tag_catalog_id:
        return False

    try:
        client = get_notion_http_client()

        # Простой запрос для проверки доступа
        response = client.get(f"{NOTION_API}/databases/{settings.notion_db_tag_catalog_id}")

        if response.status_code == 200:
            logger.debug("Tag Catalog access validated successfully")
            return True
        else:
            logger.warning(f"Tag Catalog access failed: {response.status_code}")
            return False

    except Exception as e:
        logger.warning(f"Tag Catalog access validation failed: {e}")
        return False
    finally:
        if "client" in locals():
            client.close()


def get_tag_catalog_info() -> dict[str, Any]:
    """
    Получает информацию о базе Tag Catalog.

    Returns:
        Словарь с метаданными базы
    """
    if not validate_tag_catalog_access():
        return {"accessible": False, "error": "Tag Catalog not accessible or sync disabled"}

    try:
        client = get_notion_http_client()

        response = client.get(f"{NOTION_API}/databases/{settings.notion_db_tag_catalog_id}")
        response.raise_for_status()

        db_data = response.json()

        return {
            "accessible": True,
            "title": db_data.get("title", [{}])[0].get("plain_text", "Tag Catalog"),
            "created_time": db_data.get("created_time"),
            "last_edited_time": db_data.get("last_edited_time"),
            "properties": list(db_data.get("properties", {}).keys()),
        }

    except Exception as e:
        logger.error(f"Error getting tag catalog info: {e}")
        return {"accessible": False, "error": str(e)}
    finally:
        if "client" in locals():
            client.close()
