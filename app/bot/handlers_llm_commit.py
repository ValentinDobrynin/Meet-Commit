"""
Handler для создания коммитов через LLM парсинг человеческого языка.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import Message

from app.bot.formatters import format_commit_card
from app.core.llm_commit_parse import parse_commit_text
from app.gateways.notion_commits import _map_commit_page
from app.gateways.notion_commits_async import upsert_commits_async

logger = logging.getLogger(__name__)
router = Router()


def _get_user_name(message: Message) -> str:
    """Получает имя пользователя для fallback логики."""
    if not message.from_user:
        return "Unknown User"

    # Используем display name или username
    name = (
        message.from_user.full_name or message.from_user.username or f"User_{message.from_user.id}"
    )
    return name.strip()


async def _create_direct_meeting() -> str:
    """Создает или получает встречу для прямых коммитов."""
    # Импортируем здесь чтобы избежать циклических зависимостей
    from app.bot.handlers_direct_commit import _create_direct_meeting as create_meeting

    return await create_meeting()


async def _save_commit_to_notion(commit_data: dict) -> dict[str, Any]:
    """Сохраняет коммит в Notion и возвращает созданную запись."""
    try:
        # Создаем встречу для прямых коммитов
        meeting_page_id = await _create_direct_meeting()

        # Сохраняем коммит асинхронно
        result = await upsert_commits_async(meeting_page_id, [commit_data])

        logger.info(f"Saved LLM commit: {result}")

        # Получаем ID созданного коммита
        if result.get("created"):
            # Получаем полные данные коммита из Notion для форматирования
            from app.core.clients import get_notion_client
            from app.settings import settings

            client = get_notion_client()
            try:
                response = client.databases.query(
                    database_id=settings.commits_db_id or "",
                    filter={"property": "Key", "rich_text": {"equals": commit_data["key"]}},
                    page_size=1,
                )

                if hasattr(response, "get") and response.get("results"):
                    page = response["results"][0]  # type: ignore[index]
                    return _map_commit_page(page)

            finally:
                # Notion SDK клиент не требует явного закрытия
                pass

        # Fallback: возвращаем исходные данные
        return commit_data

    except Exception as e:
        logger.error(f"Error saving LLM commit: {e}")
        raise RuntimeError(f"Ошибка сохранения коммита: {e}") from e


@router.message(F.text.regexp(r"^/llm\s+.+$"))
async def llm_commit_handler(message: Message) -> None:
    """Обрабатывает команду /llm для создания коммитов через LLM парсинг."""
    try:
        if not message.text:
            await message.answer("❌ Ошибка: отсутствует текст команды")
            return

        # Извлекаем текст после /llm
        text = message.text[4:].strip()  # Убираем "/llm"
        if not text:
            await message.answer(
                "⚠️ <b>Укажите текст коммита</b>\n\n"
                "💡 <b>Примеры:</b>\n"
                "• <code>/llm Саша подготовит презентацию к 5 октября</code>\n"
                "• <code>/llm Сделать для Катанова слайды до среды</code>\n"
                "• <code>/llm Я созвонюсь с клиентом завтра</code>",
                parse_mode="HTML",
            )
            return

        user_name = _get_user_name(message)
        user_id = message.from_user.id if message.from_user else "unknown"

        logger.info(f"User {user_id} ({user_name}) started LLM commit: '{text}'")

        # Показываем что обрабатываем
        processing_msg = await message.answer(
            "🤖 <b>Обрабатываю коммит...</b>\n\n" "⏳ Анализирую текст через LLM...",
            parse_mode="HTML",
        )

        try:
            # 1. Парсинг через LLM в executor (пока синхронный)
            commit_data = await asyncio.get_event_loop().run_in_executor(
                None, lambda: parse_commit_text(text, user_name)
            )

            # 2. Сохранение в Notion
            await processing_msg.edit_text(
                "🤖 <b>Обрабатываю коммит...</b>\n\n" "💾 Сохраняю в Notion...", parse_mode="HTML"
            )

            notion_commit = await _save_commit_to_notion(commit_data)

            # 3. Форматированный ответ
            card = format_commit_card(notion_commit, device_type="mobile")

            await processing_msg.edit_text(
                f"🤖 <b>LLM коммит создан</b>\n\n{card}", parse_mode="HTML"
            )

            logger.info(
                f"LLM commit created by user {user_id}: '{commit_data['text']}' "
                f"from {commit_data['from_person']} to {commit_data['assignees']}, "
                f"due {commit_data['due_iso'] or 'none'}"
            )

        except ValueError as e:
            # Ошибки валидации
            await processing_msg.edit_text(
                f"⚠️ <b>Ошибка валидации</b>\n\n"
                f"<code>{str(e)}</code>\n\n"
                f"💡 Попробуйте переформулировать задачу",
                parse_mode="HTML",
            )
            logger.warning(f"LLM commit validation error for user {user_id}: {e}")

        except RuntimeError as e:
            # Ошибки LLM или Notion
            await processing_msg.edit_text(
                f"❌ <b>Ошибка обработки</b>\n\n"
                f"<code>{str(e)}</code>\n\n"
                f"🔄 Попробуйте позже или используйте <code>/commit</code>",
                parse_mode="HTML",
            )
            logger.error(f"LLM commit processing error for user {user_id}: {e}")

        except Exception as e:
            # Неожиданные ошибки
            await processing_msg.edit_text(
                f"❌ <b>Неожиданная ошибка</b>\n\n"
                f"<code>{str(e)}</code>\n\n"
                f"🔄 Попробуйте позже или обратитесь к администратору",
                parse_mode="HTML",
            )
            logger.error(f"Unexpected error in LLM commit for user {user_id}: {e}")

    except Exception as e:
        # Ошибка на уровне handler
        logger.error(f"Handler error in llm_commit_handler: {e}")
        await message.answer(
            "❌ <b>Критическая ошибка</b>\n\n" "Обратитесь к администратору", parse_mode="HTML"
        )
