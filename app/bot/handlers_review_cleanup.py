"""
Обработчики команд для очистки Review Queue.

Включает команды:
- /review_clean - основная команда очистки с подрежимами
- /review_clean_help - справка по командам очистки
"""

from __future__ import annotations

import logging
from datetime import UTC

from aiogram import F, Router
from aiogram.types import Message

from app.core.review_cleanup import CleanupStats
from app.settings import settings

logger = logging.getLogger(__name__)

router = Router()


def _is_admin(message: Message) -> bool:
    """Проверяет, является ли пользователь администратором."""
    user_id = message.from_user.id if message.from_user else None
    return settings.is_admin(user_id)


@router.message(F.text.regexp(r"^/review_clean\b"))
async def review_clean_handler(message: Message) -> None:
    """
    Команда очистки Review Queue.

    Синтаксис: /review_clean [old|dups|status|all] [days=N] [threshold=0.85] [dry-run]

    Примеры:
    /review_clean old days=7
    /review_clean dups threshold=0.9
    /review_clean status resolved
    /review_clean all dry-run
    """
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        # Парсим аргументы команды
        text = message.text or ""
        args = text.split()[1:]  # Убираем /review_clean

        # Значения по умолчанию
        mode = "all"
        days = None
        threshold = None
        target_status = None
        dry_run = True  # По умолчанию dry-run для безопасности

        # Парсим аргументы
        for arg in args:
            if arg in ("old", "dups", "status", "all"):
                mode = arg
            elif arg in ("resolved", "dropped", "pending", "needs-review"):
                target_status = arg
                mode = "status"  # Автоматически переключаемся в режим статуса
            elif arg.startswith("days="):
                try:
                    days = int(arg.split("=", 1)[1])
                except ValueError:
                    await message.answer(f"❌ Неверный формат дней: {arg}")
                    return
            elif arg.startswith("threshold="):
                try:
                    threshold = float(arg.split("=", 1)[1])
                except ValueError:
                    await message.answer(f"❌ Неверный формат порога: {arg}")
                    return
            elif arg == "dry-run":
                dry_run = True
            elif arg == "real":
                dry_run = False

        # Валидируем параметры
        from app.core.review_cleanup import estimate_cleanup_time, validate_cleanup_params

        is_valid, error_msg = validate_cleanup_params(mode, days, threshold)
        if not is_valid:
            await message.answer(f"❌ {error_msg}")
            return

        # Показываем оценку времени для сложных операций
        if mode in ("dups", "all"):
            estimate = estimate_cleanup_time(mode)
            await message.answer(
                f"⚠️ <b>Очистка Review Queue ({mode})</b>\n\n"
                f"📊 Примерная оценка:\n"
                f"• Записей: ~{estimate['estimated_reviews']}\n"
                f"• Время: ~{estimate['estimated_time_minutes']} мин\n"
                f"• Сложность: {estimate['complexity']}\n\n"
                f"🔄 Начинаю {'анализ' if dry_run else 'очистку'}..."
            )

        # Выполняем операцию в зависимости от режима
        from app.core.review_cleanup import (
            auto_archive_old_reviews,
            cleanup_by_status,
            comprehensive_cleanup,
            find_duplicate_reviews,
        )

        if mode == "old":
            # Архивирование старых записей
            stats = auto_archive_old_reviews(days_threshold=days or 14, dry_run=dry_run)
            await _send_archive_report(message, stats, dry_run)

        elif mode == "dups":
            # Поиск дубликатов
            stats = find_duplicate_reviews(similarity_threshold=threshold or 0.85)
            await _send_duplicates_report(message, stats)

        elif mode == "status":
            # Очистка по статусу
            if not target_status:
                await message.answer(
                    "❌ Не указан статус для очистки. Используйте: resolved, dropped, pending"
                )
                return

            stats = cleanup_by_status(target_status=target_status, dry_run=dry_run)
            await _send_status_cleanup_report(message, stats, target_status, dry_run)

        else:  # mode == "all"
            # Комплексная очистка
            results = comprehensive_cleanup(
                archive_days=days or 14, similarity_threshold=threshold or 0.85, dry_run=dry_run
            )
            await _send_comprehensive_report(message, results, dry_run)

        # Логируем операцию
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(
            f"Admin {user_id} executed review_clean: mode={mode}, "
            f"days={days}, threshold={threshold}, dry_run={dry_run}"
        )

    except Exception as e:
        logger.error(f"Error in review_clean_handler: {e}")
        await message.answer(
            f"❌ <b>Ошибка выполнения review_clean</b>\n\n<code>{str(e)}</code>", parse_mode="HTML"
        )


async def _send_archive_report(message: Message, stats: CleanupStats, dry_run: bool) -> None:
    """Отправляет отчет об архивировании."""
    dry_prefix = "🧪 [DRY-RUN] " if dry_run else "✅ "

    report = (
        f"{dry_prefix}<b>Архивирование старых записей</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"• Просканировано: {stats.scanned}\n"
        f"• Заархивировано: {stats.archived}\n"
        f"• Ошибок: {stats.errors}\n\n"
        f"📋 <b>Детали:</b>\n"
        f"• Старые resolved: {stats.old_resolved}\n"
        f"• Старые dropped: {stats.old_dropped}\n\n"
        f"⏱️ <b>Время:</b> {stats.processing_time_s:.1f}с"
    )

    await message.answer(report, parse_mode="HTML")


async def _send_duplicates_report(message: Message, stats: CleanupStats) -> None:
    """Отправляет отчет о найденных дубликатах."""
    report = (
        f"🔍 <b>Поиск дубликатов завершен</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"• Просканировано: {stats.scanned}\n"
        f"• Найдено дубликатов: {stats.duplicates_found}\n"
        f"• Проверок похожести: {stats.similarity_checks}\n"
        f"• Ошибок: {stats.errors}\n\n"
        f"⏱️ <b>Производительность:</b>\n"
        f"• Общее время: {stats.processing_time_s:.1f}с\n"
        f"• Среднее на проверку: {stats.avg_similarity_time_ms:.1f}мс"
    )

    # Добавляем детали дубликатов если найдены
    if stats.duplicate_pairs:
        report += "\n\n🔍 <b>Найденные дубликаты:</b>\n"
        for i, (id1, id2, similarity) in enumerate(stats.duplicate_pairs[:5], 1):
            short_id1 = id1.replace("-", "")[-6:] if id1 else "unknown"
            short_id2 = id2.replace("-", "")[-6:] if id2 else "unknown"
            report += f"{i}. [{short_id1}] ~ [{short_id2}] ({similarity:.1%})\n"

        if len(stats.duplicate_pairs) > 5:
            report += f"... и еще {len(stats.duplicate_pairs) - 5} пар\n"

        report += "\n💡 <i>Используйте /delete &lt;id&gt; для удаления дубликатов</i>"

    await message.answer(report, parse_mode="HTML")


async def _send_status_cleanup_report(
    message: Message, stats: CleanupStats, status: str, dry_run: bool
) -> None:
    """Отправляет отчет об очистке по статусу."""
    dry_prefix = "🧪 [DRY-RUN] " if dry_run else "✅ "

    report = (
        f"{dry_prefix}<b>Очистка по статусу: {status}</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"• Просканировано: {stats.scanned}\n"
        f"• Заархивировано: {stats.archived}\n"
        f"• Ошибок: {stats.errors}\n\n"
        f"⏱️ <b>Время:</b> {stats.processing_time_s:.1f}с"
    )

    await message.answer(report, parse_mode="HTML")


async def _send_comprehensive_report(
    message: Message, results: dict[str, CleanupStats], dry_run: bool
) -> None:
    """Отправляет комплексный отчет об очистке."""
    dry_prefix = "🧪 [DRY-RUN] " if dry_run else "✅ "

    # Суммируем статистику
    total_scanned = sum(stats.scanned for stats in results.values())
    total_archived = sum(stats.archived for stats in results.values())
    total_duplicates = sum(stats.duplicates_found for stats in results.values())
    total_errors = sum(stats.errors for stats in results.values())
    total_time = sum(stats.processing_time_s for stats in results.values())

    report = (
        f"{dry_prefix}<b>Комплексная очистка Review Queue</b>\n\n"
        f"📊 <b>Общие результаты:</b>\n"
        f"• Просканировано: {total_scanned}\n"
        f"• Заархивировано: {total_archived}\n"
        f"• Найдено дубликатов: {total_duplicates}\n"
        f"• Ошибок: {total_errors}\n\n"
        f"⏱️ <b>Время:</b> {total_time:.1f}с\n\n"
    )

    # Добавляем детали по каждой операции
    if "archive" in results:
        archive_stats = results["archive"]
        report += (
            f"🗂️ <b>Архивирование:</b>\n"
            f"• Resolved: {archive_stats.old_resolved}\n"
            f"• Dropped: {archive_stats.old_dropped}\n\n"
        )

    if "duplicates" in results:
        dup_stats = results["duplicates"]
        if dup_stats.duplicate_pairs:
            report += f"🔍 <b>Дубликаты ({len(dup_stats.duplicate_pairs)}):</b>\n"
            for i, (id1, id2, similarity) in enumerate(dup_stats.duplicate_pairs[:3], 1):
                short_id1 = id1.replace("-", "")[-6:] if id1 else "unknown"
                short_id2 = id2.replace("-", "")[-6:] if id2 else "unknown"
                report += f"{i}. [{short_id1}] ~ [{short_id2}] ({similarity:.1%})\n"

            if len(dup_stats.duplicate_pairs) > 3:
                report += f"... и еще {len(dup_stats.duplicate_pairs) - 3} пар\n"

    await message.answer(report, parse_mode="HTML")


@router.message(F.text == "/review_clean_help")
async def review_clean_help_handler(message: Message) -> None:
    """Показывает справку по командам очистки Review Queue."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    help_text = (
        "🧹 <b>Справка по очистке Review Queue</b>\n\n"
        "📋 <b>Основная команда:</b>\n"
        "<code>/review_clean [режим] [параметры]</code>\n\n"
        "🎛️ <b>Режимы очистки:</b>\n"
        "• <code>old</code> - архивировать старые записи\n"
        "• <code>dups</code> - найти дубликаты по содержимому\n"
        "• <code>status</code> - очистить по конкретному статусу\n"
        "• <code>all</code> - комплексная очистка (по умолчанию)\n\n"
        "⚙️ <b>Параметры:</b>\n"
        "• <code>days=N</code> - количество дней для архивирования (по умолчанию 14)\n"
        "• <code>threshold=0.85</code> - порог похожести для дубликатов (0.0-1.0)\n"
        "• <code>dry-run</code> - только анализ без изменений (по умолчанию)\n"
        "• <code>real</code> - реальные изменения (осторожно!)\n\n"
        "💡 <b>Примеры использования:</b>\n\n"
        "<code>/review_clean old days=7</code>\n"
        "└ Архивировать записи старше 7 дней (тестовый режим)\n\n"
        "<code>/review_clean dups threshold=0.9</code>\n"
        "└ Найти дубликаты с похожестью >90%\n\n"
        "<code>/review_clean status resolved</code>\n"
        "└ Архивировать все resolved записи (тестовый режим)\n\n"
        "<code>/review_clean all real</code>\n"
        "└ Полная очистка с реальными изменениями\n\n"
        "⚠️ <b>Важные предупреждения:</b>\n"
        "• Всегда начинайте с тестового режима (dry-run)\n"
        "• Операции архивирования необратимы\n"
        "• Поиск дубликатов может занять время для больших очередей\n"
        "• Рекомендуется делать backup перед массовыми операциями\n\n"
        "🔍 <b>Дополнительные команды:</b>\n"
        "<code>/review_clean_help</code> - эта справка\n"
        "<code>/review</code> - просмотр текущей очереди\n"
        "<code>/admin_help</code> - все административные команды\n"
    )

    await message.answer(help_text, parse_mode="HTML")


@router.message(F.text == "/review_stats")
async def review_stats_handler(message: Message) -> None:
    """Показывает статистику Review Queue."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.review_queue import get_review_stats
        from app.gateways.notion_review import fetch_all_reviews

        # Получаем базовую статистику
        basic_stats = get_review_stats()

        # Получаем расширенную статистику
        all_reviews = fetch_all_reviews()

        # Группируем по статусам
        status_counts: dict[str, int] = {}
        for review in all_reviews:
            status = review.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        # Анализируем возраст записей
        from datetime import datetime

        now = datetime.now(UTC)
        age_groups = {"week": 0, "month": 0, "quarter": 0, "older": 0}

        for review in all_reviews:
            updated_str = review.get("last_edited_time", "")
            if updated_str:
                try:
                    updated_date = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                    days_old = (now - updated_date).days

                    if days_old <= 7:
                        age_groups["week"] += 1
                    elif days_old <= 30:
                        age_groups["month"] += 1
                    elif days_old <= 90:
                        age_groups["quarter"] += 1
                    else:
                        age_groups["older"] += 1
                except ValueError:
                    pass

        stats_text = (
            f"📊 <b>Статистика Review Queue</b>\n\n"
            f"📋 <b>Общая информация:</b>\n"
            f"• Всего записей: {len(all_reviews)}\n"
            f"• Открытых: {basic_stats.get('total_open', 0)}\n\n"
            f"📈 <b>По статусам:</b>\n"
        )

        for status, count in sorted(status_counts.items()):
            emoji = {
                "pending": "⏳",
                "needs-review": "🔍",
                "resolved": "✅",
                "dropped": "❌",
                "archived": "🗂️",
            }.get(status, "📄")
            stats_text += f"• {emoji} {status}: {count}\n"

        stats_text += (
            f"\n📅 <b>По возрасту:</b>\n"
            f"• Неделя: {age_groups['week']}\n"
            f"• Месяц: {age_groups['month']}\n"
            f"• Квартал: {age_groups['quarter']}\n"
            f"• Старше: {age_groups['older']}\n\n"
            f"💡 <i>Используйте /review_clean для очистки старых записей</i>"
        )

        await message.answer(stats_text, parse_mode="HTML")

        # Логируем запрос статистики
        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested review stats")

    except Exception as e:
        logger.error(f"Error in review_stats_handler: {e}")
        await message.answer(
            f"❌ <b>Ошибка получения статистики</b>\n\n<code>{str(e)}</code>", parse_mode="HTML"
        )
