"""Административные команды бота.

Включает команды для управления системой тегирования и диагностики.
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.core.tagger_v1_scored import validate_rules
from app.core.tags import clear_cache, get_tagging_stats, reload_tags_rules, tag_text_scored
from app.settings import settings

logger = logging.getLogger(__name__)

router = Router()


def _is_admin(message: Message) -> bool:
    """Проверяет, является ли пользователь администратором."""
    user_id = message.from_user.id if message.from_user else None
    return settings.is_admin(user_id)


@router.message(F.text == "/reload_tags")
async def reload_tags_handler(message: Message) -> None:
    """Перезагружает правила тегирования из YAML файла."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

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
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

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
                f"\n\n🏷️ <b>Tagger v1 Scored:</b>\n"
                f"   • Правил: {v1_stats.get('total_rules', 0)}\n"
                f"   • Паттернов: {v1_stats.get('total_patterns', 0)}\n"
                f"   • Исключений: {v1_stats.get('total_excludes', 0)}\n"
                f"   • Средний вес: {v1_stats.get('average_weight', 0):.2f}\n"
                f"   • Порог score: {stats.get('tags_min_score', 0.5)}"
            )

        # Добавляем производительность
        if "performance" in stats:
            perf = stats["performance"]
            stats_text += (
                f"\n\n⚡ <b>Производительность:</b>\n"
                f"   • Uptime: {perf.get('uptime_hours', 0):.1f}ч\n"
                f"   • Вызовов/час: {perf.get('calls_per_hour', 0):.1f}\n"
                f"   • Среднее время: {perf.get('avg_response_time_ms', 0):.1f}мс"
            )

        # Добавляем топ теги
        if "top_tags" in stats and stats["top_tags"]:
            top_tags = stats["top_tags"][:5]  # Топ-5
            stats_text += "\n\n🔥 <b>Топ теги:</b>\n"
            for tag, count in top_tags:
                stats_text += f"   • {tag}: {count}\n"

        await message.answer(stats_text)
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested tags stats")

    except Exception as e:
        logger.error(f"Failed to get tags stats: {e}")
        await message.answer("❌ <b>Ошибка получения статистики</b>\n\n" f"<code>{str(e)}</code>")


@router.message(F.text == "/clear_cache")
async def clear_cache_handler(message: Message) -> None:
    """Очищает кэш системы тегирования."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

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


@router.message(F.text == "/tags_validate")
async def tags_validate_handler(message: Message) -> None:
    """Валидирует YAML файл правил тегирования."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        errors = validate_rules()

        if not errors:
            await message.answer(
                "✅ <b>YAML валидация пройдена</b>\n\n"
                "Все правила тегирования корректны:\n"
                "• Regex паттерны валидны\n"
                "• Нет дубликатов тегов\n"
                "• Веса в допустимых пределах\n"
                "• Структура файла корректна"
            )
        else:
            # Ограничиваем количество ошибок для читаемости
            display_errors = errors[:20]
            error_text = "\n".join(f"• {error}" for error in display_errors)

            if len(errors) > 20:
                error_text += f"\n\n... и еще {len(errors) - 20} ошибок"

            await message.answer(
                f"❌ <b>Найдены ошибки в YAML ({len(errors)}):</b>\n\n"
                f"{error_text}\n\n"
                f"💡 Исправьте ошибки и выполните /reload_tags"
            )

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} validated YAML rules: {len(errors)} errors found")

    except Exception as e:
        logger.error(f"Error in tags validation: {e}")
        await message.answer(f"❌ <b>Ошибка валидации YAML</b>\n\n<code>{str(e)}</code>")


@router.message(F.text.regexp(r"^/retag\s+([0-9a-f\-]{10,})(\s+dry-run)?$", flags=re.I))
async def retag_handler(message: Message) -> None:
    """Пересчитывает теги для страницы встречи с опциональным dry-run."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        if not message.text:
            await message.answer("❌ Неправильный формат команды")
            return

        # Парсим команду
        match = re.match(r"^/retag\s+([0-9a-f\-]{10,})(\s+dry-run)?$", message.text, re.I)
        if not match:
            await message.answer("❌ Неправильный формат команды")
            return

        meeting_id = match.group(1).strip()
        is_dry_run = bool(match.group(2))

        await message.answer(
            f"🔍 <b>Retag {'(dry-run)' if is_dry_run else ''}</b>\n\n⏳ Получаю данные встречи..."
        )

        # Импортируем функции
        from app.core.tags import tag_text
        from app.gateways.notion_meetings import (
            fetch_meeting_page,
            update_meeting_tags,
            validate_meeting_access,
        )

        # Проверяем доступ к странице
        if not validate_meeting_access(meeting_id):
            await message.answer(f"❌ Страница встречи недоступна: {meeting_id}")
            return

        # Получаем данные страницы
        page_data = fetch_meeting_page(meeting_id)

        # Пересчитываем теги
        summary_md = page_data.get("summary_md", "")
        if not summary_md:
            await message.answer("❌ Нет summary для пересчета тегов")
            return

        new_tags = set(tag_text(summary_md))
        old_tags = set(page_data.get("current_tags", []))

        # Вычисляем diff
        tags_to_add = sorted(new_tags - old_tags)
        tags_to_remove = sorted(old_tags - new_tags)

        # Формируем отчет
        title = page_data.get("title", "Unknown")[:50]
        report_lines = [
            f"📄 <b>Встреча:</b> {title}",
            f"🆔 <b>ID:</b> <code>{meeting_id}</code>",
            f"📊 <b>Старых тегов:</b> {len(old_tags)}",
            f"📊 <b>Новых тегов:</b> {len(new_tags)}",
        ]

        if tags_to_add:
            report_lines.append(f"\n➕ <b>Добавить ({len(tags_to_add)}):</b>")
            for tag in tags_to_add:
                report_lines.append(f"   • <code>{tag}</code>")

        if tags_to_remove:
            report_lines.append(f"\n➖ <b>Удалить ({len(tags_to_remove)}):</b>")
            for tag in tags_to_remove:
                report_lines.append(f"   • <code>{tag}</code>")

        if not tags_to_add and not tags_to_remove:
            report_lines.append("\n✅ <b>Изменений нет</b> - теги актуальны")

        # Выполняем действие
        if is_dry_run or (not tags_to_add and not tags_to_remove):
            # Dry-run или нет изменений
            mode_text = "🔍 <b>Dry-run результат</b>" if is_dry_run else "ℹ️ <b>Результат</b>"
            await message.answer(f"{mode_text}\n\n" + "\n".join(report_lines))
        else:
            # Реальное обновление
            try:
                update_meeting_tags(meeting_id, sorted(new_tags))
                report_lines.insert(0, "♻️ <b>Теги обновлены</b>\n")
                await message.answer("\n".join(report_lines))

                logger.info(
                    f"Retagged meeting {meeting_id}: +{len(tags_to_add)} -{len(tags_to_remove)}"
                )

            except Exception as update_error:
                logger.error(f"Error updating meeting tags: {update_error}")
                await message.answer(
                    f"❌ <b>Ошибка обновления тегов</b>\n\n"
                    f"<code>{str(update_error)}</code>\n\n"
                    f"Используйте dry-run для проверки: <code>/retag {meeting_id} dry-run</code>"
                )

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} executed retag for {meeting_id} (dry-run: {is_dry_run})")

    except Exception as e:
        logger.error(f"Error in retag_handler: {e}")
        await message.answer(f"❌ <b>Ошибка retag</b>\n\n<code>{str(e)}</code>")


@router.message(F.text.regexp(r"^/test_tags\s+.+$"))
async def test_tags_handler(message: Message) -> None:
    """Тестирует scored тэггер на указанном тексте."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        # Извлекаем текст после команды
        text_to_test = (message.text or "").split("/test_tags", 1)[1].strip()

        if not text_to_test:
            await message.answer(
                "❌ Укажите текст для тестирования.\nПример: <code>/test_tags Обсудили IFRS аудит</code>"
            )
            return

        # Получаем scored результаты
        scored_results = tag_text_scored(text_to_test)

        if not scored_results:
            await message.answer(
                f"🏷️ <b>Тест тегирования</b>\n\n📝 Текст: <i>{text_to_test}</i>\n\n❌ Теги не найдены"
            )
            return

        # Формируем ответ
        response_lines = [
            "🏷️ <b>Тест scored тэггера</b>\n",
            f"📝 <b>Текст:</b> <i>{text_to_test}</i>\n",
            f"🎯 <b>Порог:</b> {settings.tags_min_score}\n",
            f"📊 <b>Результаты ({len(scored_results)} тегов):</b>",
        ]

        for tag, score in scored_results:
            status = "✅" if score >= settings.tags_min_score else "❌"
            response_lines.append(f"  {status} <code>{tag}</code>: {score:.2f}")

        # Показываем финальные отфильтрованные теги
        from app.core.tags import tag_text

        final_tags = tag_text(text_to_test)
        if final_tags:
            response_lines.extend(
                [
                    f"\n🏆 <b>Финальные теги ({len(final_tags)}):</b>",
                    *[f"  • <code>{tag}</code>" for tag in final_tags],
                ]
            )

        await message.answer("\n".join(response_lines))

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} tested tags for text: {text_to_test[:50]}...")

    except Exception as e:
        logger.error(f"Error in test_tags_handler: {e}")
        await message.answer(f"❌ <b>Ошибка тестирования тегов</b>\n\n<code>{str(e)}</code>")


@router.message(F.text == "/admin_help")
async def admin_help_handler(message: Message) -> None:
    """Показывает список административных команд."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    help_text = (
        "🔧 <b>Административные команды</b>\n\n"
        "🏷️ <b>Система тегирования:</b>\n"
        "♻️ <code>/reload_tags</code> - Перезагрузить правила тегирования из YAML\n"
        "📊 <code>/tags_stats</code> - Детальная статистика системы тегирования\n"
        "✅ <code>/tags_validate</code> - Валидировать YAML файл правил\n"
        "🧹 <code>/clear_cache</code> - Очистить LRU кэш результатов\n"
        "🧪 <code>/test_tags &lt;текст&gt;</code> - Протестировать scored тэггер\n\n"
        "🔄 <b>Retag функции:</b>\n"
        "🔍 <code>/retag &lt;meeting_id&gt; dry-run</code> - Показать diff тегов\n"
        "♻️ <code>/retag &lt;meeting_id&gt;</code> - Пересчитать и обновить теги\n"
        "🏷️ <code>/review_tags &lt;meeting_id&gt;</code> - Интерактивное ревью тегов\n\n"
        "🔄 <b>Notion синхронизация:</b>\n"
        "📥 <code>/sync_tags</code> - Синхронизировать правила из Notion Tag Catalog\n"
        "🔍 <code>/sync_tags dry-run</code> - Проверить синхронизацию без применения\n"
        "📊 <code>/sync_status</code> - Статус последней синхронизации\n\n"
        "👥 <b>Управление людьми:</b>\n"
        "🧩 <code>/people_miner</code> - Интерактивная верификация кандидатов\n"
        "📊 <code>/people_stats</code> - Статистика людей и кандидатов\n"
        "🔄 <code>/people_reset</code> - Сбросить состояние People Miner\n\n"
        "❓ <code>/admin_help</code> - Показать эту справку\n"
        "🔧 <code>/admin_config</code> - Показать настройки админских прав\n\n"
        "<i>Доступно только администраторам бота</i>"
    )

    await message.answer(help_text)
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(f"Admin {user_id} requested admin help")


@router.message(F.text == "/admin_config")
async def admin_config_handler(message: Message) -> None:
    """Показывает настройки админских прав для диагностики."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.settings import get_admin_config_info

        config = get_admin_config_info()
        current_user = message.from_user.id if message.from_user else None

        config_text = (
            f"🔧 <b>Настройки админских прав</b>\n\n"
            f"👤 <b>Ваш ID:</b> <code>{current_user}</code>\n"
            f"👥 <b>Админы:</b> {config['admin_ids']}\n"
            f"📊 <b>Количество:</b> {config['count']}\n"
            f"📍 <b>Источник:</b> <code>{config['source']}</code>\n"
            f"📁 <b>.env файл:</b> {'✅ Существует' if config['env_file_exists'] else '❌ Отсутствует'}\n\n"
            f"💡 <b>Рекомендуемая настройка:</b>\n"
            f"<code>{config['recommended_setup']}</code>\n\n"
            f"📋 <b>Инструкция:</b>\n"
            f"1. Создайте файл <code>.env</code> в корне проекта\n"
            f"2. Добавьте строку: <code>APP_ADMIN_USER_IDS={current_user}</code>\n"
            f"3. Перезапустите бота\n\n"
            f"🔍 <b>Для получения ID другого пользователя:</b>\n"
            f"Попросите его написать боту /start и проверьте логи"
        )

        await message.answer(config_text)
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested admin config info")

    except Exception as e:
        logger.error(f"Failed to get admin config: {e}")
        await message.answer(f"❌ <b>Ошибка получения настроек</b>\n\n<code>{str(e)}</code>")


@router.message(F.text.regexp(r"^/review_tags\s+([0-9a-f\-]{10,})$"))
async def review_tags_handler(message: Message, state: FSMContext) -> None:
    """Запускает интерактивное ревью тегов для указанной встречи."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        if not message.text:
            await message.answer("❌ Неправильный формат команды")
            return

        # Парсим ID встречи
        match = re.match(r"^/review_tags\s+([0-9a-f\-]{10,})$", message.text)
        if not match:
            await message.answer("❌ Неправильный формат ID встречи")
            return

        meeting_id = match.group(1).strip()

        await message.answer(
            f"🔍 <b>Загружаю теги встречи...</b>\n\n⏳ ID: <code>{meeting_id}</code>"
        )

        # Импортируем функции
        from app.bot.handlers_tags_review import start_tags_review
        from app.gateways.notion_meetings import fetch_meeting_page, validate_meeting_access

        # Проверяем доступ к странице
        if not validate_meeting_access(meeting_id):
            await message.answer(f"❌ Страница встречи недоступна: {meeting_id}")
            return

        # Получаем данные страницы
        page_data = fetch_meeting_page(meeting_id)
        current_tags = page_data.get("current_tags", [])

        if not current_tags:
            await message.answer("❌ У встречи нет тегов для ревью")
            return

        # Запускаем интерактивное ревью
        user_id = message.from_user.id if message.from_user else 0
        await start_tags_review(
            meeting_id=meeting_id,
            original_tags=current_tags,
            user_id=user_id,
            message=message,
            state=state,
        )

        logger.info(f"Admin {user_id} started manual tags review for meeting {meeting_id}")

    except Exception as e:
        logger.error(f"Error in review_tags_handler: {e}")
        await message.answer(f"❌ <b>Ошибка запуска ревью тегов</b>\n\n<code>{str(e)}</code>")


@router.message(F.text.regexp(r"^/sync_tags(\s+dry-run)?$"))
async def sync_tags_handler(message: Message) -> None:
    """Синхронизирует правила тегирования из Notion Tag Catalog."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        if not message.text:
            await message.answer("❌ Неправильный формат команды")
            return

        # Проверяем режим dry-run
        is_dry_run = "dry-run" in message.text

        await message.answer(
            f"🔄 <b>Синхронизация правил тегирования{'(dry-run)' if is_dry_run else ''}</b>\n\n"
            "⏳ Подключаюсь к Notion Tag Catalog..."
        )

        # Импортируем функции синхронизации
        from app.core.tags_notion_sync import smart_sync

        # Выполняем синхронизацию
        result = smart_sync(dry_run=is_dry_run)

        if result.success:
            # Формируем сообщение об успехе
            breakdown_text = (
                ", ".join(
                    f"{kind}={count}" for kind, count in sorted(result.kind_breakdown.items())
                )
                if result.kind_breakdown
                else "нет данных"
            )

            success_message = (
                f"✅ <b>Синхронизация {'проверена' if is_dry_run else 'завершена'}</b>\n\n"
                f"📊 <b>Источник:</b> {result.source}\n"
                f"🏷️ <b>Правил загружено:</b> {result.rules_count}\n"
                f"📋 <b>По категориям:</b> {breakdown_text}\n"
            )

            if result.cache_updated:
                success_message += "💾 <b>Кэш обновлен</b>\n"

            if is_dry_run:
                success_message += "\n💡 Для применения запустите без dry-run"
            else:
                success_message += "\n🎯 Правила активны в тэггере"

            await message.answer(success_message)
        else:
            # Сообщение об ошибке
            error_message = (
                f"❌ <b>Ошибка синхронизации</b>\n\n"
                f"📊 <b>Источник:</b> {result.source}\n"
                f"❌ <b>Ошибка:</b> <code>{result.error}</code>\n\n"
                f"💡 Проверьте настройки Notion или используйте YAML fallback"
            )

            await message.answer(error_message)

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(
            f"Admin {user_id} executed sync_tags (dry_run={is_dry_run}): "
            f"success={result.success}, source={result.source}, count={result.rules_count}"
        )

    except Exception as e:
        logger.error(f"Error in sync_tags_handler: {e}")
        await message.answer(f"❌ <b>Ошибка синхронизации</b>\n\n<code>{str(e)}</code>")


@router.message(F.text == "/sync_status")
async def sync_status_handler(message: Message) -> None:
    """Показывает статус синхронизации правил тегирования."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.tags_notion_sync import get_sync_status
        from app.gateways.notion_tag_catalog import get_tag_catalog_info

        # Получаем статус синхронизации
        sync_status = get_sync_status()
        catalog_info = get_tag_catalog_info()

        # Формируем сообщение
        status_text = (
            f"📊 <b>Статус синхронизации Tag Catalog</b>\n\n"
            f"🕐 <b>Последняя синхронизация:</b> {sync_status.get('last_sync', 'никогда')}\n"
            f"⏱️ <b>Прошло времени:</b> {sync_status.get('hours_since_sync', 0):.1f} часов\n"
            f"📍 <b>Источник:</b> {sync_status.get('source', 'неизвестно')}\n"
            f"✅ <b>Статус:</b> {sync_status.get('status', 'неизвестно')}\n"
            f"🏷️ <b>Правил загружено:</b> {sync_status.get('rules_count', 0)}\n"
        )

        # Добавляем breakdown по категориям
        breakdown = sync_status.get("kind_breakdown", {})
        if breakdown:
            breakdown_text = ", ".join(f"{k}={v}" for k, v in sorted(breakdown.items()))
            status_text += f"📋 <b>По категориям:</b> {breakdown_text}\n"

        # Добавляем статус Notion
        status_text += "\n🔗 <b>Notion Tag Catalog:</b>\n"
        if catalog_info.get("accessible"):
            status_text += (
                f"   ✅ Доступен\n"
                f"   📝 Название: {catalog_info.get('title', 'неизвестно')}\n"
                f"   🔧 Поля: {len(catalog_info.get('properties', []))}\n"
            )
        else:
            status_text += f"   ❌ Недоступен: {catalog_info.get('error', 'неизвестная ошибка')}\n"

        # Добавляем статус кэша
        status_text += f"\n💾 <b>Локальный кэш:</b> {'✅ доступен' if sync_status.get('cache_available') else '❌ отсутствует'}\n"

        # Добавляем ошибку если есть
        if sync_status.get("error"):
            status_text += f"\n❌ <b>Последняя ошибка:</b>\n<code>{sync_status['error']}</code>"

        await message.answer(status_text)

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested sync status")

    except Exception as e:
        logger.error(f"Error in sync_status_handler: {e}")
        await message.answer(f"❌ <b>Ошибка получения статуса</b>\n\n<code>{str(e)}</code>")
