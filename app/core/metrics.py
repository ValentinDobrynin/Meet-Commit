"""
Система метрик для Meet-Commit Bot.

Обеспечивает сбор и анализ метрик производительности, ошибок и использования ресурсов
для всех компонентов системы: LLM, Notion API, тегирование, обработка файлов.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from typing import Any, NamedTuple, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

# Thread-safe хранилище метрик
_lock = threading.RLock()

# Счетчики событий
_counters: dict[str, int] = defaultdict(int)
# Счетчики ошибок
_errors: dict[str, int] = defaultdict(int)
# Полная история латентности (для точных перцентилей)
_latency_ms: dict[str, list[float]] = defaultdict(list)
# Последние ошибки для диагностики
_last_errors: dict[str, str] = {}
# Скользящее окно для быстрых вычислений
_recent_latency: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=100))
# Специальные метрики для LLM токенов
_llm_tokens: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


class MetricSnapshot(NamedTuple):
    """Снимок метрик на момент времени."""

    counters: dict[str, int]
    errors: dict[str, int]
    last_errors: dict[str, str]
    latency: dict[str, dict[str, float]]
    llm_tokens: dict[str, dict[str, int]]
    timestamp: float


def inc(name: str, by: int = 1) -> None:
    """Увеличивает счетчик."""
    with _lock:
        _counters[name] += by


def err(name: str, detail: str | None = None) -> None:
    """Регистрирует ошибку."""
    with _lock:
        _errors[name] += 1
        if detail:
            _last_errors[name] = detail[:500]  # Увеличил лимит для детальной диагностики


def observe_latency(name: str, ms: float) -> None:
    """Записывает измерение латентности."""
    with _lock:
        _latency_ms[name].append(ms)
        _recent_latency[name].append(ms)


def track_llm_tokens(
    name: str, prompt_tokens: int, completion_tokens: int, total_tokens: int
) -> None:
    """Отслеживает использование токенов LLM."""
    with _lock:
        _llm_tokens[name]["prompt_tokens"] += prompt_tokens
        _llm_tokens[name]["completion_tokens"] += completion_tokens
        _llm_tokens[name]["total_tokens"] += total_tokens
        _llm_tokens[name]["calls"] += 1


@contextmanager
def timer(name: str):
    """Контекстный менеджер для измерения времени выполнения."""
    t0 = time.perf_counter()
    try:
        yield
        ms = (time.perf_counter() - t0) * 1000
        observe_latency(name, ms)
        inc(f"{name}.success")
    except Exception as e:
        err(name, repr(e))
        inc(f"{name}.error")
        raise


@asynccontextmanager
async def async_timer(name: str):
    """Async версия timer для async функций."""
    t0 = time.perf_counter()
    try:
        yield
        ms = (time.perf_counter() - t0) * 1000
        observe_latency(name, ms)
        inc(f"{name}.success")
    except Exception as e:
        err(name, repr(e))
        inc(f"{name}.error")
        raise


def wrap_timer(name: str) -> Callable[[F], F]:
    """Декоратор для автоматического измерения времени выполнения функций."""

    def decorator(fn: F) -> F:
        if asyncio.iscoroutinefunction(fn):

            async def async_wrapper(*args, **kwargs):
                async with async_timer(name):
                    return await fn(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]
        else:

            def sync_wrapper(*args, **kwargs):
                with timer(name):
                    return fn(*args, **kwargs)

            return sync_wrapper  # type: ignore[return-value]

    return decorator


def _calculate_percentiles(values: list[float]) -> dict[str, float]:
    """Вычисляет перцентили для списка значений."""
    if not values:
        return {"min": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "avg": 0.0}

    sorted_vals = sorted(values)
    length = len(sorted_vals)

    return {
        "min": sorted_vals[0],
        "p50": sorted_vals[int(0.5 * (length - 1))],
        "p95": sorted_vals[int(0.95 * (length - 1))],
        "p99": sorted_vals[int(0.99 * (length - 1))],
        "max": sorted_vals[-1],
        "avg": sum(sorted_vals) / length,
    }


def snapshot() -> MetricSnapshot:
    """Создает снимок всех метрик."""
    with _lock:
        # Вычисляем статистику по латентности
        latency_stats = {}
        for name, values in _latency_ms.items():
            latency_stats[name] = _calculate_percentiles(values)
            latency_stats[name]["count"] = len(values)

        return MetricSnapshot(
            counters=dict(_counters),
            errors=dict(_errors),
            last_errors=dict(_last_errors),
            latency=latency_stats,
            llm_tokens=dict(_llm_tokens),
            timestamp=time.time(),
        )


def reset_metrics() -> None:
    """Сбрасывает все метрики (для тестирования)."""
    with _lock:
        _counters.clear()
        _errors.clear()
        _latency_ms.clear()
        _last_errors.clear()
        _recent_latency.clear()
        _llm_tokens.clear()


def get_recent_latency(name: str, window_size: int = 10) -> list[float]:
    """Получает последние N измерений латентности."""
    with _lock:
        recent = _recent_latency.get(name, deque())
        return list(recent)[-window_size:]


def get_error_rate(name: str) -> float:
    """Вычисляет процент ошибок для операции."""
    with _lock:
        total_calls = _counters.get(f"{name}.success", 0) + _counters.get(f"{name}.error", 0)
        if total_calls == 0:
            return 0.0
        error_calls = _counters.get(f"{name}.error", 0)
        return (error_calls / total_calls) * 100


# Специальные функции для интеграции с существующими системами


def integrate_with_tags_stats(tags_stats: dict[str, Any]) -> None:
    """Интегрирует существующую статистику тегирования."""
    with _lock:
        # Переносим статистику из tags.py
        if "total_calls" in tags_stats:
            _counters["tagging.total_calls"] = tags_stats["total_calls"]
        if "cache_hits" in tags_stats:
            _counters["tagging.cache_hits"] = tags_stats["cache_hits"]
        if "cache_misses" in tags_stats:
            _counters["tagging.cache_misses"] = tags_stats["cache_misses"]


def track_pipeline_stage(stage: str, duration_ms: float, success: bool = True) -> None:
    """Отслеживает этапы обработки пайплайна."""
    observe_latency(f"pipeline.{stage}", duration_ms)
    if success:
        inc(f"pipeline.{stage}.success")
    else:
        inc(f"pipeline.{stage}.error")


def track_batch_operation(operation: str, batch_size: int, duration_ms: float) -> None:
    """Отслеживает батчевые операции (например, обработка нескольких коммитов)."""
    observe_latency(f"batch.{operation}", duration_ms)
    inc(f"batch.{operation}.items", batch_size)
    inc(f"batch.{operation}.calls")


# Константы для стандартных имен метрик
class MetricNames:
    """Стандартные имена метрик для консистентности."""

    # LLM операции
    LLM_SUMMARIZE = "llm.summarize"
    LLM_EXTRACT_COMMITS = "llm.extract_commits"
    LLM_COMMIT_PARSE = "llm.commit_parse"
    LLM_ALIAS_SUGGESTIONS = "llm.alias_suggestions"

    # Notion операции
    NOTION_CREATE_MEETING = "notion.create_meeting"
    NOTION_UPSERT_COMMITS = "notion.upsert_commits"
    NOTION_QUERY_COMMITS = "notion.query_commits"
    NOTION_UPDATE_COMMIT_STATUS = "notion.update_commit_status"
    NOTION_CREATE_REVIEW = "notion.create_review"

    # Асинхронные Notion операции
    NOTION_UPSERT_COMMITS_ASYNC = "notion.upsert_commits_async"
    NOTION_QUERY_COMMITS_ASYNC = "notion.query_commits_async"
    NOTION_UPDATE_COMMIT_STATUS_ASYNC = "notion.update_commit_status_async"
    NOTION_UPDATE_REVIEW = "notion.update_review"

    # Обработка файлов
    INGEST_EXTRACT = "ingest.extract"
    INGEST_NORMALIZE = "ingest.normalize"

    # Тегирование
    TAGGING_TAG_TEXT = "tagging.tag_text"
    TAGGING_V1_SCORED = "tagging.v1_scored"

    # Пайплайн этапы
    PIPELINE_TOTAL = "pipeline.total"

    # People Miner v2
    PEOPLE_MINER_INGEST = "people_miner.ingest"
    PEOPLE_MINER_LIST = "people_miner.list"
    PEOPLE_MINER_APPROVE = "people_miner.approve"
    PEOPLE_MINER_BATCH_APPROVE = "people_miner.batch_approve"
    PEOPLE_MINER_BATCH_REJECT = "people_miner.batch_reject"
    PEOPLE_MINER_CANDIDATES_ADDED = "people_miner.candidates_added"
    PEOPLE_MINER_CANDIDATES_UPDATED = "people_miner.candidates_updated"
    PEOPLE_MINER_APPROVED = "people_miner.approved"
    PEOPLE_MINER_REJECTED = "people_miner.rejected"
    PIPELINE_LLM_PHASE = "pipeline.llm_phase"
    PIPELINE_NOTION_PHASE = "pipeline.notion_phase"
    PIPELINE_TAGGING_PHASE = "pipeline.tagging_phase"

    # Батчевые операции
    BATCH_COMMITS_PROCESS = "batch.commits_process"
    BATCH_TAGS_APPLY = "batch.tags_apply"

    # Дедупликация встреч
    MEETINGS_DEDUP_HIT = "meetings.dedup.hit"
    MEETINGS_DEDUP_MISS = "meetings.dedup.miss"


# Экспорт основных функций
__all__ = [
    "inc",
    "err",
    "observe_latency",
    "track_llm_tokens",
    "timer",
    "async_timer",
    "wrap_timer",
    "snapshot",
    "reset_metrics",
    "get_recent_latency",
    "get_error_rate",
    "integrate_with_tags_stats",
    "track_pipeline_stage",
    "track_batch_operation",
    "MetricSnapshot",
    "MetricNames",
]
