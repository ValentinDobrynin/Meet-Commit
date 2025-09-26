"""
Система профилирования производительности.

Обеспечивает детальный анализ производительности операций,
выявление узких мест и оптимизацию ресурсов.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.core.metrics import observe_latency

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# Хранилище данных профилирования
_profiling_data: dict[str, list[float]] = defaultdict(list)
_call_counts: dict[str, int] = defaultdict(int)
_concurrent_operations: dict[str, int] = defaultdict(int)
_peak_concurrency: dict[str, int] = defaultdict(int)


@dataclass
class ProfileData:
    """Данные профилирования операции."""
    name: str
    duration_ms: float
    concurrent_count: int
    timestamp: float
    memory_delta: int = 0
    cpu_percent: float = 0.0
    additional_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConcurrencyStats:
    """Статистика конкурентности."""
    current: int
    peak: int
    average: float
    total_calls: int


class PerformanceProfiler:
    """Профилировщик производительности."""
    
    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time: float = 0
        self.start_memory: int = 0
    
    def __enter__(self) -> PerformanceProfiler:
        self.start_time = time.perf_counter()
        _concurrent_operations[self.operation_name] += 1
        _peak_concurrency[self.operation_name] = max(
            _peak_concurrency[self.operation_name],
            _concurrent_operations[self.operation_name]
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        _concurrent_operations[self.operation_name] -= 1
        _call_counts[self.operation_name] += 1
        _profiling_data[self.operation_name].append(duration_ms)
        
        # Интегрируем с существующей системой метрик
        observe_latency(self.operation_name, duration_ms)
        
        logger.debug(f"Profile: {self.operation_name} took {duration_ms:.2f}ms")


@asynccontextmanager
async def async_profiler(operation_name: str):
    """Асинхронный профилировщик."""
    start_time = time.perf_counter()
    _concurrent_operations[operation_name] += 1
    _peak_concurrency[operation_name] = max(
        _peak_concurrency[operation_name],
        _concurrent_operations[operation_name]
    )
    
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        _concurrent_operations[operation_name] -= 1
        _call_counts[operation_name] += 1
        _profiling_data[operation_name].append(duration_ms)
        
        # Интегрируем с существующей системой метрик
        observe_latency(operation_name, duration_ms)
        
        logger.debug(f"Async Profile: {operation_name} took {duration_ms:.2f}ms")


def profile_sync(operation_name: str) -> Callable[[F], F]:
    """Декоратор для профилирования синхронных функций."""
    def decorator(func: F) -> F:
        def wrapper(*args, **kwargs):
            with PerformanceProfiler(operation_name):
                return func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


def profile_async(operation_name: str) -> Callable[[F], F]:
    """Декоратор для профилирования асинхронных функций."""
    def decorator(func: F) -> F:
        async def wrapper(*args, **kwargs):
            async with async_profiler(operation_name):
                return await func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


def get_operation_stats(operation_name: str) -> dict[str, Any]:
    """Получает статистику по операции."""
    durations = _profiling_data.get(operation_name, [])
    if not durations:
        return {
            "operation": operation_name,
            "calls": 0,
            "avg_ms": 0,
            "min_ms": 0,
            "max_ms": 0,
            "total_ms": 0,
            "current_concurrent": 0,
            "peak_concurrent": 0,
        }
    
    return {
        "operation": operation_name,
        "calls": len(durations),
        "avg_ms": sum(durations) / len(durations),
        "min_ms": min(durations),
        "max_ms": max(durations),
        "total_ms": sum(durations),
        "current_concurrent": _concurrent_operations[operation_name],
        "peak_concurrent": _peak_concurrency[operation_name],
    }


def get_concurrency_stats(operation_name: str) -> ConcurrencyStats:
    """Получает статистику конкурентности."""
    durations = _profiling_data.get(operation_name, [])
    total_calls = _call_counts[operation_name]
    
    return ConcurrencyStats(
        current=_concurrent_operations[operation_name],
        peak=_peak_concurrency[operation_name],
        average=sum(durations) / len(durations) if durations else 0,
        total_calls=total_calls,
    )


def get_all_operations_stats() -> dict[str, dict[str, Any]]:
    """Получает статистику по всем операциям."""
    stats = {}
    all_operations = set(_profiling_data.keys()) | set(_call_counts.keys())
    
    for operation in all_operations:
        stats[operation] = get_operation_stats(operation)
    
    return stats


def get_slow_operations(threshold_ms: float = 1000) -> list[dict[str, Any]]:
    """Находит медленные операции."""
    slow_ops = []
    
    for operation, durations in _profiling_data.items():
        if durations:
            avg_duration = sum(durations) / len(durations)
            max_duration = max(durations)
            
            if avg_duration > threshold_ms or max_duration > threshold_ms * 2:
                slow_ops.append({
                    "operation": operation,
                    "avg_ms": avg_duration,
                    "max_ms": max_duration,
                    "calls": len(durations),
                    "severity": "high" if avg_duration > threshold_ms * 2 else "medium",
                })
    
    return sorted(slow_ops, key=lambda x: x["avg_ms"], reverse=True)


def get_high_concurrency_operations(threshold: int = 5) -> list[dict[str, Any]]:
    """Находит операции с высокой конкурентностью."""
    high_concurrency = []
    
    for operation, peak in _peak_concurrency.items():
        if peak >= threshold:
            high_concurrency.append({
                "operation": operation,
                "peak_concurrent": peak,
                "current_concurrent": _concurrent_operations[operation],
                "total_calls": _call_counts[operation],
            })
    
    return sorted(high_concurrency, key=lambda x: x["peak_concurrent"], reverse=True)


def reset_profiling_data() -> None:
    """Сбрасывает данные профилирования."""
    _profiling_data.clear()
    _call_counts.clear()
    _concurrent_operations.clear()
    _peak_concurrency.clear()
    logger.info("Profiling data reset")


def get_performance_summary() -> dict[str, Any]:
    """Получает сводку производительности."""
    all_stats = get_all_operations_stats()
    slow_ops = get_slow_operations()
    high_concurrency = get_high_concurrency_operations()
    
    total_operations = sum(stats["calls"] for stats in all_stats.values())
    total_time_ms = sum(stats["total_ms"] for stats in all_stats.values())
    
    return {
        "summary": {
            "total_operations": total_operations,
            "total_time_ms": total_time_ms,
            "average_operation_ms": total_time_ms / total_operations if total_operations > 0 else 0,
            "unique_operations": len(all_stats),
        },
        "slow_operations": slow_ops,
        "high_concurrency_operations": high_concurrency,
        "top_operations_by_time": sorted(
            all_stats.values(), 
            key=lambda x: x["total_ms"], 
            reverse=True
        )[:10],
        "top_operations_by_calls": sorted(
            all_stats.values(), 
            key=lambda x: x["calls"], 
            reverse=True
        )[:10],
    }


# =============== ASYNC BENCHMARKING ===============


async def benchmark_async_vs_sync(
    operation_name: str,
    async_func: Callable[[], Any],
    sync_func: Callable[[], Any],
    iterations: int = 10,
) -> dict[str, Any]:
    """
    Сравнивает производительность async vs sync операций.
    
    Args:
        operation_name: Название операции для логирования
        async_func: Асинхронная функция для тестирования
        sync_func: Синхронная функция для тестирования
        iterations: Количество итераций
        
    Returns:
        Статистика сравнения производительности
    """
    logger.info(f"Benchmarking {operation_name}: async vs sync ({iterations} iterations)")
    
    # Тестируем async версию (параллельно)
    async_start = time.perf_counter()
    async_tasks = [async_func() for _ in range(iterations)]
    async_results = await asyncio.gather(*async_tasks, return_exceptions=True)
    async_duration = time.perf_counter() - async_start
    
    async_errors = sum(1 for r in async_results if isinstance(r, Exception))
    
    # Тестируем sync версию через executor (последовательно)
    sync_start = time.perf_counter()
    sync_results = []
    for _ in range(iterations):
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, sync_func)
            sync_results.append(result)
        except Exception as e:
            sync_results.append(e)
    sync_duration = time.perf_counter() - sync_start
    
    sync_errors = sum(1 for r in sync_results if isinstance(r, Exception))
    
    # Анализируем результаты
    speedup = sync_duration / async_duration if async_duration > 0 else float('inf')
    
    stats = {
        "operation": operation_name,
        "iterations": iterations,
        "async": {
            "duration_ms": async_duration * 1000,
            "avg_per_op_ms": (async_duration * 1000) / iterations,
            "errors": async_errors,
            "success_rate": (iterations - async_errors) / iterations,
        },
        "sync": {
            "duration_ms": sync_duration * 1000,
            "avg_per_op_ms": (sync_duration * 1000) / iterations,
            "errors": sync_errors,
            "success_rate": (iterations - sync_errors) / iterations,
        },
        "comparison": {
            "speedup": speedup,
            "async_faster": speedup > 1.0,
            "time_saved_ms": (sync_duration - async_duration) * 1000,
            "efficiency_gain": ((sync_duration - async_duration) / sync_duration) * 100 if sync_duration > 0 else 0,
        }
    }
    
    logger.info(
        f"Benchmark {operation_name}: "
        f"async {stats['async']['duration_ms']:.1f}ms vs sync {stats['sync']['duration_ms']:.1f}ms "
        f"(speedup: {speedup:.1f}x)"
    )
    
    return stats


# =============== RESOURCE MONITORING ===============


def get_memory_usage() -> dict[str, Any]:
    """Получает информацию об использовании памяти."""
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        
        return {
            "rss_mb": memory_info.rss / 1024 / 1024,  # Resident Set Size
            "vms_mb": memory_info.vms / 1024 / 1024,  # Virtual Memory Size
            "percent": process.memory_percent(),
            "available": True,
        }
    except ImportError:
        return {"available": False, "error": "psutil не установлен"}
    except Exception as e:
        return {"available": False, "error": str(e)}


def get_cpu_usage() -> dict[str, Any]:
    """Получает информацию об использовании CPU."""
    try:
        import psutil
        process = psutil.Process()
        
        return {
            "percent": process.cpu_percent(),
            "num_threads": process.num_threads(),
            "available": True,
        }
    except ImportError:
        return {"available": False, "error": "psutil не установлен"}
    except Exception as e:
        return {"available": False, "error": str(e)}


def get_system_resources() -> dict[str, Any]:
    """Получает общую информацию о системных ресурсах."""
    return {
        "memory": get_memory_usage(),
        "cpu": get_cpu_usage(),
        "timestamp": time.time(),
    }


# =============== BOTTLENECK DETECTION ===============


def detect_bottlenecks(min_calls: int = 10) -> dict[str, Any]:
    """
    Автоматически выявляет узкие места в производительности.
    
    Args:
        min_calls: Минимальное количество вызовов для анализа
        
    Returns:
        Анализ узких мест с рекомендациями
    """
    bottlenecks = {
        "slow_operations": [],
        "high_concurrency": [],
        "frequent_operations": [],
        "recommendations": [],
    }
    
    # Анализируем медленные операции
    for operation, durations in _profiling_data.items():
        if len(durations) < min_calls:
            continue
            
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
        p95_duration = sorted(durations)[int(len(durations) * 0.95)]
        
        # Медленные операции (>1s среднее или >5s максимум)
        if avg_duration > 1000 or max_duration > 5000:
            bottlenecks["slow_operations"].append({
                "operation": operation,
                "avg_ms": avg_duration,
                "max_ms": max_duration,
                "p95_ms": p95_duration,
                "calls": len(durations),
                "severity": "critical" if avg_duration > 2000 else "warning",
            })
    
    # Анализируем высокую конкурентность
    for operation, peak in _peak_concurrency.items():
        if peak >= 10:  # Более 10 одновременных операций
            bottlenecks["high_concurrency"].append({
                "operation": operation,
                "peak_concurrent": peak,
                "total_calls": _call_counts[operation],
                "avg_concurrent": peak / _call_counts[operation] if _call_counts[operation] > 0 else 0,
            })
    
    # Анализируем частые операции
    frequent_ops = sorted(_call_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    for operation, calls in frequent_ops:
        if calls >= min_calls:
            durations = _profiling_data.get(operation, [])
            avg_duration = sum(durations) / len(durations) if durations else 0
            
            bottlenecks["frequent_operations"].append({
                "operation": operation,
                "calls": calls,
                "avg_ms": avg_duration,
                "total_time_ms": sum(durations),
            })
    
    # Генерируем рекомендации
    recommendations = []
    
    if bottlenecks["slow_operations"]:
        recommendations.append("Оптимизировать медленные операции: добавить кэширование или уменьшить timeout'ы")
    
    if bottlenecks["high_concurrency"]:
        recommendations.append("Добавить семафоры для контроля конкурентности в высоконагруженных операциях")
    
    if len(bottlenecks["frequent_operations"]) > 3:
        recommendations.append("Рассмотреть кэширование для часто вызываемых операций")
    
    bottlenecks["recommendations"] = recommendations
    
    return bottlenecks


def generate_performance_report() -> str:
    """Генерирует отчет о производительности в читаемом формате."""
    summary = get_performance_summary()
    bottlenecks = detect_bottlenecks()
    resources = get_system_resources()
    
    report = []
    report.append("📊 ОТЧЕТ О ПРОИЗВОДИТЕЛЬНОСТИ")
    report.append("=" * 50)
    
    # Общая статистика
    total_ops = summary["summary"]["total_operations"]
    total_time = summary["summary"]["total_time_ms"]
    avg_time = summary["summary"]["average_operation_ms"]
    
    report.append(f"🔢 Всего операций: {total_ops}")
    report.append(f"⏱️ Общее время: {total_time:.1f}ms")
    report.append(f"📈 Среднее время: {avg_time:.1f}ms/операция")
    report.append("")
    
    # Топ операций по времени
    if summary["top_operations_by_time"]:
        report.append("🐌 ТОП МЕДЛЕННЫХ ОПЕРАЦИЙ:")
        for i, op in enumerate(summary["top_operations_by_time"][:5], 1):
            report.append(f"{i}. {op['operation']}: {op['avg_ms']:.1f}ms (вызовов: {op['calls']})")
        report.append("")
    
    # Узкие места
    if bottlenecks["slow_operations"]:
        report.append("⚠️ УЗКИЕ МЕСТА:")
        for bottleneck in bottlenecks["slow_operations"][:3]:
            severity = "🔴" if bottleneck["severity"] == "critical" else "🟡"
            report.append(f"{severity} {bottleneck['operation']}: {bottleneck['avg_ms']:.1f}ms среднее")
        report.append("")
    
    # Рекомендации
    if bottlenecks["recommendations"]:
        report.append("💡 РЕКОМЕНДАЦИИ:")
        for i, rec in enumerate(bottlenecks["recommendations"], 1):
            report.append(f"{i}. {rec}")
        report.append("")
    
    # Ресурсы системы
    if resources["memory"]["available"]:
        memory_mb = resources["memory"]["rss_mb"]
        memory_percent = resources["memory"]["percent"]
        report.append(f"💾 Память: {memory_mb:.1f}MB ({memory_percent:.1f}%)")
    
    if resources["cpu"]["available"]:
        cpu_percent = resources["cpu"]["percent"]
        threads = resources["cpu"]["num_threads"]
        report.append(f"🖥️ CPU: {cpu_percent:.1f}% ({threads} потоков)")
    
    return "\n".join(report)
