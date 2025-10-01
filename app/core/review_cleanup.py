"""
Система очистки Review Queue от старых записей и дубликатов.

Обеспечивает:
- Автоматическое архивирование старых решенных записей
- Обнаружение дубликатов по содержимому текста
- Массовые операции очистки с dry-run режимом
- Детальную отчетность и метрики операций
- Безопасность через валидацию и административные права
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from app.core.constants import REVIEW_STATUS_DROPPED, REVIEW_STATUS_RESOLVED

logger = logging.getLogger(__name__)

# Константы для очистки
DEFAULT_ARCHIVE_DAYS = 14
DEFAULT_SIMILARITY_THRESHOLD = 0.85
MAX_SIMILARITY_CHECKS = 1000  # Лимит для производительности


class CleanupStats:
    """Статистика операций очистки Review Queue."""

    def __init__(self) -> None:
        # Основные счетчики
        self.scanned = 0
        self.archived = 0
        self.duplicates_found = 0
        self.errors = 0

        # Детали операций
        self.old_resolved = 0
        self.old_dropped = 0
        self.similarity_checks = 0

        # Производительность
        self.processing_time_s = 0.0
        self.avg_similarity_time_ms = 0.0

        # Найденные дубликаты
        self.duplicate_pairs: list[tuple[str, str, float]] = []

    def as_dict(self) -> dict[str, Any]:
        """Возвращает статистику в виде словаря."""
        return {
            "summary": {
                "scanned": self.scanned,
                "archived": self.archived,
                "duplicates_found": self.duplicates_found,
                "errors": self.errors,
            },
            "details": {
                "old_resolved": self.old_resolved,
                "old_dropped": self.old_dropped,
                "similarity_checks": self.similarity_checks,
            },
            "performance": {
                "processing_time_s": round(self.processing_time_s, 2),
                "avg_similarity_time_ms": round(self.avg_similarity_time_ms, 2),
            },
            "duplicates": [
                {"item1": pair[0], "item2": pair[1], "similarity": round(pair[2], 3)}
                for pair in self.duplicate_pairs
            ],
        }


def normalize_text_for_comparison(text: str) -> str:
    """
    Нормализует текст для сравнения на похожесть.

    Args:
        text: Исходный текст

    Returns:
        Нормализованный текст для сравнения
    """
    if not text:
        return ""

    # Приводим к нижнему регистру и убираем лишние пробелы
    normalized = " ".join(text.lower().split())

    # Убираем пунктуацию для лучшего сравнения
    import re

    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = " ".join(normalized.split())

    return normalized


def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Вычисляет похожесть двух текстов.

    Использует комбинацию методов:
    1. SequenceMatcher для общей похожести
    2. Jaccard similarity для токенов
    3. Учет длины текстов

    Args:
        text1: Первый текст
        text2: Второй текст

    Returns:
        Коэффициент похожести (0.0-1.0)
    """
    if not text1 or not text2:
        return 0.0

    # Нормализуем тексты
    norm1 = normalize_text_for_comparison(text1)
    norm2 = normalize_text_for_comparison(text2)

    if not norm1 or not norm2:
        return 0.0

    # 1. Sequence similarity
    sequence_sim = SequenceMatcher(None, norm1, norm2).ratio()

    # 2. Jaccard similarity для токенов
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())

    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0

    intersection = len(tokens1.intersection(tokens2))
    union = len(tokens1.union(tokens2))
    jaccard_sim = intersection / union if union > 0 else 0.0

    # 3. Комбинируем с весами
    combined_similarity = (sequence_sim * 0.6) + (jaccard_sim * 0.4)

    return combined_similarity


def text_fingerprint(text: str) -> str:
    """
    Создает fingerprint текста для быстрого сравнения.

    Args:
        text: Текст для анализа

    Returns:
        16-символьный fingerprint
    """
    if not text:
        return "0" * 16

    normalized = normalize_text_for_comparison(text)
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


def auto_archive_old_reviews(
    days_threshold: int = DEFAULT_ARCHIVE_DAYS, dry_run: bool = True
) -> CleanupStats:
    """
    Автоматически архивирует старые решенные записи Review Queue.

    Args:
        days_threshold: Количество дней после которых архивировать
        dry_run: Если True, только анализирует без изменений

    Returns:
        Статистика операции архивирования
    """
    from time import perf_counter

    from app.gateways.notion_review import bulk_update_status, fetch_all_reviews

    start_time = perf_counter()
    stats = CleanupStats()

    logger.info(f"Starting auto-archive: days_threshold={days_threshold}, dry_run={dry_run}")

    try:
        # Получаем все записи Review
        all_reviews = fetch_all_reviews()
        stats.scanned = len(all_reviews)

        # Вычисляем cutoff дату
        cutoff_date = datetime.now(UTC) - timedelta(days=days_threshold)

        # Находим записи для архивирования
        to_archive = []

        for review in all_reviews:
            try:
                status = review.get("status", "pending")

                # Проверяем что статус закрытый
                if status not in (REVIEW_STATUS_RESOLVED, REVIEW_STATUS_DROPPED):
                    continue

                # Проверяем дату последнего обновления
                updated_str = review.get("last_edited_time", "")
                if not updated_str:
                    continue

                # Парсим дату (ISO формат от Notion)
                try:
                    updated_date = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                except ValueError:
                    logger.warning(
                        f"Invalid date format for review {review.get('id')}: {updated_str}"
                    )
                    continue

                # Проверяем возраст
                if updated_date < cutoff_date:
                    to_archive.append(review["id"])

                    if status == REVIEW_STATUS_RESOLVED:
                        stats.old_resolved += 1
                    elif status == REVIEW_STATUS_DROPPED:
                        stats.old_dropped += 1

            except Exception as e:
                logger.error(f"Error processing review {review.get('id', 'unknown')}: {e}")
                stats.errors += 1

        # Выполняем архивирование если не dry-run
        if to_archive and not dry_run:
            try:
                result = bulk_update_status(to_archive, "archived")
                stats.archived = result.get("updated", 0)
                logger.info(f"Archived {stats.archived} old reviews")
            except Exception as e:
                logger.error(f"Error during bulk archiving: {e}")
                stats.errors += 1
        else:
            # В dry-run режиме считаем как архивированные
            stats.archived = len(to_archive)

        stats.processing_time_s = perf_counter() - start_time

        logger.info(
            f"Auto-archive completed: scanned={stats.scanned}, "
            f"archived={stats.archived}, errors={stats.errors}"
        )

        return stats

    except Exception as e:
        stats.processing_time_s = perf_counter() - start_time
        logger.error(f"Critical error in auto_archive_old_reviews: {e}")
        stats.errors += 1
        return stats


def find_duplicate_reviews(
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_checks: int = MAX_SIMILARITY_CHECKS,
) -> CleanupStats:
    """
    Находит дубликаты в Review Queue по содержимому текста.

    Args:
        similarity_threshold: Порог похожести (0.0-1.0)
        max_checks: Максимальное количество проверок для производительности

    Returns:
        Статистика с найденными дубликатами
    """
    from time import perf_counter

    from app.gateways.notion_review import fetch_all_reviews

    start_time = perf_counter()
    stats = CleanupStats()

    logger.info(f"Starting duplicate detection: threshold={similarity_threshold}")

    try:
        # Получаем все открытые записи
        all_reviews = fetch_all_reviews(status_filter=["pending", "needs-review"])
        stats.scanned = len(all_reviews)

        if len(all_reviews) < 2:
            logger.info("Less than 2 reviews, no duplicates possible")
            stats.processing_time_s = perf_counter() - start_time
            return stats

        # Ограничиваем количество проверок для производительности
        reviews_to_check = (
            all_reviews[:max_checks] if len(all_reviews) > max_checks else all_reviews
        )

        # Создаем fingerprints для быстрой предфильтрации
        fingerprints: dict[str, list[dict]] = {}

        for review in reviews_to_check:
            text = review.get("text", "")
            if not text.strip():
                continue

            fp = text_fingerprint(text)
            if fp not in fingerprints:
                fingerprints[fp] = []
            fingerprints[fp].append(review)

        # Проверяем на дубликаты
        similarity_times = []

        for _fp, reviews_group in fingerprints.items():
            if len(reviews_group) < 2:
                continue

            # Проверяем все пары в группе
            for i in range(len(reviews_group)):
                for j in range(i + 1, len(reviews_group)):
                    review1 = reviews_group[i]
                    review2 = reviews_group[j]

                    sim_start = perf_counter()

                    similarity = calculate_text_similarity(
                        review1.get("text", ""), review2.get("text", "")
                    )

                    sim_time = (perf_counter() - sim_start) * 1000
                    similarity_times.append(sim_time)
                    stats.similarity_checks += 1

                    if similarity >= similarity_threshold:
                        stats.duplicate_pairs.append(
                            (review1.get("id", ""), review2.get("id", ""), similarity)
                        )
                        stats.duplicates_found += 1

                        logger.debug(
                            f"Duplicate found: {review1.get('id', '')[:8]} ~ "
                            f"{review2.get('id', '')[:8]} (similarity: {similarity:.3f})"
                        )

        # Вычисляем среднее время similarity проверки
        if similarity_times:
            stats.avg_similarity_time_ms = sum(similarity_times) / len(similarity_times)

        stats.processing_time_s = perf_counter() - start_time

        logger.info(
            f"Duplicate detection completed: scanned={stats.scanned}, "
            f"checks={stats.similarity_checks}, duplicates={stats.duplicates_found}"
        )

        return stats

    except Exception as e:
        stats.processing_time_s = perf_counter() - start_time
        logger.error(f"Critical error in find_duplicate_reviews: {e}")
        stats.errors += 1
        return stats


def cleanup_by_status(
    target_status: str, archive_status: str = "archived", dry_run: bool = True
) -> CleanupStats:
    """
    Очищает Review Queue по конкретному статусу.

    Args:
        target_status: Статус записей для очистки
        archive_status: Статус для архивирования
        dry_run: Если True, только анализирует без изменений

    Returns:
        Статистика операции очистки
    """
    from time import perf_counter

    from app.gateways.notion_review import bulk_update_status, fetch_all_reviews

    start_time = perf_counter()
    stats = CleanupStats()

    logger.info(f"Starting status cleanup: target={target_status}, dry_run={dry_run}")

    try:
        # Получаем все записи с целевым статусом
        all_reviews = fetch_all_reviews(status_filter=[target_status])
        stats.scanned = len(all_reviews)

        if not all_reviews:
            logger.info(f"No reviews found with status '{target_status}'")
            stats.processing_time_s = perf_counter() - start_time
            return stats

        # Собираем ID для архивирования
        to_archive = [review["id"] for review in all_reviews if review.get("id")]

        # Выполняем архивирование если не dry-run
        if to_archive and not dry_run:
            try:
                result = bulk_update_status(to_archive, archive_status)
                stats.archived = result.get("updated", 0)
                logger.info(f"Archived {stats.archived} reviews with status '{target_status}'")
            except Exception as e:
                logger.error(f"Error during bulk status update: {e}")
                stats.errors += 1
        else:
            # В dry-run режиме считаем как архивированные
            stats.archived = len(to_archive)

        stats.processing_time_s = perf_counter() - start_time

        logger.info(
            f"Status cleanup completed: scanned={stats.scanned}, "
            f"archived={stats.archived}, errors={stats.errors}"
        )

        return stats

    except Exception as e:
        stats.processing_time_s = perf_counter() - start_time
        logger.error(f"Critical error in cleanup_by_status: {e}")
        stats.errors += 1
        return stats


def comprehensive_cleanup(
    archive_days: int = DEFAULT_ARCHIVE_DAYS,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    dry_run: bool = True,
) -> dict[str, CleanupStats]:
    """
    Выполняет комплексную очистку Review Queue.

    Включает:
    1. Архивирование старых записей
    2. Поиск дубликатов
    3. Общую статистику

    Args:
        archive_days: Количество дней для архивирования старых записей
        similarity_threshold: Порог похожести для дубликатов
        dry_run: Если True, только анализирует без изменений

    Returns:
        Словарь со статистикой каждой операции
    """
    logger.info(f"Starting comprehensive cleanup: dry_run={dry_run}")

    results = {}

    try:
        # 1. Архивируем старые записи
        logger.info("Phase 1: Archiving old reviews")
        results["archive"] = auto_archive_old_reviews(archive_days, dry_run)

        # 2. Ищем дубликаты
        logger.info("Phase 2: Finding duplicates")
        results["duplicates"] = find_duplicate_reviews(similarity_threshold)

        # 3. Общая статистика
        total_scanned = sum(stats.scanned for stats in results.values())
        total_archived = sum(stats.archived for stats in results.values())
        total_duplicates = sum(stats.duplicates_found for stats in results.values())
        total_errors = sum(stats.errors for stats in results.values())

        logger.info(
            f"Comprehensive cleanup completed: scanned={total_scanned}, "
            f"archived={total_archived}, duplicates={total_duplicates}, errors={total_errors}"
        )

        return results

    except Exception as e:
        logger.error(f"Critical error in comprehensive_cleanup: {e}")
        # Возвращаем результаты даже при ошибке
        return results


def validate_cleanup_params(
    mode: str, days: int | None = None, threshold: float | None = None
) -> tuple[bool, str]:
    """
    Валидирует параметры для операций очистки.

    Args:
        mode: Режим очистки ("old", "dups", "status", "all")
        days: Количество дней для архивирования
        threshold: Порог похожести для дубликатов

    Returns:
        Кортеж (валидно, сообщение об ошибке)
    """
    # Проверяем режим
    valid_modes = {"old", "dups", "status", "all", "dry-run"}
    if mode not in valid_modes:
        return False, f"Неверный режим: {mode}. Используйте: {', '.join(valid_modes)}"

    # Проверяем дни
    if days is not None:
        if not isinstance(days, int) or days < 1:
            return False, f"Количество дней должно быть положительным числом: {days}"
        if days > 365:
            return False, f"Слишком большое количество дней: {days}. Максимум 365"

    # Проверяем порог похожести
    if threshold is not None:
        if not isinstance(threshold, int | float) or not 0.0 <= threshold <= 1.0:
            return False, f"Порог похожести должен быть от 0.0 до 1.0: {threshold}"

    return True, ""


def estimate_cleanup_time(mode: str, estimated_reviews: int = 100) -> dict[str, Any]:
    """
    Оценивает время выполнения операций очистки.

    Args:
        mode: Режим очистки
        estimated_reviews: Примерное количество записей

    Returns:
        Словарь с оценками времени
    """
    # Базовые оценки времени (в секундах)
    base_times = {
        "old": 0.01,  # Быстрая проверка дат
        "dups": 0.05,  # Similarity вычисления
        "status": 0.005,  # Простая фильтрация
        "all": 0.06,  # Комбинация всех операций
    }

    base_time = base_times.get(mode, 0.05)

    # Для дубликатов время растет квадратично
    if mode == "dups":
        # O(n²) для similarity проверок
        estimated_time = (estimated_reviews**2) * base_time / 1000
    else:
        # O(n) для остальных операций
        estimated_time = estimated_reviews * base_time

    return {
        "estimated_reviews": estimated_reviews,
        "estimated_time_seconds": round(estimated_time, 1),
        "estimated_time_minutes": round(estimated_time / 60, 1),
        "complexity": "O(n²)" if mode == "dups" else "O(n)",
    }
