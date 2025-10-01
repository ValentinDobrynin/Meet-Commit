"""
Сервис массового перетегирования встреч и коммитов.

Обеспечивает:
- Безопасное массовое обновление тегов в Notion
- Пагинированную обработку больших объемов данных
- Dry-run режим для тестирования изменений
- Детальные метрики и отчетность
- Фильтрацию по дате и лимитам
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Literal

from app.core.tags import tag_text
from app.core.tags_dedup import dedup_fuse
from app.gateways.notion_commits import iter_commits, update_commit_tags
from app.gateways.notion_meetings import iter_meetings, update_meeting_tags

logger = logging.getLogger(__name__)


class RetagStats:
    """Статистика процесса перетегирования."""

    def __init__(self) -> None:
        # Основные счетчики
        self.scanned = 0
        self.updated = 0
        self.skipped = 0
        self.errors = 0

        # Детали обработки
        self.empty_text = 0
        self.no_changes = 0
        self.api_errors = 0

        # Производительность
        self.latency_s = 0.0
        self.avg_processing_time_ms = 0.0

        # Метрики тегирования
        self.total_tags_before = 0
        self.total_tags_after = 0
        self.dedup_metrics_total: dict[str, int] = {}

    def as_dict(self) -> dict[str, Any]:
        """Возвращает статистику в виде словаря."""
        return {
            "summary": {
                "scanned": self.scanned,
                "updated": self.updated,
                "skipped": self.skipped,
                "errors": self.errors,
            },
            "details": {
                "empty_text": self.empty_text,
                "no_changes": self.no_changes,
                "api_errors": self.api_errors,
            },
            "performance": {
                "total_time_s": round(self.latency_s, 2),
                "avg_processing_ms": round(self.avg_processing_time_ms, 2),
            },
            "tagging": {
                "tags_before": self.total_tags_before,
                "tags_after": self.total_tags_after,
                "dedup_metrics": self.dedup_metrics_total,
            },
        }


def _compose_meeting_text(meeting: dict[str, Any]) -> str:
    """
    Составляет текст для тегирования из данных встречи.

    Args:
        meeting: Данные встречи из Notion

    Returns:
        Объединенный текст для анализа
    """
    title = (meeting.get("Name") or "").strip()
    summary = (meeting.get("Summary MD") or "").strip()

    # Объединяем заголовок и содержимое
    parts = [part for part in [title, summary] if part]
    return "\n\n".join(parts)


def _compose_commit_text(commit: dict[str, Any]) -> str:
    """
    Составляет текст для тегирования из данных коммита.

    Args:
        commit: Данные коммита из Notion

    Returns:
        Объединенный текст для анализа
    """
    text = (commit.get("Text") or "").strip()
    context = (commit.get("Context") or "").strip()

    # Объединяем основной текст и контекст
    parts = [part for part in [text, context] if part]
    return "\n\n".join(parts)


def retag(
    *,
    db: Literal["meetings", "commits"] = "meetings",
    since_iso: str | None = None,
    limit: int | None = None,
    mode: Literal["v0", "v1", "both"] = "both",
    dry_run: bool = True,
) -> RetagStats:
    """
    Выполняет массовое перетегирование встреч или коммитов.

    Args:
        db: Тип базы данных ("meetings" или "commits")
        since_iso: Фильтр по дате (ISO формат YYYY-MM-DD)
        limit: Максимальное количество записей для обработки
        mode: Режим тегирования ("v0", "v1", "both")
        dry_run: Если True, только анализирует без обновления

    Returns:
        Статистика выполнения операции
    """
    stats = RetagStats()
    start_time = perf_counter()

    logger.info(
        f"Starting retag operation: db={db}, since={since_iso}, "
        f"limit={limit}, mode={mode}, dry_run={dry_run}"
    )

    try:
        # Выбираем функции в зависимости от типа базы
        if db == "meetings":
            iterator_func = iter_meetings
            update_func = update_meeting_tags
            compose_func = _compose_meeting_text
            tag_kind = "meeting"
        else:  # commits
            iterator_func = iter_commits
            update_func = update_commit_tags
            compose_func = _compose_commit_text  # type: ignore[assignment]
            tag_kind = "commit"

        # Обрабатываем данные батчами
        processed_count = 0
        processing_times = []

        for batch in iterator_func(since_iso=since_iso, page_size=100):
            for item in batch:
                item_start = perf_counter()
                stats.scanned += 1

                try:
                    # Получаем текст для тегирования
                    text = compose_func(item)
                    if not text.strip():
                        stats.empty_text += 1
                        stats.skipped += 1
                        continue

                    # Получаем старые теги
                    old_tags = item.get("Tags") or []
                    stats.total_tags_before += len(old_tags)

                    # Вычисляем новые теги
                    if mode == "both":
                        # Используем новую систему дедупликации
                        tags_v0 = tag_text(text, kind=tag_kind, mode="v0")
                        tags_v1 = tag_text(text, kind=tag_kind, mode="v1")
                        new_tags, dedup_metrics = dedup_fuse(tags_v0, tags_v1)

                        # Аккумулируем метрики дедупликации
                        for key, value in dedup_metrics.as_dict().items():
                            if isinstance(value, dict):
                                for subkey, subvalue in value.items():
                                    full_key = f"{key}_{subkey}"
                                    current_value = stats.dedup_metrics_total.get(full_key, 0)
                                    additional_value = (
                                        int(subvalue) if isinstance(subvalue, int | float) else 0
                                    )
                                    stats.dedup_metrics_total[full_key] = (
                                        current_value + additional_value
                                    )
                    else:
                        # Одиночный режим
                        new_tags = tag_text(text, kind=tag_kind, mode=mode)

                    stats.total_tags_after += len(new_tags)

                    # Проверяем нужно ли обновление
                    if set(old_tags) == set(new_tags):
                        stats.no_changes += 1
                        stats.skipped += 1
                    else:
                        # Обновляем если не dry-run
                        if not dry_run:
                            try:
                                success = update_func(item["id"], new_tags)
                                if success:
                                    stats.updated += 1
                                    logger.debug(
                                        f"Updated {db[:-1]} {item['id']}: "
                                        f"{len(old_tags)} → {len(new_tags)} tags"
                                    )
                                else:
                                    stats.api_errors += 1
                                    stats.errors += 1
                            except Exception as update_error:
                                logger.error(f"Error updating {item['id']}: {update_error}")
                                stats.api_errors += 1
                                stats.errors += 1
                        else:
                            # В dry-run режиме просто считаем как обновленные
                            stats.updated += 1
                            logger.debug(
                                f"[DRY-RUN] Would update {db[:-1]} {item['id']}: "
                                f"{len(old_tags)} → {len(new_tags)} tags"
                            )

                except Exception as e:
                    logger.error(f"Error processing {db[:-1]} {item.get('id', 'unknown')}: {e}")
                    stats.errors += 1

                # Отслеживаем время обработки
                item_time = (perf_counter() - item_start) * 1000
                processing_times.append(item_time)

                processed_count += 1

                # Проверяем лимит
                if limit and processed_count >= limit:
                    logger.info(f"Reached limit of {limit} items, stopping")
                    break

            # Проверяем лимит на уровне батча
            if limit and processed_count >= limit:
                break

        # Вычисляем среднее время обработки
        if processing_times:
            stats.avg_processing_time_ms = sum(processing_times) / len(processing_times)

        stats.latency_s = perf_counter() - start_time

        logger.info(
            f"Retag operation completed: {stats.scanned} scanned, "
            f"{stats.updated} updated, {stats.skipped} skipped, "
            f"{stats.errors} errors in {stats.latency_s:.2f}s"
        )

        return stats

    except Exception as e:
        stats.latency_s = perf_counter() - start_time
        logger.error(f"Critical error in retag operation: {e}")
        stats.errors += 1
        return stats


def validate_retag_params(
    db: str, since_iso: str | None, limit: int | None, mode: str
) -> tuple[bool, str]:
    """
    Валидирует параметры для retag операции.

    Args:
        db: Тип базы данных
        since_iso: Дата в ISO формате
        limit: Лимит записей
        mode: Режим тегирования

    Returns:
        Кортеж (валидно, сообщение об ошибке)
    """
    # Проверяем тип базы
    if db not in ("meetings", "commits"):
        return False, f"Неверный тип базы: {db}. Используйте 'meetings' или 'commits'"

    # Проверяем дату
    if since_iso is not None and since_iso.strip():
        import re
        from datetime import datetime

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", since_iso):
            return False, f"Неверный формат даты: {since_iso}. Используйте YYYY-MM-DD"

        # Дополнительная проверка валидности даты
        try:
            datetime.strptime(since_iso, "%Y-%m-%d")
        except ValueError:
            return False, f"Невалидная дата: {since_iso}. Проверьте месяц и день"

    # Проверяем лимит
    if limit is not None:
        if not isinstance(limit, int) or limit <= 0:
            return False, f"Лимит должен быть положительным числом: {limit}"
        if limit > 10000:
            return False, f"Лимит слишком большой: {limit}. Максимум 10000"

    # Проверяем режим
    if mode not in ("v0", "v1", "both"):
        return False, f"Неверный режим: {mode}. Используйте 'v0', 'v1' или 'both'"

    return True, ""


def estimate_retag_time(
    db: str, since_iso: str | None = None, limit: int | None = None
) -> dict[str, Any]:
    """
    Оценивает время выполнения retag операции.

    Args:
        db: Тип базы данных
        since_iso: Фильтр по дате
        limit: Лимит записей

    Returns:
        Словарь с оценками времени
    """
    # Базовые оценки времени на запись (в секундах)
    base_time_per_item = {
        "meetings": 0.5,  # Встречи обычно больше и сложнее
        "commits": 0.2,  # Коммиты короче и быстрее
    }

    # Примерная оценка количества записей (без реального запроса)
    estimated_items = limit or 1000  # По умолчанию оцениваем в 1000 записей

    base_time = base_time_per_item.get(db, 0.3)
    estimated_total_time = estimated_items * base_time

    return {
        "estimated_items": estimated_items,
        "estimated_time_seconds": round(estimated_total_time, 1),
        "estimated_time_minutes": round(estimated_total_time / 60, 1),
        "base_time_per_item_ms": round(base_time * 1000, 1),
    }
