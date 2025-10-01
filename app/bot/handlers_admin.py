"""Административные команды бота.

Включает команды для управления системой тегирования и диагностики.
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.core.clients import clear_clients_cache, get_clients_info
from app.core.metrics import snapshot as get_metrics_snapshot
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


@router.message(F.text == "/metrics")
async def metrics_handler(message: Message) -> None:
    """Показывает общие метрики производительности системы."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        snapshot = get_metrics_snapshot()

        # Функция для форматирования латентности
        def format_latency(name: str) -> str:
            lat = snapshot.latency.get(name, {})
            if lat.get("count", 0) == 0:
                return f"{name}: нет данных"
            return (
                f"{name}: n={lat.get('count', 0)} "
                f"avg={lat.get('avg', 0):.1f}ms "
                f"p95={lat.get('p95', 0):.1f}ms "
                f"p99={lat.get('p99', 0):.1f}ms"
            )

        # Функция для форматирования токенов LLM
        def format_llm_tokens(name: str) -> str:
            tokens = snapshot.llm_tokens.get(name, {})
            if tokens.get("calls", 0) == 0:
                return f"{name}: нет вызовов"
            return (
                f"{name}: {tokens.get('calls', 0)} вызовов, "
                f"{tokens.get('total_tokens', 0):,} токенов "
                f"(prompt: {tokens.get('prompt_tokens', 0):,}, "
                f"completion: {tokens.get('completion_tokens', 0):,})"
            )

        metrics_text = (
            f"📊 <b>Метрики производительности</b>\n\n"
            f"🤖 <b>LLM операции:</b>\n"
            f"📝 {format_latency('llm.summarize')}\n"
            f"📋 {format_latency('llm.extract_commits')}\n"
            f"🧠 {format_latency('llm.commit_parse')}\n\n"
            f"💰 <b>LLM токены:</b>\n"
            f"📝 {format_llm_tokens('llm.summarize')}\n"
            f"📋 {format_llm_tokens('llm.extract_commits')}\n"
            f"🧠 {format_llm_tokens('llm.commit_parse')}\n\n"
            f"📁 <b>Обработка файлов:</b>\n"
            f"📄 {format_latency('ingest.extract')}\n\n"
            f"🗄️ <b>Notion API:</b>\n"
            f"📅 {format_latency('notion.create_meeting')}\n"
            f"📝 {format_latency('notion.upsert_commits')}\n"
            f"🔍 {format_latency('notion.query_commits')}\n"
            f"✅ {format_latency('notion.update_commit_status')}\n\n"
            f"♻️ <b>Дедупликация встреч:</b>\n"
            f"🎯 Попадания: {snapshot.counters.get('meetings.dedup.hit', 0)}\n"
            f"🆕 Промахи: {snapshot.counters.get('meetings.dedup.miss', 0)}\n\n"
            f"🏷️ <b>Тегирование:</b>\n"
            f"🎯 {format_latency('tagging.tag_text')}\n\n"
        )

        # Добавляем ошибки если есть
        if snapshot.errors:
            metrics_text += "❌ <b>Ошибки:</b>\n"
            for error_name, count in list(snapshot.errors.items())[:5]:  # Топ-5 ошибок
                metrics_text += f"   • {error_name}: {count}\n"
        else:
            metrics_text += "✅ <b>Ошибок нет</b>\n"

        # Добавляем счетчики успешных операций
        success_counters = {k: v for k, v in snapshot.counters.items() if k.endswith(".success")}
        if success_counters:
            metrics_text += "\n🎯 <b>Успешные операции:</b>\n"
            for counter_name, count in list(success_counters.items())[:5]:
                clean_name = counter_name.replace(".success", "")
                metrics_text += f"   • {clean_name}: {count}\n"

        await message.answer(metrics_text, parse_mode="HTML")
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested metrics")

    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        await message.answer("❌ <b>Ошибка получения метрик</b>\n\n" f"<code>{str(e)}</code>")


@router.message(F.text == "/dedup_status")
async def dedup_status_handler(message: Message) -> None:
    """Показывает статус дедупликации встреч."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.metrics import snapshot
        from app.settings import settings

        snap = snapshot()

        # Статистика дедупликации
        hits = snap.counters.get("meetings.dedup.hit", 0)
        misses = snap.counters.get("meetings.dedup.miss", 0)
        total = hits + misses
        hit_rate = (hits / total * 100) if total > 0 else 0

        status_text = (
            f"♻️ <b>Статус дедупликации встреч</b>\n\n"
            f"🎛️ <b>Статус:</b> {'🟢 Включена' if settings.enable_meetings_dedup else '🔴 Отключена'}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"🎯 Попадания: {hits}\n"
            f"🆕 Промахи: {misses}\n"
            f"📈 Hit rate: {hit_rate:.1f}%\n"
            f"📋 Всего операций: {total}\n\n"
        )

        if settings.enable_meetings_dedup:
            status_text += (
                "✅ <b>Дедупликация активна</b>\n"
                "• Повторные загрузки обновляют существующие встречи\n"
                "• Теги и участники объединяются\n"
                "• Summary MD перезаписывается\n\n"
                "🔧 Отключить: <code>/dedup_toggle</code>"
            )
        else:
            status_text += (
                "⚠️ <b>Дедупликация отключена</b>\n"
                "• Каждая загрузка создает новую встречу\n"
                "• Возможны дубликаты в базе данных\n\n"
                "🔧 Включить: <code>/dedup_toggle</code>"
            )

        await message.answer(status_text, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested dedup status")

    except Exception as e:
        logger.error(f"Error in dedup_status_handler: {e}")
        await message.answer(f"❌ <b>Ошибка получения статуса</b>\n\n<code>{str(e)}</code>")


@router.message(F.text == "/dedup_toggle")
async def dedup_toggle_handler(message: Message) -> None:
    """Переключает состояние дедупликации встреч."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.settings import settings

        # Переключаем состояние
        old_state = settings.enable_meetings_dedup
        settings.enable_meetings_dedup = not old_state
        new_state = settings.enable_meetings_dedup

        # Формируем ответ
        if new_state:
            description = (
                "✅ <b>Дедупликация встреч включена</b>\n\n"
                "📋 <b>Что изменилось:</b>\n"
                "• Повторные загрузки будут обновлять существующие встречи\n"
                "• Теги и участники будут объединяться\n"
                "• Summary MD будет перезаписываться\n\n"
                "🔧 Отключить: <code>/dedup_toggle</code>"
            )
        else:
            description = (
                "⚠️ <b>Дедупликация встреч отключена</b>\n\n"
                "📋 <b>Что изменилось:</b>\n"
                "• Каждая загрузка будет создавать новую встречу\n"
                "• Возможны дубликаты в базе данных\n"
                "• Рекомендуется только для отладки\n\n"
                "🔧 Включить: <code>/dedup_toggle</code>"
            )

        await message.answer(description, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} toggled meetings dedup: {old_state} → {new_state}")

    except Exception as e:
        logger.error(f"Error in dedup_toggle_handler: {e}")
        await message.answer(f"❌ <b>Ошибка переключения</b>\n\n<code>{str(e)}</code>")


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
        "📊 <b>Мониторинг:</b>\n"
        "📈 <code>/metrics</code> - Общие метрики производительности системы\n"
        "🏷️ <code>/tags_stats</code> - Детальная статистика системы тегирования\n\n"
        "🏷️ <b>Система тегирования:</b>\n"
        "♻️ <code>/reload_tags</code> - Перезагрузить правила тегирования из YAML\n"
        "✅ <code>/tags_validate</code> - Валидировать YAML файл правил\n"
        "🧹 <code>/clear_cache</code> - Очистить LRU кэш результатов\n"
        "🧪 <code>/test_tags &lt;текст&gt;</code> - Протестировать scored тэггер\n\n"
        "🔄 <b>Retag функции:</b>\n"
        "🔍 <code>/retag &lt;meeting_id&gt; dry-run</code> - Показать diff тегов\n"
        "♻️ <code>/retag &lt;meeting_id&gt;</code> - Пересчитать и обновить теги\n"
        "🏷️ <code>/review_tags &lt;meeting_id&gt;</code> - Интерактивное ревью тегов\n\n"
        "🆕 <b>Массовое перетегирование:</b>\n"
        "🔄 <code>/retag_all [параметры]</code> - Массовое обновление тегов\n"
        "   💡 <i>Пример: /retag_all meetings dry=1</i>\n"
        "❓ <code>/retag_help</code> - Подробная справка по перетегированию\n"
        "   📋 Параметры: meetings|commits, since=дата, limit=N, mode=v0|v1|both, dry=0|1\n\n"
        "⚡ <b>Производительность клиентов:</b>\n"
        "📊 <code>/clients_stats</code> - Статистика клиентов и connection pooling\n"
        "🧹 <code>/clients_cleanup</code> - Очистка кэша Notion SDK клиентов\n\n"
        "🔄 <b>Notion синхронизация:</b>\n"
        "📥 <code>/sync_tags</code> - Синхронизировать правила из Notion Tag Catalog\n"
        "🔍 <code>/sync_tags dry-run</code> - Проверить синхронизацию без применения\n"
        "📊 <code>/sync_status</code> - Статус последней синхронизации\n\n"
        "👥 <b>Управление людьми:</b>\n"
        "🧩 <code>/people_miner</code> - Интерактивная верификация кандидатов (v1)\n"
        "🆕 <code>/people_miner2 [freq|date]</code> - People Miner v2 с улучшенным UX\n"
        "📊 <code>/people_stats</code> - Статистика людей и кандидатов\n"
        "📈 <code>/people_stats_v2</code> - Подробная статистика People Miner v2\n"
        "📈 <code>/people_activity</code> - Рейтинг активности людей в коммитах\n"
        "🔄 <code>/people_reset</code> - Сбросить состояние People Miner v1\n"
        "🧹 <code>/people_clear_v2</code> - Очистить кандидатов People Miner v2\n\n"
        "📋 <b>Статистика повесток:</b>\n"
        "📊 <code>/agenda_stats</code> - Статистика использования agenda системы\n\n"
        "🎨 <b>Форматирование:</b>\n"
        "📱 <code>/adaptive_demo</code> - Демонстрация адаптивного форматирования\n"
        "📱 <code>/adaptive_demo mobile</code> - Показать форматирование для мобильного\n\n"
        "♻️ <b>Дедупликация встреч:</b>\n"
        "🎛️ <code>/dedup_status</code> - Статус дедупликации встреч\n"
        "🔧 <code>/dedup_toggle</code> - Включить/отключить дедупликацию\n\n"
        "🔧 <b>Настройки и диагностика:</b>\n"
        "❓ <code>/admin_help</code> - Показать эту справку\n"
        "🔧 <code>/admin_config</code> - Показать настройки админских прав\n\n"
        "⚠️ <b>Важно:</b>\n"
        "• Команды массового обновления всегда начинайте с dry=1\n"
        "• Большие операции могут занять несколько минут\n"
        "• Все действия логируются для аудита\n\n"
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


@router.message(F.text == "/clients_stats")
async def clients_stats_handler(message: Message) -> None:
    """Показывает статистику кэширования HTTP клиентов."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        # Получаем информацию о клиентах
        clients_info = get_clients_info()

        # Статистика кэша HTTP клиентов
        http_cache = clients_info["cache_info"]["notion_http_client"]

        stats_text = "⚡ <b>Статистика клиентов</b>\n\n" "📊 <b>HTTP клиенты:</b>\n"

        if isinstance(http_cache, dict):
            stats_text += (
                f"   🎯 Hit ratio: {http_cache.get('hit_ratio', 0):.1%}\n"
                f"   ✅ Hits: {http_cache.get('hits', 0)}\n"
                f"   ❌ Misses: {http_cache.get('misses', 0)}\n"
                f"   📦 Размер: {http_cache.get('size', 0)}/{http_cache.get('maxsize', 0)}\n"
                f"   ⏰ TTL: {http_cache.get('ttl_seconds', 0)}s\n\n"
            )

            # Детали записей в кэше
            entries = http_cache.get("entries", [])
            if entries:
                stats_text += f"📋 <b>Записи в кэше ({len(entries)}):</b>\n"
                for entry in entries[:3]:  # Показываем первые 3
                    stats_text += (
                        f"   • {entry['key']}: возраст {entry['age_seconds']:.1f}s, "
                        f"доступов {entry['access_count']}, "
                        f"истекает через {entry['expires_in']:.1f}s\n"
                    )
                if len(entries) > 3:
                    stats_text += f"   ... и еще {len(entries) - 3}\n"
        else:
            stats_text += f"   ℹ️ {http_cache}\n"

        # Информация о Notion SDK клиентах (они кэшируются безопасно)
        notion_cache = clients_info["cache_info"]["notion_client"]
        if isinstance(notion_cache, dict):
            stats_text += (
                f"\n🏗️ <b>Notion SDK клиенты:</b>\n"
                f"   🎯 Hit ratio: {notion_cache.get('hit_ratio', 0):.1%}\n"
                f"   ✅ Hits: {notion_cache.get('hits', 0)}\n"
                f"   ❌ Misses: {notion_cache.get('misses', 0)}\n"
                f"   📦 Размер: {notion_cache.get('currsize', 0)}/{notion_cache.get('maxsize', 0)}\n"
            )

        await message.answer(stats_text, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested clients stats")

    except Exception as e:
        logger.error(f"Error in clients_stats_handler: {e}")
        await message.answer(
            f"❌ <b>Ошибка получения статистики клиентов</b>\n\n<code>{str(e)}</code>"
        )


@router.message(F.text == "/clients_cleanup")
async def clients_cleanup_handler(message: Message) -> None:
    """Принудительная очистка кэша клиентов."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        # Получаем статистику до очистки
        clients_info_before = get_clients_info()
        http_cache_before = clients_info_before["cache_info"]["notion_http_client"]

        before_size = 0
        if isinstance(http_cache_before, dict):
            before_size = http_cache_before.get("size", 0)

        # Выполняем очистку
        clear_clients_cache()

        # Получаем статистику после очистки
        clients_info_after = get_clients_info()
        http_cache_after = clients_info_after["cache_info"]["notion_http_client"]

        after_size = 0
        if isinstance(http_cache_after, dict):
            after_size = http_cache_after.get("size", 0)

        cleanup_text = (
            "🧹 <b>Очистка кэша клиентов завершена</b>\n\n"
            "📊 <b>Результат:</b>\n"
            "   💾 Notion SDK кэш очищен\n"
            "   🔄 HTTP клиенты: создаются новые (не кэшируются)\n"
            "   🌐 Connection pooling: TCP соединения переиспользуются\n\n"
            "✅ Система готова к работе\n"
        )

        await message.answer(cleanup_text, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} performed clients cleanup: {before_size} → {after_size}")

    except Exception as e:
        logger.error(f"Error in clients_cleanup_handler: {e}")
        await message.answer(f"❌ <b>Ошибка очистки кэша клиентов</b>\n\n<code>{str(e)}</code>")


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


@router.message(F.text.regexp(r"^/adaptive_demo(\s+(mobile|tablet|desktop))?$"))
async def adaptive_demo_handler(message: Message) -> None:
    """Демонстрирует адаптивное форматирование для разных устройств."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        # Парсим device_type из команды
        parts = (message.text or "").strip().split()
        device_type = parts[1] if len(parts) > 1 else None

        from app.bot.formatters import (
            DEVICE_LIMITS,
            format_adaptive_demo,
            format_commit_card,
            format_meeting_card,
        )

        # Пример данных
        sample_meeting = {
            "title": "Финансовое планирование и бюджетирование на Q4 2025 с обсуждением IFRS стандартов",
            "date": "2025-09-23",
            "attendees": [
                "Valya Dobrynin",
                "Nodari Kezua",
                "Sergey Lompa",
                "Vlad Sklyanov",
                "Serezha Ustinenko",
                "Ivan Petrov",
            ],
            "tags": [
                "Finance/IFRS",
                "Finance/Budget",
                "Business/Market",
                "Topic/Planning",
                "People/Valya Dobrynin",
            ],
            "url": "https://notion.so/sample-meeting-12345",
        }

        sample_commit = {
            "text": "Подготовить детальный отчет по продажам и маркетинговым активностям за Q3 с анализом конверсии",
            "status": "open",
            "direction": "theirs",
            "assignees": ["Daniil Petrov", "Maria Sidorova"],
            "due_iso": "2025-10-15",
            "confidence": 0.85,
            "short_id": "abc123def456ghi789",
        }

        if device_type:
            # Показываем для конкретного устройства
            limits = DEVICE_LIMITS.get(device_type, DEVICE_LIMITS["tablet"])

            await message.answer(
                f"📱 <b>Адаптивное форматирование для {device_type.title()}</b>\n\n"
                f"🎯 <b>Лимиты:</b> title={limits.title}, desc={limits.description}, "
                f"attendees={limits.attendees}, tags={limits.tags}, id={limits.id_length}",
                parse_mode="HTML",
            )

            # Встреча
            meeting_formatted = format_meeting_card(sample_meeting, device_type=device_type)
            await message.answer(f"📅 <b>Встреча:</b>\n\n{meeting_formatted}", parse_mode="HTML")

            # Коммит
            commit_formatted = format_commit_card(sample_commit, device_type=device_type)
            await message.answer(f"📝 <b>Коммит:</b>\n\n{commit_formatted}", parse_mode="HTML")
        else:
            # Показываем сравнение всех устройств
            await message.answer(
                "🎨 <b>Демонстрация адаптивного форматирования</b>\n\n"
                "📱 Сравнение для разных устройств:",
                parse_mode="HTML",
            )

            # Встречи для всех устройств
            demo_results = format_adaptive_demo(sample_meeting)
            for _device, formatted in demo_results.items():
                await message.answer(formatted, parse_mode="HTML")

            # Лимиты
            limits_text = "🎯 <b>Адаптивные лимиты:</b>\n\n"
            for device, limits in DEVICE_LIMITS.items():
                limits_text += (
                    f"📱 <b>{device.title()}:</b> "
                    f"title={limits.title}, desc={limits.description}, "
                    f"attendees={limits.attendees}, tags={limits.tags}\n"
                )

            await message.answer(limits_text, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} used adaptive demo with device_type={device_type}")

    except Exception as e:
        logger.error(f"Error in adaptive_demo_handler: {e}")
        await message.answer(
            f"❌ <b>Ошибка демонстрации</b>\n\n<code>{str(e)}</code>", parse_mode="HTML"
        )


@router.message(F.text == "/people_activity")
async def people_activity_handler(message: Message) -> None:
    """Показывает рейтинг активности людей в коммитах."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.people_activity import (
            get_cache_info,
            get_people_activity_stats,
            get_top_people_by_activity,
        )

        # Получаем статистику активности
        people_stats = get_people_activity_stats()
        top_people = get_top_people_by_activity(min_count=1, max_count=20, min_score=0)
        cache_info = get_cache_info()

        activity_text = (
            f"📈 <b>Рейтинг активности людей</b>\n\n"
            f"📊 <b>Общая статистика:</b>\n"
            f"   👥 Всего людей: {len(people_stats)}\n"
            f"   🏆 В топе: {len(top_people)}\n"
            f"   💾 Кэш: {cache_info.get('hits', 0)} hits, {cache_info.get('misses', 0)} misses\n\n"
        )

        if top_people:
            activity_text += "🏆 <b>Топ-10 по активности:</b>\n"
            for i, person in enumerate(top_people[:10], 1):
                stats = people_stats.get(person, {"assignee": 0, "from_person": 0})
                assignee_count = stats["assignee"]
                from_person_count = stats["from_person"]
                total = assignee_count + from_person_count

                activity_text += (
                    f"   {i:2}. <b>{person}</b>: {total} "
                    f"(👤{assignee_count} + 📝{from_person_count})\n"
                )
        else:
            activity_text += "ℹ️ Нет данных об активности людей"

        await message.answer(activity_text, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested people activity stats")

    except Exception as e:
        logger.error(f"Error in people_activity_handler: {e}")
        await message.answer(
            f"❌ <b>Ошибка получения статистики активности</b>\n\n<code>{str(e)}</code>",
            parse_mode="HTML",
        )


@router.message(F.text == "/agenda_stats")
async def agenda_stats_handler(message: Message) -> None:
    """Показывает статистику использования agenda системы."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.metrics import snapshot
        from app.core.people_activity import (
            get_other_people,
            get_people_activity_stats,
            get_top_people_by_activity,
        )

        # Получаем данные для статистики
        people_stats = get_people_activity_stats()
        top_people = get_top_people_by_activity()
        other_people = get_other_people(exclude_top=top_people)

        # Получаем метрики использования agenda
        metrics = snapshot()
        agenda_metrics = {k: v for k, v in metrics.counters.items() if "agenda" in k.lower()}

        stats_text = (
            f"📊 <b>Статистика Agenda системы</b>\n\n"
            f"👥 <b>Люди в системе:</b>\n"
            f"   🏆 Топ людей: {len(top_people)}\n"
            f"   👥 Other people: {len(other_people)}\n"
            f"   📊 Всего с активностью: {len(people_stats)}\n\n"
        )

        if top_people:
            stats_text += f"🏆 <b>Текущий топ-{len(top_people)}:</b>\n"
            for i, person in enumerate(top_people, 1):
                stats_text += f"   {i}. {person}\n"
            stats_text += "\n"

        if agenda_metrics:
            stats_text += "📈 <b>Метрики использования:</b>\n"
            for metric, count in sorted(agenda_metrics.items()):
                stats_text += f"   • {metric}: {count}\n"
        else:
            stats_text += "ℹ️ Нет метрик использования agenda\n"

        await message.answer(stats_text, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested agenda stats")

    except Exception as e:
        logger.error(f"Error in agenda_stats_handler: {e}")
        await message.answer(
            f"❌ <b>Ошибка получения статистики agenda</b>\n\n<code>{str(e)}</code>",
            parse_mode="HTML",
        )


# ====== RETAGGING PIPELINE COMMANDS ======


@router.message(F.text.regexp(r"^/retag_all\b"))
async def retag_all_handler(message: Message) -> None:
    """
    Массовое перетегирование встреч или коммитов.

    Синтаксис: /retag_all [meetings|commits] [since=YYYY-MM-DD] [limit=N] [mode=v0|v1|both] [dry=0|1]

    Примеры:
    /retag_all meetings dry=1
    /retag_all commits since=2024-12-01 limit=100 mode=both dry=0
    """
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        # Парсим аргументы команды
        text = message.text or ""
        args = text.split()[1:]  # Убираем /retag_all

        # Значения по умолчанию
        db = "meetings"
        since_iso = None
        limit = None
        mode = "both"
        dry_run = True

        # Парсим аргументы
        for arg in args:
            if arg in ("meetings", "commits"):
                db = arg
            elif arg.startswith("since="):
                since_iso = arg.split("=", 1)[1]
            elif arg.startswith("limit="):
                try:
                    limit = int(arg.split("=", 1)[1])
                except ValueError:
                    await message.answer(f"❌ Неверный формат лимита: {arg}")
                    return
            elif arg.startswith("mode="):
                mode = arg.split("=", 1)[1]
            elif arg.startswith("dry="):
                dry_value = arg.split("=", 1)[1]
                dry_run = dry_value != "0"

        # Валидируем параметры
        from app.core.retag_service import estimate_retag_time, validate_retag_params

        is_valid, error_msg = validate_retag_params(db, since_iso, limit, mode)
        if not is_valid:
            await message.answer(f"❌ {error_msg}")
            return

        # Показываем оценку времени для больших операций
        if not dry_run and (limit is None or limit > 100):
            estimate = estimate_retag_time(db, since_iso, limit)
            await message.answer(
                f"⚠️ <b>Массовое обновление {db}</b>\n\n"
                f"📊 Примерная оценка:\n"
                f"• Записей: ~{estimate['estimated_items']}\n"
                f"• Время: ~{estimate['estimated_time_minutes']} мин\n\n"
                f"🔄 Начинаю обработку..."
            )

        # Выполняем операцию
        # Приводим типы для mypy
        from typing import Literal, cast

        from app.core.retag_service import retag

        db_typed = cast(
            Literal["meetings", "commits"], db if db in ("meetings", "commits") else "meetings"
        )
        mode_typed = cast(
            Literal["v0", "v1", "both"], mode if mode in ("v0", "v1", "both") else "both"
        )

        stats = retag(
            db=db_typed, since_iso=since_iso, limit=limit, mode=mode_typed, dry_run=dry_run
        )

        # Форматируем результат
        dry_prefix = "🧪 [DRY-RUN] " if dry_run else "✅ "

        result_message = (
            f"{dry_prefix}<b>Retag {db} завершен</b>\n\n"
            f"📊 <b>Обработано:</b>\n"
            f"• Просканировано: {stats.scanned}\n"
            f"• Обновлено: {stats.updated}\n"
            f"• Пропущено: {stats.skipped}\n"
            f"• Ошибок: {stats.errors}\n\n"
            f"⏱️ <b>Производительность:</b>\n"
            f"• Общее время: {stats.latency_s:.1f}с\n"
            f"• Среднее на запись: {stats.avg_processing_time_ms:.1f}мс\n\n"
            f"🏷️ <b>Теги:</b>\n"
            f"• До: {stats.total_tags_before}\n"
            f"• После: {stats.total_tags_after}\n"
        )

        # Добавляем детали дедупликации если есть
        if stats.dedup_metrics_total:
            result_message += "\n🔄 <b>Дедупликация:</b>\n"
            for key, value in stats.dedup_metrics_total.items():
                if isinstance(value, int | float) and value > 0:
                    result_message += f"• {key}: {value}\n"

        await message.answer(result_message, parse_mode="HTML")

        # Логируем операцию
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(
            f"Admin {user_id} executed retag_all: db={db}, since={since_iso}, "
            f"limit={limit}, mode={mode}, dry_run={dry_run}, "
            f"stats={stats.as_dict()}"
        )

    except Exception as e:
        logger.error(f"Error in retag_all_handler: {e}")
        await message.answer(
            f"❌ <b>Ошибка выполнения retag_all</b>\n\n<code>{str(e)}</code>", parse_mode="HTML"
        )


@router.message(F.text == "/retag_help")
async def retag_help_handler(message: Message) -> None:
    """Показывает справку по командам перетегирования."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    help_text = (
        "🔄 <b>Справка по командам перетегирования</b>\n\n"
        "📋 <b>Основная команда:</b>\n"
        "<code>/retag_all [параметры]</code>\n\n"
        "🎛️ <b>Параметры:</b>\n"
        "• <code>meetings</code> или <code>commits</code> - тип базы\n"
        "• <code>since=YYYY-MM-DD</code> - фильтр по дате\n"
        "• <code>limit=N</code> - максимум записей (1-10000)\n"
        "• <code>mode=v0|v1|both</code> - режим тегирования\n"
        "• <code>dry=0|1</code> - тестовый режим (1=да, 0=нет)\n\n"
        "💡 <b>Примеры использования:</b>\n"
        "<code>/retag_all meetings dry=1</code>\n"
        "└ Тестовый прогон всех встреч\n\n"
        "<code>/retag_all commits since=2024-12-01 limit=100</code>\n"
        "└ Коммиты с 1 декабря, максимум 100, тестовый режим\n\n"
        "<code>/retag_all meetings mode=both dry=0</code>\n"
        "└ Реальное обновление всех встреч двойным тегированием\n\n"
        "⚠️ <b>Внимание:</b>\n"
        "• Всегда начинайте с <code>dry=1</code> для проверки\n"
        "• Большие операции могут занять несколько минут\n"
        "• Операция необратима (кроме dry-run режима)\n\n"
        "🔍 <b>Дополнительные команды:</b>\n"
        "<code>/retag_help</code> - эта справка\n"
        "<code>/tags_stats</code> - статистика тегирования\n"
        "<code>/tags_validate</code> - валидация правил\n"
    )

    await message.answer(help_text, parse_mode="HTML")
