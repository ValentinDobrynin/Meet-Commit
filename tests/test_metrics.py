"""Тесты для системы метрик."""

import asyncio
import time

import pytest

from app.core.metrics import (
    MetricNames,
    async_timer,
    err,
    get_error_rate,
    get_recent_latency,
    inc,
    integrate_with_tags_stats,
    observe_latency,
    reset_metrics,
    snapshot,
    timer,
    track_batch_operation,
    track_llm_tokens,
    track_pipeline_stage,
    wrap_timer,
)


class TestBasicMetrics:
    """Тесты базовых функций метрик."""

    def setup_method(self):
        """Сброс метрик перед каждым тестом."""
        reset_metrics()

    def test_inc_counter(self):
        """Тест счетчиков."""
        inc("test.counter")
        inc("test.counter", 5)

        snap = snapshot()
        assert snap.counters["test.counter"] == 6

    def test_error_tracking(self):
        """Тест отслеживания ошибок."""
        err("test.operation", "Test error details")
        err("test.operation")  # Без деталей

        snap = snapshot()
        assert snap.errors["test.operation"] == 2
        assert snap.last_errors["test.operation"] == "Test error details"

    def test_latency_observation(self):
        """Тест записи латентности."""
        observe_latency("test.operation", 100.5)
        observe_latency("test.operation", 200.0)
        observe_latency("test.operation", 150.0)

        snap = snapshot()
        lat = snap.latency["test.operation"]

        assert lat["count"] == 3
        assert lat["min"] == 100.5
        assert lat["max"] == 200.0
        assert lat["avg"] == 150.16666666666666
        assert lat["p95"] == 150.0  # p95 от [100.5, 150.0, 200.0] = 150.0

    def test_llm_token_tracking(self):
        """Тест отслеживания токенов LLM."""
        track_llm_tokens("llm.test", 100, 50, 150)
        track_llm_tokens("llm.test", 200, 75, 275)

        snap = snapshot()
        tokens = snap.llm_tokens["llm.test"]

        assert tokens["calls"] == 2
        assert tokens["prompt_tokens"] == 300
        assert tokens["completion_tokens"] == 125
        assert tokens["total_tokens"] == 425


class TestTimers:
    """Тесты таймеров и декораторов."""

    def setup_method(self):
        """Сброс метрик перед каждым тестом."""
        reset_metrics()

    def test_timer_context_manager_success(self):
        """Тест успешного выполнения с таймером."""
        with timer("test.operation"):
            time.sleep(0.01)  # 10ms

        snap = snapshot()
        assert snap.counters["test.operation.success"] == 1
        assert snap.counters.get("test.operation.error", 0) == 0

        lat = snap.latency["test.operation"]
        assert lat["count"] == 1
        assert lat["avg"] >= 10.0  # Минимум 10ms

    def test_timer_context_manager_error(self):
        """Тест обработки ошибки в таймере."""
        with pytest.raises(ValueError):
            with timer("test.operation"):
                raise ValueError("Test error")

        snap = snapshot()
        assert snap.counters.get("test.operation.success", 0) == 0
        assert snap.counters["test.operation.error"] == 1
        assert snap.errors["test.operation"] == 1
        assert "ValueError" in snap.last_errors["test.operation"]

    @pytest.mark.asyncio
    async def test_async_timer_success(self):
        """Тест async таймера."""
        async with async_timer("test.async_operation"):
            await asyncio.sleep(0.01)  # 10ms

        snap = snapshot()
        assert snap.counters["test.async_operation.success"] == 1

        lat = snap.latency["test.async_operation"]
        assert lat["count"] == 1
        assert lat["avg"] >= 10.0

    @pytest.mark.asyncio
    async def test_async_timer_error(self):
        """Тест обработки ошибки в async таймере."""
        with pytest.raises(ValueError):
            async with async_timer("test.async_operation"):
                raise ValueError("Async test error")

        snap = snapshot()
        assert snap.counters["test.async_operation.error"] == 1
        assert snap.errors["test.async_operation"] == 1

    def test_wrap_timer_sync_function(self):
        """Тест декоратора для синхронных функций."""

        @wrap_timer("test.decorated")
        def test_function(x: int) -> int:
            time.sleep(0.01)
            return x * 2

        result = test_function(5)
        assert result == 10

        snap = snapshot()
        assert snap.counters["test.decorated.success"] == 1
        assert snap.latency["test.decorated"]["count"] == 1

    @pytest.mark.asyncio
    async def test_wrap_timer_async_function(self):
        """Тест декоратора для async функций."""

        @wrap_timer("test.async_decorated")
        async def async_test_function(x: int) -> int:
            await asyncio.sleep(0.01)
            return x * 3

        result = await async_test_function(4)
        assert result == 12

        snap = snapshot()
        assert snap.counters["test.async_decorated.success"] == 1
        assert snap.latency["test.async_decorated"]["count"] == 1


class TestAdvancedFeatures:
    """Тесты продвинутых функций."""

    def setup_method(self):
        """Сброс метрик перед каждым тестом."""
        reset_metrics()

    def test_get_recent_latency(self):
        """Тест получения последних измерений."""
        for i in range(15):
            observe_latency("test.operation", float(i * 10))

        recent = get_recent_latency("test.operation", 5)
        assert len(recent) == 5
        assert recent == [100.0, 110.0, 120.0, 130.0, 140.0]

    def test_get_error_rate(self):
        """Тест вычисления процента ошибок."""
        inc("test.operation.success", 7)
        inc("test.operation.error", 3)

        error_rate = get_error_rate("test.operation")
        assert error_rate == 30.0  # 3/(7+3) * 100

    def test_get_error_rate_no_calls(self):
        """Тест процента ошибок при отсутствии вызовов."""
        error_rate = get_error_rate("nonexistent.operation")
        assert error_rate == 0.0

    def test_integrate_with_tags_stats(self):
        """Тест интеграции с существующей статистикой тегирования."""
        tags_stats = {
            "total_calls": 42,
            "cache_hits": 35,
            "cache_misses": 7,
        }

        integrate_with_tags_stats(tags_stats)

        snap = snapshot()
        assert snap.counters["tagging.total_calls"] == 42
        assert snap.counters["tagging.cache_hits"] == 35
        assert snap.counters["tagging.cache_misses"] == 7

    def test_track_pipeline_stage(self):
        """Тест отслеживания этапов пайплайна."""
        track_pipeline_stage("llm_phase", 1500.0, True)
        track_pipeline_stage("notion_phase", 800.0, False)

        snap = snapshot()
        assert snap.latency["pipeline.llm_phase"]["count"] == 1
        assert snap.latency["pipeline.llm_phase"]["avg"] == 1500.0
        assert snap.counters["pipeline.llm_phase.success"] == 1
        assert snap.counters["pipeline.notion_phase.error"] == 1

    def test_track_batch_operation(self):
        """Тест отслеживания батчевых операций."""
        track_batch_operation("commits_process", 5, 2000.0)
        track_batch_operation("commits_process", 3, 1200.0)

        snap = snapshot()
        assert snap.counters["batch.commits_process.items"] == 8  # 5 + 3
        assert snap.counters["batch.commits_process.calls"] == 2
        assert snap.latency["batch.commits_process"]["count"] == 2


class TestMetricNames:
    """Тесты констант имен метрик."""

    def test_metric_names_constants(self):
        """Проверяем, что все константы определены."""
        assert hasattr(MetricNames, "LLM_SUMMARIZE")
        assert hasattr(MetricNames, "LLM_EXTRACT_COMMITS")
        assert hasattr(MetricNames, "NOTION_CREATE_MEETING")
        assert hasattr(MetricNames, "NOTION_UPSERT_COMMITS")
        assert hasattr(MetricNames, "TAGGING_TAG_TEXT")
        assert hasattr(MetricNames, "INGEST_EXTRACT")

    def test_metric_names_values(self):
        """Проверяем значения констант."""
        assert MetricNames.LLM_SUMMARIZE == "llm.summarize"
        assert MetricNames.NOTION_CREATE_MEETING == "notion.create_meeting"
        assert MetricNames.TAGGING_TAG_TEXT == "tagging.tag_text"


class TestThreadSafety:
    """Тесты потокобезопасности."""

    def setup_method(self):
        """Сброс метрик перед каждым тестом."""
        reset_metrics()

    def test_concurrent_counter_updates(self):
        """Тест конкурентного обновления счетчиков."""
        import threading

        def worker():
            for _ in range(100):
                inc("test.concurrent")

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = snapshot()
        assert snap.counters["test.concurrent"] == 500  # 5 threads * 100 increments

    def test_concurrent_latency_observations(self):
        """Тест конкурентных измерений латентности."""
        import threading

        def worker():
            for i in range(50):
                observe_latency("test.concurrent_latency", float(i))

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = snapshot()
        assert (
            snap.latency["test.concurrent_latency"]["count"] == 150
        )  # 3 threads * 50 observations


class TestIntegration:
    """Интеграционные тесты."""

    def setup_method(self):
        """Сброс метрик перед каждым тестом."""
        reset_metrics()

    def test_full_pipeline_simulation(self):
        """Симуляция полного пайплайна с метриками."""
        # Симулируем обработку файла
        with timer(MetricNames.INGEST_EXTRACT):
            time.sleep(0.01)

        # Симулируем LLM вызовы
        track_llm_tokens(MetricNames.LLM_SUMMARIZE, 500, 200, 700)
        with timer(MetricNames.LLM_EXTRACT_COMMITS):
            time.sleep(0.02)

        # Симулируем Notion операции
        with timer(MetricNames.NOTION_CREATE_MEETING):
            time.sleep(0.005)

        track_batch_operation("commits_process", 3, 150.0)

        # Проверяем результат
        snap = snapshot()

        # Проверяем счетчики
        assert snap.counters[f"{MetricNames.INGEST_EXTRACT}.success"] == 1
        assert snap.counters[f"{MetricNames.LLM_EXTRACT_COMMITS}.success"] == 1
        assert snap.counters[f"{MetricNames.NOTION_CREATE_MEETING}.success"] == 1

        # Проверяем латентность
        assert snap.latency[MetricNames.INGEST_EXTRACT]["count"] == 1
        assert snap.latency[MetricNames.LLM_EXTRACT_COMMITS]["count"] == 1
        assert snap.latency[MetricNames.NOTION_CREATE_MEETING]["count"] == 1

        # Проверяем токены
        tokens = snap.llm_tokens[MetricNames.LLM_SUMMARIZE]
        assert tokens["total_tokens"] == 700
        assert tokens["calls"] == 1

        # Проверяем батчевые операции
        assert snap.counters["batch.commits_process.items"] == 3
        assert snap.counters["batch.commits_process.calls"] == 1

    def test_error_scenarios(self):
        """Тест сценариев с ошибками."""
        # Симулируем ошибки в разных компонентах
        err("llm.summarize", "OpenAI API timeout")
        err("notion.create_meeting", "Rate limit exceeded")
        err("tagging.tag_text", "Rule parsing error")

        with pytest.raises(ValueError):
            with timer("test.failing_operation"):
                raise ValueError("Simulated failure")

        snap = snapshot()

        # Проверяем ошибки
        assert snap.errors["llm.summarize"] == 1
        assert snap.errors["notion.create_meeting"] == 1
        assert snap.errors["tagging.tag_text"] == 1
        assert snap.errors["test.failing_operation"] == 1

        # Проверяем детали ошибок
        assert "OpenAI API timeout" in snap.last_errors["llm.summarize"]
        assert "Rate limit exceeded" in snap.last_errors["notion.create_meeting"]
        assert "ValueError" in snap.last_errors["test.failing_operation"]


class TestPerformanceCalculations:
    """Тесты вычислений производительности."""

    def setup_method(self):
        """Сброс метрик перед каждым тестом."""
        reset_metrics()

    def test_percentile_calculations(self):
        """Тест вычисления перцентилей."""
        # Добавляем известные значения
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        for val in values:
            observe_latency("test.percentiles", val)

        snap = snapshot()
        lat = snap.latency["test.percentiles"]

        assert lat["min"] == 10
        assert lat["max"] == 100
        assert lat["p50"] == 50
        assert lat["p95"] == 90  # p95 от 10 элементов = index 8 = value 90
        assert lat["avg"] == 55.0

    def test_error_rate_calculation(self):
        """Тест вычисления процента ошибок."""
        # 80 успешных, 20 ошибок = 20% error rate
        inc("test.service.success", 80)
        inc("test.service.error", 20)

        error_rate = get_error_rate("test.service")
        assert error_rate == 20.0

    def test_recent_latency_window(self):
        """Тест скользящего окна латентности."""
        # Добавляем больше значений, чем размер окна
        for i in range(150):
            observe_latency("test.window", float(i))

        # Должно вернуть только последние 100 (размер deque)
        recent_all = get_recent_latency("test.window", 200)
        assert len(recent_all) == 100
        assert recent_all[-1] == 149.0  # Последнее значение

        # Должно вернуть только последние 10
        recent_10 = get_recent_latency("test.window", 10)
        assert len(recent_10) == 10
        assert recent_10 == [140.0, 141.0, 142.0, 143.0, 144.0, 145.0, 146.0, 147.0, 148.0, 149.0]


class TestRealWorldScenarios:
    """Тесты реальных сценариев использования."""

    def setup_method(self):
        """Сброс метрик перед каждым тестом."""
        reset_metrics()

    def test_llm_retry_scenario(self):
        """Тест сценария с повторными попытками LLM."""
        # Первая попытка
        track_llm_tokens("llm.extract_commits", 1000, 300, 1300)

        # Повторная попытка
        track_llm_tokens("llm.extract_commits.retry", 1000, 250, 1250)

        snap = snapshot()

        # Основные токены
        main_tokens = snap.llm_tokens["llm.extract_commits"]
        assert main_tokens["total_tokens"] == 1300
        assert main_tokens["calls"] == 1

        # Токены повторных попыток
        retry_tokens = snap.llm_tokens["llm.extract_commits.retry"]
        assert retry_tokens["total_tokens"] == 1250
        assert retry_tokens["calls"] == 1

    def test_notion_batch_processing(self):
        """Тест батчевой обработки в Notion."""
        # Симулируем обработку встречи с 5 коммитами
        with timer(MetricNames.NOTION_CREATE_MEETING):
            time.sleep(0.1)

        track_batch_operation("commits_upsert", 5, 250.0)

        # Симулируем обработку запросов
        for _ in range(3):
            with timer(MetricNames.NOTION_QUERY_COMMITS):
                time.sleep(0.05)

        snap = snapshot()

        # Проверяем создание встречи
        assert snap.counters[f"{MetricNames.NOTION_CREATE_MEETING}.success"] == 1

        # Проверяем батчевую обработку
        assert snap.counters["batch.commits_upsert.items"] == 5
        assert snap.counters["batch.commits_upsert.calls"] == 1

        # Проверяем запросы
        assert snap.counters[f"{MetricNames.NOTION_QUERY_COMMITS}.success"] == 3
        assert snap.latency[MetricNames.NOTION_QUERY_COMMITS]["count"] == 3

    def test_tagging_integration(self):
        """Тест интеграции с существующей статистикой тегирования."""
        # Симулируем статистику из tags.py
        legacy_stats = {
            "total_calls": 150,
            "cache_hits": 120,
            "cache_misses": 30,
        }

        integrate_with_tags_stats(legacy_stats)

        # Добавляем новые метрики
        with timer(MetricNames.TAGGING_TAG_TEXT):
            time.sleep(0.01)

        snap = snapshot()

        # Проверяем интегрированную статистику
        assert snap.counters["tagging.total_calls"] == 150
        assert snap.counters["tagging.cache_hits"] == 120
        assert snap.counters["tagging.cache_misses"] == 30

        # Проверяем новые метрики
        assert snap.counters[f"{MetricNames.TAGGING_TAG_TEXT}.success"] == 1
        assert snap.latency[MetricNames.TAGGING_TAG_TEXT]["count"] == 1


class TestMetricSnapshot:
    """Тесты снимков метрик."""

    def setup_method(self):
        """Сброс метрик перед каждым тестом."""
        reset_metrics()

    def test_snapshot_structure(self):
        """Тест структуры снимка метрик."""
        # Добавляем разные типы метрик
        inc("test.counter", 5)
        err("test.error", "Error details")
        observe_latency("test.latency", 123.45)
        track_llm_tokens("test.llm", 100, 50, 150)

        snap = snapshot()

        # Проверяем структуру
        assert isinstance(snap.counters, dict)
        assert isinstance(snap.errors, dict)
        assert isinstance(snap.last_errors, dict)
        assert isinstance(snap.latency, dict)
        assert isinstance(snap.llm_tokens, dict)
        assert isinstance(snap.timestamp, float)

        # Проверяем содержимое
        assert snap.counters["test.counter"] == 5
        assert snap.errors["test.error"] == 1
        assert snap.last_errors["test.error"] == "Error details"
        assert snap.latency["test.latency"]["avg"] == 123.45
        assert snap.llm_tokens["test.llm"]["total_tokens"] == 150

    def test_empty_snapshot(self):
        """Тест пустого снимка."""
        snap = snapshot()

        assert len(snap.counters) == 0
        assert len(snap.errors) == 0
        assert len(snap.last_errors) == 0
        assert len(snap.latency) == 0
        assert len(snap.llm_tokens) == 0
        assert snap.timestamp > 0
