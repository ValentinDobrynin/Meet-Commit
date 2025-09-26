import logging
from typing import Any

from app.core.clients import get_notion_client
from app.core.metrics import MetricNames, inc, timer
from app.settings import settings as app_settings

logger = logging.getLogger(__name__)


# Удалено: используем единые клиенты и настройки из app.core.clients и app.settings


# -------- helpers --------


def _props(payload: dict[str, Any]) -> dict[str, Any]:
    """Собирает properties под фактические поля базы."""
    name = (payload.get("title") or "Untitled Meeting")[:200]
    date = payload.get("date")  # ISO YYYY-MM-DD
    attendees: list[str] = payload.get("attendees", [])
    source = payload.get("source", "telegram")
    raw_hash = payload.get("raw_hash", "")
    summary_md = (payload.get("summary_md") or "")[:1900]  # ограничим rich_text
    tags: list[str] = payload.get("tags", [])

    # Логируем данные для диагностики
    logger.debug(f"Building props for meeting: title='{name}', date='{date}'")
    logger.debug(f"Attendees raw: {attendees} (type: {type(attendees)}, len: {len(attendees)})")
    logger.debug(f"Tags raw: {tags} (type: {type(tags)}, len: {len(tags)})")

    # Создаем multi_select для attendees
    attendees_multi_select = [{"name": str(a)} for a in attendees if a and str(a).strip()]
    logger.debug(f"Attendees multi_select: {attendees_multi_select}")

    props = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Date": {"date": {"start": date} if date else None},
        "Attendees": {"multi_select": attendees_multi_select},
        "Source": {"rich_text": [{"text": {"content": source}}]},
        "Raw hash": {"rich_text": [{"text": {"content": raw_hash}}]},
        "Summary MD": {"rich_text": [{"text": {"content": summary_md}}]},
        "Tags": {"multi_select": [{"name": t} for t in tags]},
    }
    return props


# -------- public API --------


def upsert_meeting(payload: dict[str, Any]) -> str:
    """
    Создаёт новую страницу Meeting или возвращает существующую по raw_hash.
    Возвращает URL страницы.
    Ожидаемые поля payload: title, date, attendees, source, raw_hash, summary_md, tags.
    """
    with timer(MetricNames.NOTION_CREATE_MEETING):
        try:
            client = get_notion_client()
            db_id = app_settings.notion_db_meetings_id
            if not db_id:
                raise RuntimeError("NOTION_DB_MEETINGS_ID не настроен")
            raw_hash = payload.get("raw_hash", "")

            title = payload.get("title", "Untitled Meeting")
            tags_count = len(payload.get("tags", []))
            attendees_count = len(payload.get("attendees", []))

            # Проверяем, существует ли встреча с таким raw_hash (если дедупликация включена)
            if raw_hash and app_settings.enable_meetings_dedup:
                try:
                    response = client.databases.query(
                        database_id=db_id,
                        filter={"property": "Raw hash", "rich_text": {"equals": raw_hash}},
                        page_size=1,
                    )

                    results = response.get("results", [])  # type: ignore[union-attr]
                    if results:
                        existing_page = results[0]
                        existing_page_id = existing_page["id"]
                        existing_url = existing_page.get("url", "")

                        # Обновляем существующую встречу с объединением данных
                        logger.info(
                            f"♻️ Updating existing meeting with hash '{raw_hash}': {existing_url}"
                        )
                        inc(MetricNames.MEETINGS_DEDUP_HIT)

                        # Получаем текущие данные для объединения
                        current_props = existing_page.get("properties", {})

                        # Объединяем теги
                        current_tags = [
                            tag["name"]
                            for tag in current_props.get("Tags", {}).get("multi_select", [])
                        ]
                        new_tags = payload.get("tags", [])
                        merged_tags = sorted(set(current_tags) | set(new_tags))

                        # Объединяем участников
                        current_attendees = [
                            att["name"]
                            for att in current_props.get("Attendees", {}).get("multi_select", [])
                        ]
                        new_attendees = payload.get("attendees", [])
                        merged_attendees = sorted(set(current_attendees) | set(new_attendees))

                        # Подготавливаем обновленные properties
                        update_props = _props(payload)
                        if merged_tags:
                            update_props["Tags"] = {
                                "multi_select": [{"name": tag} for tag in merged_tags]
                            }
                        if merged_attendees:
                            update_props["Attendees"] = {
                                "multi_select": [{"name": att} for att in merged_attendees]
                            }

                        # Обновляем страницу
                        client.pages.update(page_id=existing_page_id, properties=update_props)

                        logger.info(
                            f"Updated meeting: tags {len(current_tags)}→{len(merged_tags)}, attendees {len(current_attendees)}→{len(merged_attendees)}"
                        )
                        return str(existing_url)

                except Exception as e:
                    logger.warning(f"Failed to query existing meeting by hash: {e}")
                    # Продолжаем создание новой встречи

            logger.info(
                f"Creating meeting page: '{title}' with {tags_count} tags, {attendees_count} attendees"
            )
            inc(MetricNames.MEETINGS_DEDUP_MISS)

            # Создаем новую запись
            properties = _props(payload)
            create_response = client.pages.create(
                parent={"database_id": db_id},
                properties=properties,
            )
            page_id = create_response["id"]  # type: ignore[index]

            page_response = client.pages.retrieve(page_id)
            url = str(page_response["url"])  # type: ignore[index]

            logger.info(f"Meeting page created successfully: {url}")
            return url

        except Exception as e:
            logger.error(f"Failed to create meeting page: {e}", exc_info=True)
            raise
