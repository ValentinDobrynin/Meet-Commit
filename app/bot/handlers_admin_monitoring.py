"""
Административные команды для мониторинга и профилирования.

Расширенные команды для Фазы 3: health checks, анализ производительности,
профилирование операций и управление кэшем.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(message: Message) -> bool:
    """Проверяет, является ли пользователь администратором."""
    from app.settings import settings

    if not message.from_user:
        return False
    return settings.is_admin(message.from_user.id)


@router.message(F.text == "/health")
async def health_check_handler(message: Message) -> None:
    """Проверяет состояние внешних сервисов."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.health_checks import format_health_report, run_all_health_checks

        # Уведомляем о начале проверки
        status_msg = await message.answer("🔍 <b>Проверяю состояние сервисов...</b>", parse_mode="HTML")

        # Запускаем health checks
        health = await run_all_health_checks(timeout=15.0)

        # Форматируем отчет
        report = format_health_report(health)

        await status_msg.edit_text(
            f"🏥 <b>Health Check Report</b>\\n\\n{report}", parse_mode="Markdown"
        )

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested health check")

    except Exception as e:
        logger.error(f"Error in health_check_handler: {e}")
        await message.answer(f"❌ <b>Ошибка health check</b>\\n\\n<code>{str(e)}</code>")


@router.message(F.text == "/performance")
async def performance_report_handler(message: Message) -> None:
    """Показывает отчет о производительности."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.profiling import generate_performance_report

        report = generate_performance_report()

        await message.answer(
            f"📊 <b>Отчет о производительности</b>\\n\\n<pre>{report}</pre>", parse_mode="HTML"
        )

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested performance report")

    except Exception as e:
        logger.error(f"Error in performance_report_handler: {e}")
        await message.answer(
            f"❌ <b>Ошибка отчета производительности</b>\\n\\n<code>{str(e)}</code>"
        )


@router.message(F.text == "/bottlenecks")
async def bottlenecks_handler(message: Message) -> None:
    """Анализирует узкие места в производительности."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.profiling import detect_bottlenecks

        bottlenecks = detect_bottlenecks(min_calls=5)

        lines = ["🎯 <b>Анализ узких мест</b>\\n"]

        # Медленные операции
        if bottlenecks["slow_operations"]:
            lines.append("🐌 <b>Медленные операции:</b>")
            for op in bottlenecks["slow_operations"][:5]:
                severity_emoji = "🔴" if op["severity"] == "critical" else "🟡"
                lines.append(
                    f"{severity_emoji} <code>{op['operation']}</code>: {op['avg_ms']:.1f}ms"
                )
            lines.append("")

        # Высокая конкурентность
        if bottlenecks["high_concurrency"]:
            lines.append("⚡ <b>Высокая конкурентность:</b>")
            for op in bottlenecks["high_concurrency"][:3]:
                lines.append(
                    f"🔥 <code>{op['operation']}</code>: пик {op['peak_concurrent']} одновременно"
                )
            lines.append("")

        # Рекомендации
        if bottlenecks["recommendations"]:
            lines.append("💡 <b>Рекомендации:</b>")
            for i, rec in enumerate(bottlenecks["recommendations"], 1):
                lines.append(f"{i}. {rec}")

        if not any([bottlenecks["slow_operations"], bottlenecks["high_concurrency"]]):
            lines.append("✅ <b>Узких мест не обнаружено</b>")
            lines.append("Система работает оптимально")

        await message.answer("\\n".join(lines), parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested bottlenecks analysis")

    except Exception as e:
        logger.error(f"Error in bottlenecks_handler: {e}")
        await message.answer(f"❌ <b>Ошибка анализа узких мест</b>\\n\\n<code>{str(e)}</code>")


@router.message(F.text == "/cache_stats")
async def cache_stats_handler(message: Message) -> None:
    """Показывает статистику кэширования."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.clients import get_clients_info
        from app.core.query_optimizer import get_cache_stats

        # Статистика кэша запросов
        query_cache = get_cache_stats()

        # Статистика кэша клиентов
        clients_info = get_clients_info()
        client_cache = clients_info["cache_info"]

        lines = [
            "💾 <b>Статистика кэширования</b>\\n",
            "🔍 <b>Кэш запросов:</b>",
            f"📊 Всего записей: {query_cache['total_entries']}",
            f"✅ Валидных: {query_cache['valid_entries']}",
            f"⏰ Устаревших: {query_cache['expired_entries']}",
            f"⏱️ TTL: {query_cache['cache_ttl_seconds']}s",
            f"💾 Память: ~{query_cache['memory_usage_estimate'] / 1024:.1f}KB\\n",
            "🔧 <b>Кэш клиентов:</b>",
        ]

        for client_name, cache_info in client_cache.items():
            if hasattr(cache_info, "hits"):
                hit_rate = (
                    cache_info.hits / (cache_info.hits + cache_info.misses) * 100
                    if (cache_info.hits + cache_info.misses) > 0
                    else 0
                )
                lines.append(f"📈 {client_name}: {cache_info.hits} попаданий ({hit_rate:.1f}%)")

        await message.answer("\\n".join(lines), parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} requested cache stats")

    except Exception as e:
        logger.error(f"Error in cache_stats_handler: {e}")
        await message.answer(f"❌ <b>Ошибка статистики кэша</b>\\n\\n<code>{str(e)}</code>")


@router.message(F.text.regexp(r"^/benchmark\\s+(\\w+)$"))
async def benchmark_handler(message: Message) -> None:
    """Запускает бенчмарк производительности."""
    if not _is_admin(message):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        # Извлекаем тип бенчмарка
        text = message.text or ""
        parts = text.split()
        if len(parts) < 2:
            await message.answer("⚠️ Укажите тип бенчмарка: <code>/benchmark commits</code>", parse_mode="HTML")
            return

        benchmark_type = parts[1].lower()

        status_msg = await message.answer(
            f"🏃 <b>Запускаю бенчмарк: {benchmark_type}</b>\\n\\n⏳ Это может занять 10-30 секунд..."
        , parse_mode="HTML")

        if benchmark_type == "commits":
            from app.core.llm_extract_commits import extract_commits
            from app.core.llm_extract_commits_async import extract_commits_async
            from app.core.profiling import benchmark_async_vs_sync

            # Мок функции для бенчмарка
            async def mock_async():
                return await extract_commits_async("Test text", ["User"], "2025-09-26")

            def mock_sync():
                return extract_commits("Test text", ["User"], "2025-09-26")

            # Запускаем бенчмарк (с мокингом для безопасности)
            from unittest.mock import patch

            with patch("app.core.llm_extract_commits.get_openai_client"):
                with patch("app.core.llm_extract_commits_async.get_async_openai_client"):
                    stats = await benchmark_async_vs_sync(
                        "commits_extraction", mock_async, mock_sync, iterations=5
                    )

            # Форматируем результаты
            speedup = stats["comparison"]["speedup"]
            async_time = stats["async"]["duration_ms"]
            sync_time = stats["sync"]["duration_ms"]

            result_text = (
                f"🏆 <b>Бенчмарк: {benchmark_type}</b>\\n\\n"
                f"⚡ Async: {async_time:.1f}ms\\n"
                f"🐌 Sync: {sync_time:.1f}ms\\n"
                f"🚀 Ускорение: {speedup:.1f}x\\n\\n"
                f"{'✅ Async быстрее' if speedup > 1 else '⚠️ Sync быстрее'}"
            )

        else:
            result_text = f"❌ Неизвестный тип бенчмарка: {benchmark_type}\\n\\nДоступные: commits"

        await status_msg.edit_text(result_text, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"Admin {user_id} ran benchmark: {benchmark_type}")

    except Exception as e:
        logger.error(f"Error in benchmark_handler: {e}")
        await message.answer(f"❌ <b>Ошибка бенчмарка</b>\\n\\n<code>{str(e)}</code>")
