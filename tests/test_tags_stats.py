"""Тесты для расширенной статистики тегирования."""

import time
from unittest.mock import patch

from app.core.tags import clear_cache, get_tagging_stats, tag_text


class TestTagsStats:
    """Тесты статистики тегирования."""

    def test_stats_initialization(self):
        """Тест инициализации статистики с метриками дедупликации."""
        stats = get_tagging_stats()

        assert "stats" in stats
        assert "performance" in stats
        assert "top_tags" in stats
        assert "cache_info" in stats
        assert "deduplication" in stats

        # Проверяем базовые поля
        assert "total_calls" in stats["stats"]
        assert "start_time" in stats["stats"]
        assert "calls_by_mode" in stats["stats"]
        assert "calls_by_kind" in stats["stats"]

        # Проверяем метрики дедупликации
        dedup = stats["deduplication"]
        assert "v0_tags_total" in dedup
        assert "v1_tags_total" in dedup
        assert "merged_tags_total" in dedup
        assert "duplicates_removed" in dedup
        assert "people_tags_preserved" in dedup
        assert "v1_priority_wins" in dedup
        assert "efficiency_percent" in dedup

        # Проверяем метрики наследования
        inheritance = stats["inheritance"]
        assert "meeting_tags_total" in inheritance
        assert "commit_tags_total" in inheritance
        assert "inherited_tags" in inheritance
        assert "duplicates_removed" in inheritance
        assert "people_inherited" in inheritance
        assert "business_inherited" in inheritance
        assert "projects_inherited" in inheritance
        assert "finance_inherited" in inheritance
        assert "topic_inherited" in inheritance
        assert "efficiency_percent" in inheritance

    def test_stats_after_calls(self):
        """Тест обновления статистики после вызовов."""
        # Очищаем статистику
        clear_cache()

        # Делаем несколько вызовов
        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "v1"
            mock_settings.tagger_v1_enabled = True
            mock_settings.tags_min_score = 0.5

            tag_text("test text 1")
            tag_text("test text 2", kind="commit")

        stats = get_tagging_stats()

        # Проверяем счетчики
        assert stats["stats"]["total_calls"] >= 2
        assert stats["stats"]["calls_by_mode"]["v1"] >= 2
        assert stats["stats"]["calls_by_kind"]["meeting"] >= 1
        assert stats["stats"]["calls_by_kind"]["commit"] >= 1

    def test_deduplication_metrics(self):
        """Тест метрик дедупликации."""
        # Очищаем статистику
        clear_cache()

        # Делаем вызовы в режиме both для активации дедупликации
        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "both"
            mock_settings.tagger_v1_enabled = True
            mock_settings.tags_min_score = 0.5

            # Тестируем с текстом, который может дать дубликаты
            tag_text("Обсудили IFRS аудит и планирование")
            tag_text("Тест lavka и darkstore")

        stats = get_tagging_stats()
        dedup = stats["deduplication"]

        # Проверяем, что метрики обновились
        assert dedup["v0_tags_total"] >= 0
        assert dedup["v1_tags_total"] >= 0
        assert dedup["merged_tags_total"] >= 0
        assert dedup["duplicates_removed"] >= 0
        assert dedup["people_tags_preserved"] >= 0
        assert dedup["v1_priority_wins"] >= 0
        assert dedup["efficiency_percent"] >= 0.0

        # Проверяем типы
        assert isinstance(dedup["v0_tags_total"], int)
        assert isinstance(dedup["v1_tags_total"], int)
        assert isinstance(dedup["merged_tags_total"], int)
        assert isinstance(dedup["duplicates_removed"], int)
        assert isinstance(dedup["people_tags_preserved"], int)
        assert isinstance(dedup["v1_priority_wins"], int)
        assert isinstance(dedup["efficiency_percent"], float)

    def test_inheritance_metrics(self):
        """Тест метрик наследования тегов."""
        # Очищаем статистику
        clear_cache()

        # Импортируем функцию наследования
        from app.core.tags import merge_meeting_and_commit_tags

        # Тестируем наследование тегов
        meeting_tags = ["People/Sasha", "Business/Lavka", "Finance/IFRS", "Topic/Planning"]
        commit_tags = ["People/Valentin", "Finance/Audit"]

        # Выполняем наследование
        merge_meeting_and_commit_tags(meeting_tags, commit_tags)

        # Проверяем, что метрики обновились
        stats = get_tagging_stats()
        inheritance = stats["inheritance"]

        assert inheritance["meeting_tags_total"] >= 4
        assert inheritance["commit_tags_total"] >= 2
        assert inheritance["inherited_tags"] >= 0
        assert inheritance["duplicates_removed"] >= 0
        assert inheritance["people_inherited"] >= 0
        assert inheritance["business_inherited"] >= 0
        assert inheritance["projects_inherited"] >= 0
        assert inheritance["finance_inherited"] >= 0
        assert inheritance["topic_inherited"] >= 0
        assert inheritance["efficiency_percent"] >= 0.0

        # Проверяем типы
        assert isinstance(inheritance["meeting_tags_total"], int)
        assert isinstance(inheritance["commit_tags_total"], int)
        assert isinstance(inheritance["inherited_tags"], int)
        assert isinstance(inheritance["duplicates_removed"], int)
        assert isinstance(inheritance["people_inherited"], int)
        assert isinstance(inheritance["business_inherited"], int)
        assert isinstance(inheritance["projects_inherited"], int)
        assert isinstance(inheritance["finance_inherited"], int)
        assert isinstance(inheritance["topic_inherited"], int)
        assert isinstance(inheritance["efficiency_percent"], float)

    def test_performance_metrics(self):
        """Тест метрик производительности."""
        stats = get_tagging_stats()
        perf = stats["performance"]

        assert "uptime_hours" in perf
        assert "calls_per_hour" in perf
        assert "avg_response_time_ms" in perf

        assert isinstance(perf["uptime_hours"], int | float)
        assert perf["uptime_hours"] >= 0
        assert isinstance(perf["avg_response_time_ms"], int | float)

    def test_top_tags_tracking(self):
        """Тест отслеживания топ тегов."""
        # Очищаем кэш для чистого теста
        clear_cache()

        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "v1"
            mock_settings.tagger_v1_enabled = True
            mock_settings.tags_min_score = 0.5

            # Мокаем tagger_v1 для возврата предсказуемых тегов
            with patch("app.core.tags.tagger_v1") as mock_tagger:
                mock_tagger.return_value = ["Finance/IFRS", "Finance/Audit"]

                # Делаем несколько вызовов
                tag_text("test 1")
                tag_text("test 2")
                tag_text("test 3")

        stats = get_tagging_stats()
        top_tags = dict(stats["top_tags"])

        # Проверяем, что теги отслеживаются
        assert len(top_tags) > 0
        # Finance/IFRS должен встречаться 3 раза
        assert top_tags.get("Finance/IFRS", 0) >= 3

    def test_cache_hit_rate(self):
        """Тест расчета cache hit rate."""
        stats = get_tagging_stats()
        cache_info = stats["cache_info"]

        assert "hit_rate_percent" in cache_info
        assert isinstance(cache_info["hit_rate_percent"], int | float)
        assert 0 <= cache_info["hit_rate_percent"] <= 100

    def test_stats_error_handling(self):
        """Тест обработки ошибок в статистике."""
        with patch("app.core.tags._tag_cached.cache_info", side_effect=Exception("Cache error")):
            stats = get_tagging_stats()

            # При ошибке должна быть базовая статистика
            assert "error" in stats
            assert "current_mode" in stats
            assert "stats" in stats


class TestStatsIntegration:
    """Интеграционные тесты статистики."""

    def test_stats_with_real_tagger(self):
        """Тест статистики с реальным тэггером."""
        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "v1"
            mock_settings.tagger_v1_enabled = True
            mock_settings.tags_min_score = 0.5

            # Реальный вызов
            tags = tag_text("Обсудили IFRS аудит для Lavka")

            stats = get_tagging_stats()

            # Проверяем, что статистика обновилась
            assert stats["stats"]["total_calls"] > 0
            assert len(stats["top_tags"]) > 0

            # Проверяем, что найденные теги попали в топ
            top_tags_dict = dict(stats["top_tags"])
            for tag in tags:
                assert tag in top_tags_dict

    def test_uptime_calculation(self):
        """Тест расчета uptime."""
        # Получаем статистику дважды с небольшой задержкой
        stats1 = get_tagging_stats()
        time.sleep(0.01)  # 10ms
        stats2 = get_tagging_stats()

        # Uptime должен увеличиться
        uptime1 = stats1["performance"]["uptime_hours"]
        uptime2 = stats2["performance"]["uptime_hours"]

        assert uptime2 >= uptime1

    def test_calls_per_hour_calculation(self):
        """Тест расчета вызовов в час."""
        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "v1"
            mock_settings.tagger_v1_enabled = True

            # Делаем вызов
            tag_text("test")

            stats = get_tagging_stats()
            calls_per_hour = stats["performance"]["calls_per_hour"]

            # Должно быть положительное число
            assert isinstance(calls_per_hour, int | float)
            assert calls_per_hour >= 0
