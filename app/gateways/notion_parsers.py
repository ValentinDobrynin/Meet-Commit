"""
Общие парсеры для Notion API properties.

Устраняет дублирование кода парсинга между gateway модулями
и обеспечивает консистентную обработку данных из Notion.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


__all__ = [
    "parse_rich_text",
    "parse_title",
    "parse_select",
    "parse_multi_select",
    "parse_date",
    "parse_number",
    "parse_checkbox",
    "parse_relation",
    "parse_relation_single",
]


def parse_rich_text(prop: dict | None) -> str:
    """
    Парсит Notion rich_text property.

    Args:
        prop: Notion property объект

    Returns:
        Объединенный текст из всех блоков
    """
    if not prop or prop.get("type") != "rich_text":
        return ""

    parts = prop.get("rich_text", [])
    if not parts:  # Защита от None
        return ""
    return "".join(p.get("plain_text", "") for p in parts).strip()


def parse_title(prop: dict | None) -> str:
    """
    Парсит Notion title property.

    Args:
        prop: Notion property объект

    Returns:
        Объединенный текст из всех блоков title
    """
    if not prop or prop.get("type") != "title":
        return ""

    parts = prop.get("title", [])
    if not parts:  # Защита от None
        return ""
    return "".join(p.get("plain_text", "") for p in parts).strip()


def parse_select(prop: dict | None) -> str | None:
    """
    Парсит Notion select property.

    Args:
        prop: Notion property объект

    Returns:
        Название выбранного варианта или None
    """
    if not prop or prop.get("type") != "select":
        return None

    select_data = prop.get("select")
    return select_data.get("name") if select_data else None


def parse_multi_select(prop: dict | None) -> list[str]:
    """
    Парсит Notion multi_select property.

    Args:
        prop: Notion property объект

    Returns:
        Список названий выбранных вариантов
    """
    if not prop or prop.get("type") != "multi_select":
        return []

    multi_select_list = prop.get("multi_select", [])
    if not multi_select_list:  # Защита от None
        return []
    return [item.get("name", "") for item in multi_select_list if item.get("name")]


def parse_date(prop: dict | None) -> str | None:
    """
    Парсит Notion date property.

    Args:
        prop: Notion property объект

    Returns:
        ISO дата или None
    """
    if not prop or prop.get("type") != "date":
        return None

    date_data = prop.get("date")
    return date_data.get("start") if date_data else None


def parse_number(prop: dict | None) -> float:
    """
    Парсит Notion number property.

    Args:
        prop: Notion property объект

    Returns:
        Числовое значение или 1.0 по умолчанию
    """
    if not prop or prop.get("type") != "number":
        return 1.0

    number_value = prop.get("number")
    return float(number_value) if number_value is not None else 1.0


def parse_checkbox(prop: dict | None) -> bool:
    """
    Парсит Notion checkbox property.

    Args:
        prop: Notion property объект

    Returns:
        Булево значение
    """
    if not prop or prop.get("type") != "checkbox":
        return False

    return bool(prop.get("checkbox", False))


def parse_relation(prop: dict | None) -> list[str]:
    """
    Парсит Notion relation property.

    Args:
        prop: Notion property объект

    Returns:
        Список ID связанных страниц
    """
    if not prop or prop.get("type") != "relation":
        return []

    relation_list = prop.get("relation", [])
    if not relation_list:  # Защита от None
        return []
    return [item.get("id", "") for item in relation_list if item.get("id")]


def parse_relation_single(prop: dict | None) -> str | None:
    """
    Парсит Notion relation property для одного элемента.

    Args:
        prop: Notion property объект

    Returns:
        ID первой связанной страницы или None
    """
    relations = parse_relation(prop)
    return relations[0] if relations else None


def extract_page_fields(
    page: dict[str, Any], field_mapping: dict[str, tuple[str, str]]
) -> dict[str, Any]:
    """
    Извлекает поля из Notion страницы с автоматическим парсингом.

    Args:
        page: Notion page объект
        field_mapping: Маппинг {output_field: (notion_field, parser_type)}

    Returns:
        Словарь с распарсенными полями

    Example:
        field_mapping = {
            "title": ("Name", "title"),
            "tags": ("Tags", "multi_select"),
            "date": ("Date", "date"),
            "active": ("Active", "checkbox"),
        }
    """
    props = page.get("properties", {})
    result = {"id": page.get("id"), "url": page.get("url")}

    # Маппинг типов парсеров на функции
    parsers = {
        "title": parse_title,
        "rich_text": parse_rich_text,
        "select": parse_select,
        "multi_select": parse_multi_select,
        "date": parse_date,
        "number": parse_number,
        "checkbox": parse_checkbox,
        "relation": parse_relation,
        "relation_single": parse_relation_single,
    }

    for output_field, (notion_field, parser_type) in field_mapping.items():
        parser = parsers.get(parser_type)
        if parser:
            try:
                result[output_field] = parser(props.get(notion_field))
            except Exception as e:
                logger.warning(f"Error parsing {notion_field} as {parser_type}: {e}")
                # Устанавливаем разумные значения по умолчанию
                if parser_type == "multi_select":
                    result[output_field] = []
                elif parser_type == "number":
                    result[output_field] = 0.0
                elif parser_type == "checkbox":
                    result[output_field] = False
                else:
                    result[output_field] = None
        else:
            logger.warning(f"Unknown parser type: {parser_type}")
            result[output_field] = None

    return result


def build_properties(
    data: dict[str, Any], field_mapping: dict[str, tuple[str, str]]
) -> dict[str, Any]:
    """
    Строит Notion properties из данных с автоматическим форматированием.

    Args:
        data: Исходные данные
        field_mapping: Маппинг {data_field: (notion_field, property_type)}

    Returns:
        Словарь properties для Notion API

    Example:
        field_mapping = {
            "title": ("Name", "title"),
            "tags": ("Tags", "multi_select"),
            "date": ("Date", "date"),
            "active": ("Active", "checkbox"),
        }
    """
    properties: dict[str, Any] = {}

    for data_field, (notion_field, property_type) in field_mapping.items():
        value = data.get(data_field)

        if value is None:
            continue

        try:
            if property_type == "title":
                properties[notion_field] = {"title": [{"text": {"content": str(value)[:2000]}}]}

            elif property_type == "rich_text":
                properties[notion_field] = {"rich_text": [{"text": {"content": str(value)[:2000]}}]}

            elif property_type == "select":
                properties[notion_field] = {"select": {"name": str(value)}}

            elif property_type == "multi_select":
                if isinstance(value, list):
                    properties[notion_field] = {
                        "multi_select": [{"name": str(v)} for v in value if v]
                    }

            elif property_type == "date":
                if value:
                    properties[notion_field] = {"date": {"start": str(value)}}
                else:
                    properties[notion_field] = {"date": None}

            elif property_type == "number":
                properties[notion_field] = {"number": float(value)}

            elif property_type == "checkbox":
                properties[notion_field] = {"checkbox": bool(value)}

            elif property_type == "relation":
                if isinstance(value, list):
                    properties[notion_field] = {"relation": [{"id": str(v)} for v in value if v]}
                elif value:
                    properties[notion_field] = {"relation": [{"id": str(value)}]}

        except Exception as e:
            logger.warning(f"Error building property {notion_field} ({property_type}): {e}")
            continue

    return properties


# Готовые маппинги для основных типов страниц

MEETING_FIELD_MAPPING = {
    "title": ("Name", "title"),
    "summary_md": ("Summary MD", "rich_text"),
    "tags": ("Tags", "multi_select"),
    "attendees": ("Attendees", "multi_select"),
    "date": ("Date", "date"),
    "source": ("Source", "rich_text"),
    "raw_hash": ("Raw hash", "rich_text"),
}

COMMIT_FIELD_MAPPING = {
    "title": ("Name", "title"),
    "text": ("Text", "rich_text"),
    "direction": ("Direction", "select"),
    "assignees": ("Assignee", "multi_select"),
    "from_person": ("From", "multi_select"),
    "due_iso": ("Due", "date"),
    "confidence": ("Confidence", "number"),
    "flags": ("Flags", "multi_select"),
    "status": ("Status", "select"),
    "tags": ("Tags", "multi_select"),
    "key": ("Key", "rich_text"),
}

REVIEW_FIELD_MAPPING = {
    "text": ("Commit text", "rich_text"),
    "direction": ("Direction", "select"),
    "assignees": ("Assignee", "multi_select"),
    "due_iso": ("Due", "date"),
    "confidence": ("Confidence", "number"),
    "reasons": ("Reason", "multi_select"),
    "context": ("Context", "rich_text"),
    "status": ("Status", "select"),
    "key": ("Key", "rich_text"),
}

AGENDA_FIELD_MAPPING = {
    "title": ("Name", "title"),
    "date": ("Date", "date"),
    "context_type": ("Context type", "select"),
    "context_key": ("Context key", "rich_text"),
    "summary_md": ("Summary MD", "rich_text"),
    "tags": ("Tags", "multi_select"),
    "people": ("People", "multi_select"),
    "raw_hash": ("Raw hash", "rich_text"),
    "commits_linked": ("Commits", "relation"),
}


__all__.extend(
    [
        "extract_page_fields",
        "build_properties",
        "MEETING_FIELD_MAPPING",
        "COMMIT_FIELD_MAPPING",
        "REVIEW_FIELD_MAPPING",
        "AGENDA_FIELD_MAPPING",
    ]
)
