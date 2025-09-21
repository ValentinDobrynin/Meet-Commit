"""Административные команды бота.

Включает команды для управления системой тегирования и диагностики.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from app.core.tags import clear_cache, get_tagging_stats, reload_tags_rules

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text == "/reload_tags")
async def reload_tags_handler(message: Message) -> None:
    """Перезагружает правила тегирования из YAML файла."""
    try:
        rules_count = reload_tags_rules()
        await message.answer(
            f"♻️ <b>Tag rules reloaded</b>\n\n"
            f"📊 <b>{rules_count}</b> категорий загружено\n"
            f"🔄 LRU кэш очищен"
        )
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} reloaded tag rules: {rules_count} categories")

    except Exception as e:
        logger.error(f"Failed to reload tag rules: {e}")
        await message.answer("❌ <b>Ошибка перезагрузки правил</b>\n\n" f"<code>{str(e)}</code>")


@router.message(F.text == "/tags_stats")
async def tags_stats_handler(message: Message) -> None:
    """Показывает статистику системы тегирования."""
    try:
        stats = get_tagging_stats()

        # Формируем сообщение со статистикой
        stats_text = (
            f"📊 <b>Статистика системы тегирования</b>\n\n"
            f"🎯 <b>Режим:</b> {stats['current_mode']}\n"
            f"📈 <b>Вызовы по режимам:</b>\n"
        )

        for mode, count in stats["stats"]["calls_by_mode"].items():
            stats_text += f"   • {mode}: {count}\n"

        stats_text += "\n📋 <b>Вызовы по типам:</b>\n"
        for kind, count in stats["stats"]["calls_by_kind"].items():
            stats_text += f"   • {kind}: {count}\n"

        cache_info = stats["cache_info"]
        stats_text += (
            f"\n💾 <b>Кэш:</b> {cache_info['hits']} hits, "
            f"{cache_info['misses']} misses\n"
            f"📦 <b>Размер:</b> {cache_info['currsize']}/{cache_info['maxsize']}\n"
            f"🔄 <b>Правила маппинга:</b> {stats['mapping_rules']}"
        )

        if "v1_stats" in stats and "error" not in stats["v1_stats"]:
            v1_stats = stats["v1_stats"]
            stats_text += (
                f"\n\n🏷️ <b>Tagger v1:</b>\n"
                f"   • Тегов: {v1_stats.get('total_tags', 0)}\n"
                f"   • Паттернов: {v1_stats.get('total_patterns', 0)}\n"
                f"   • Категорий: {len(v1_stats.get('categories', {}))}"
            )

        await message.answer(stats_text)
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested tags stats")

    except Exception as e:
        logger.error(f"Failed to get tags stats: {e}")
        await message.answer("❌ <b>Ошибка получения статистики</b>\n\n" f"<code>{str(e)}</code>")


@router.message(F.text == "/clear_cache")
async def clear_cache_handler(message: Message) -> None:
    """Очищает кэш системы тегирования."""
    try:
        clear_cache()
        await message.answer(
            "🧹 <b>Кэш очищен</b>\n\n"
            "LRU кэш результатов тегирования сброшен.\n"
            "Следующие запросы будут обрабатываться заново."
        )
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} cleared tagging cache")

    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        await message.answer("❌ <b>Ошибка очистки кэша</b>\n\n" f"<code>{str(e)}</code>")


@router.message(F.text == "/admin_help")
async def admin_help_handler(message: Message) -> None:
    """Показывает список административных команд."""
    help_text = (
        "🔧 <b>Административные команды</b>\n\n"
        "🏷️ <b>Система тегирования:</b>\n"
        "♻️ <code>/reload_tags</code> - Перезагрузить правила тегирования из YAML\n"
        "📊 <code>/tags_stats</code> - Статистика системы тегирования\n"
        "🧹 <code>/clear_cache</code> - Очистить LRU кэш результатов\n\n"
        "👥 <b>Управление людьми:</b>\n"
        "🧩 <code>/people_miner</code> - Интерактивная верификация кандидатов\n"
        "📊 <code>/people_stats</code> - Статистика людей и кандидатов\n"
        "🔄 <code>/people_reset</code> - Сбросить состояние People Miner\n\n"
        "❓ <code>/admin_help</code> - Показать эту справку\n\n"
        "<i>Доступно только администраторам бота</i>"
    )

    await message.answer(help_text)
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(f"Admin {user_id} requested admin help")
