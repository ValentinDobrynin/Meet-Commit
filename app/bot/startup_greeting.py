"""Модуль для отправки приветственных сообщений при запуске бота."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot

from app.bot.user_storage import get_user_chat_ids, get_users_count

logger = logging.getLogger(__name__)

# Приветственное сообщение (то же, что в /start)
STARTUP_GREETING = (
    "🤖 <b>Добро пожаловать в Meet-Commit!</b>\n\n"
    "📋 <b>Я помогу вам:</b>\n"
    "• 📝 Суммаризировать встречи через AI\n"
    "• 🎯 Извлечь обязательства и действия\n"
    "• 📊 Сохранить все в Notion с умной организацией\n"
    "• 🔍 Управлять очередью задач на проверку\n\n"
    "📎 <b>Отправьте файл встречи для начала работы</b>\n\n"
    "🎯 <b>Поддерживаемые форматы:</b>\n"
    "• 📄 Текстовые файлы (.txt)\n"
    "• 📋 PDF документы (.pdf)\n"
    "• 📝 Word документы (.docx)\n"
    "• 📺 Субтитры (.vtt, .webvtt)\n\n"
    "💡 <i>Просто перетащите файл в чат или используйте кнопку прикрепления</i>"
)


async def send_startup_greetings(bot: Bot) -> None:
    """
    Отправляет приветственные сообщения всем активным пользователям при запуске бота.

    Args:
        bot: Экземпляр бота для отправки сообщений
    """
    try:
        chat_ids = get_user_chat_ids()
        users_count = get_users_count()

        if not chat_ids:
            logger.info("No active users found for startup greetings")
            return

        logger.info(f"Sending startup greetings to {users_count} active users")

        successful_sends = 0
        failed_sends = 0

        # Отправляем сообщения с небольшой задержкой для соблюдения rate limits
        for i, chat_id in enumerate(chat_ids):
            try:
                await bot.send_message(chat_id=chat_id, text=STARTUP_GREETING, parse_mode="HTML")
                successful_sends += 1
                logger.debug(f"Sent greeting to user {chat_id}")

                # Небольшая задержка между сообщениями (соблюдение rate limits)
                if i < len(chat_ids) - 1:  # Не ждем после последнего сообщения
                    await asyncio.sleep(0.1)  # 100ms задержка

            except Exception as e:
                failed_sends += 1
                logger.warning(f"Failed to send greeting to user {chat_id}: {e}")

                # Если пользователь заблокировал бота, можно удалить его из списка
                if "bot was blocked by the user" in str(e).lower():
                    from app.bot.user_storage import remove_user

                    remove_user(chat_id)
                    logger.info(f"Removed blocked user {chat_id} from active users")

        logger.info(f"Startup greetings completed: {successful_sends} sent, {failed_sends} failed")

    except Exception as e:
        logger.error(f"Error in send_startup_greetings: {e}")


async def send_startup_greetings_safe(bot: Bot) -> None:
    """
    Безопасная версия отправки приветствий с обработкой всех ошибок.

    Args:
        bot: Экземпляр бота для отправки сообщений
    """
    try:
        await send_startup_greetings(bot)
    except Exception as e:
        logger.error(f"Critical error in startup greetings: {e}")
        # Не прерываем запуск бота из-за ошибок в приветствиях
