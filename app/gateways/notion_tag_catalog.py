"""Gateway для синхронизации правил тегирования с Notion Tag Catalog.

Обеспечивает централизованное управление правилами тегирования через Notion
с fallback на локальные YAML файлы при недоступности Notion.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.clients import get_notion_http_client
from app.gateways.error_handling import notion_update, notion_validation
from app.gateways.notion_parsers import (
    parse_checkbox,
    parse_number,
    parse_rich_text,
    parse_select,
    parse_title,
)
from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


# Используем общие парсеры из notion_parsers.py


@notion_update("fetch_tag_catalog")  # Strict handling для критичных данных
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

                # Парсим основные поля с помощью общих парсеров
                name = parse_title(props.get("Name"))
                kind = parse_select(props.get("Kind"))
                patterns_text = parse_rich_text(props.get("Pattern(s)"))
                exclude_text = parse_rich_text(props.get("Exclude"))
                weight = parse_number(props.get("Weight"))
                active = parse_checkbox(props.get("Active"))

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


@notion_validation("validate_tag_catalog_access")  # Graceful fallback на False
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


@notion_validation("get_tag_catalog_info")  # Graceful fallback с error info
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


@notion_update("create_tag_rule")
def create_tag_rule(rule: dict[str, Any]) -> str:
    """
    Создает новое правило в Notion Tag Catalog.

    Args:
        rule: Правило в формате YAML (name, patterns, exclude, weight, kind)

    Returns:
        ID созданной страницы

    Raises:
        RuntimeError: При ошибках создания
    """
    if not settings.notion_sync_enabled:
        raise RuntimeError("Notion sync is disabled in settings")

    client = get_notion_http_client()

    try:
        # Подготавливаем данные для создания страницы
        properties = {
            "Name": {"title": [{"text": {"content": rule["name"]}}]},
            "Kind": {"select": {"name": rule.get("kind", "Topic")}},
            "Weight": {"number": rule.get("weight", 1.0)},
            "Active": {"checkbox": True},
        }

        # Добавляем patterns как multi_select или rich_text
        patterns = rule.get("patterns", [])
        if patterns:
            # Используем rich_text для хранения patterns (как массив)
            patterns_text = "\n".join(patterns)
            properties["Pattern(s)"] = {"rich_text": [{"text": {"content": patterns_text}}]}

        # Добавляем exclude как rich_text
        exclude = rule.get("exclude", [])
        if exclude:
            exclude_text = "\n".join(exclude)
            properties["Exclude"] = {"rich_text": [{"text": {"content": exclude_text}}]}

        # Добавляем описание если есть
        description = rule.get("description", "")
        if description:
            properties["Description"] = {"rich_text": [{"text": {"content": description}}]}

        # Создаем страницу
        payload = {
            "parent": {"database_id": settings.notion_db_tag_catalog_id},
            "properties": properties,
        }

        response = client.post(f"{NOTION_API}/pages", json=payload)
        response.raise_for_status()

        page_data = response.json()
        page_id = page_data["id"]

        logger.info(f"Created tag rule in Notion: {rule['name']} (ID: {page_id})")
        return page_id

    except Exception as e:
        logger.error(f"Error creating tag rule {rule.get('name', 'unknown')}: {e}")
        raise RuntimeError(f"Failed to create tag rule: {e}") from e
    finally:
        client.close()


@notion_update("update_tag_rule")
def update_tag_rule(page_id: str, rule: dict[str, Any]) -> bool:
    """
    Обновляет существующее правило в Notion Tag Catalog.

    Args:
        page_id: ID страницы в Notion
        rule: Обновленное правило в формате YAML

    Returns:
        True если обновление успешно

    Raises:
        RuntimeError: При ошибках обновления
    """
    if not settings.notion_sync_enabled:
        raise RuntimeError("Notion sync is disabled in settings")

    client = get_notion_http_client()

    try:
        # Подготавливаем данные для обновления
        properties = {
            "Kind": {"select": {"name": rule.get("kind", "Topic")}},
            "Weight": {"number": rule.get("weight", 1.0)},
            "Active": {"checkbox": True},
        }

        # Обновляем patterns
        patterns = rule.get("patterns", [])
        if patterns:
            patterns_text = "\n".join(patterns)
            properties["Pattern(s)"] = {"rich_text": [{"text": {"content": patterns_text}}]}

        # Обновляем exclude
        exclude = rule.get("exclude", [])
        if exclude:
            exclude_text = "\n".join(exclude)
            properties["Exclude"] = {"rich_text": [{"text": {"content": exclude_text}}]}
        else:
            # Очищаем поле если exclude пустой
            properties["Exclude"] = {"rich_text": []}

        # Обновляем описание
        description = rule.get("description", "")
        if description:
            properties["Description"] = {"rich_text": [{"text": {"content": description}}]}

        # Обновляем страницу
        payload = {"properties": properties}

        response = client.patch(f"{NOTION_API}/pages/{page_id}", json=payload)
        response.raise_for_status()

        logger.info(f"Updated tag rule in Notion: {rule['name']} (ID: {page_id})")
        return True

    except Exception as e:
        logger.error(f"Error updating tag rule {rule.get('name', 'unknown')}: {e}")
        raise RuntimeError(f"Failed to update tag rule: {e}") from e
    finally:
        client.close()
