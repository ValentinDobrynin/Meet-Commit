"""
Тесты для сервиса массового перетегирования app/core/retag_service.py

Покрывает:
- Валидацию параметров
- Композицию текста для тегирования
- Статистику операций
- Оценку времени выполнения
- Обработку ошибок
"""

from unittest.mock import patch

from app.core.retag_service import (
    RetagStats,
    _compose_commit_text,
    _compose_meeting_text,
    estimate_retag_time,
    retag,
    validate_retag_params,
)


class TestRetagStats:
    """Тесты класса статистики перетегирования."""

    def test_stats_initialization(self):
        """Тест инициализации статистики."""
        stats = RetagStats()

        assert stats.scanned == 0
        assert stats.updated == 0
        assert stats.skipped == 0
        assert stats.errors == 0
        assert stats.latency_s == 0.0
        assert isinstance(stats.dedup_metrics_total, dict)

    def test_stats_as_dict(self):
        """Тест преобразования статистики в словарь."""
        stats = RetagStats()
        stats.scanned = 10
        stats.updated = 5
        stats.errors = 1
        stats.latency_s = 2.5

        result = stats.as_dict()

        assert isinstance(result, dict)
        assert result["summary"]["scanned"] == 10
        assert result["summary"]["updated"] == 5
        assert result["summary"]["errors"] == 1
        assert result["performance"]["total_time_s"] == 2.5
        assert "tagging" in result
        assert "details" in result


class TestTextComposition:
    """Тесты композиции текста для тегирования."""

    def test_compose_meeting_text_full(self):
        """Тест композиции полного текста встречи."""
        meeting = {
            "Name": "Планирование Q4 2024",
            "Summary MD": "Обсудили бюджет и планы на квартал.",
        }

        result = _compose_meeting_text(meeting)

        assert "Планирование Q4 2024" in result
        assert "Обсудили бюджет и планы на квартал." in result
        assert "\n\n" in result  # Разделитель между частями

    def test_compose_meeting_text_partial(self):
        """Тест композиции частичного текста встречи."""
        # Только заголовок
        meeting1 = {"Name": "Встреча команды"}
        result1 = _compose_meeting_text(meeting1)
        assert result1 == "Встреча команды"

        # Только содержимое
        meeting2 = {"Summary MD": "Обсудили планы"}
        result2 = _compose_meeting_text(meeting2)
        assert result2 == "Обсудили планы"

        # Пустые данные
        meeting3 = {}
        result3 = _compose_meeting_text(meeting3)
        assert result3 == ""

    def test_compose_commit_text_full(self):
        """Тест композиции полного текста коммита."""
        commit = {"Text": "подготовить отчет по продажам", "Context": "для встречи с руководством"}

        result = _compose_commit_text(commit)

        assert "подготовить отчет по продажам" in result
        assert "для встречи с руководством" in result
        assert "\n\n" in result

    def test_compose_commit_text_partial(self):
        """Тест композиции частичного текста коммита."""
        # Только основной текст
        commit1 = {"Text": "подготовить презентацию"}
        result1 = _compose_commit_text(commit1)
        assert result1 == "подготовить презентацию"

        # Пустые данные
        commit2 = {}
        result2 = _compose_commit_text(commit2)
        assert result2 == ""


class TestParameterValidation:
    """Тесты валидации параметров."""

    def test_valid_parameters(self):
        """Тест валидных параметров."""
        valid_cases = [
            ("meetings", None, None, "both"),
            ("commits", "2024-12-01", 100, "v1"),
            ("meetings", "2024-01-01", 1000, "v0"),
        ]

        for db, since_iso, limit, mode in valid_cases:
            is_valid, error_msg = validate_retag_params(db, since_iso, limit, mode)
            assert (
                is_valid
            ), f"Should be valid: {db}, {since_iso}, {limit}, {mode}. Error: {error_msg}"
            assert error_msg == ""

    def test_invalid_db_parameter(self):
        """Тест невалидного параметра базы данных."""
        is_valid, error_msg = validate_retag_params("invalid_db", None, None, "both")

        assert not is_valid
        assert "Неверный тип базы" in error_msg
        assert "invalid_db" in error_msg

    def test_invalid_date_parameter(self):
        """Тест невалидного параметра даты."""
        invalid_dates = [
            "2024-13-01",  # Неверный месяц
            "2024/12/01",  # Неверный формат
            "01-12-2024",  # Неверный порядок
            "invalid",  # Не дата
        ]

        for invalid_date in invalid_dates:
            is_valid, error_msg = validate_retag_params("meetings", invalid_date, None, "both")
            assert not is_valid, f"Date should be invalid: {invalid_date}"
            # Проверяем что есть сообщение об ошибке даты (может быть разное)
            assert any(
                keyword in error_msg for keyword in ["Неверный формат даты", "Невалидная дата"]
            )

    def test_invalid_limit_parameter(self):
        """Тест невалидного параметра лимита."""
        invalid_limits = [
            0,  # Ноль
            -10,  # Отрицательное
            10001,  # Слишком большое
            "abc",  # Не число
        ]

        for invalid_limit in invalid_limits:
            is_valid, error_msg = validate_retag_params("meetings", None, invalid_limit, "both")
            assert not is_valid, f"Limit should be invalid: {invalid_limit}"

    def test_invalid_mode_parameter(self):
        """Тест невалидного параметра режима."""
        is_valid, error_msg = validate_retag_params("meetings", None, None, "invalid_mode")

        assert not is_valid
        assert "Неверный режим" in error_msg
        assert "invalid_mode" in error_msg


class TestTimeEstimation:
    """Тесты оценки времени выполнения."""

    def test_basic_time_estimation(self):
        """Тест базовой оценки времени."""
        estimate = estimate_retag_time("meetings", None, 100)

        assert isinstance(estimate, dict)
        assert "estimated_items" in estimate
        assert "estimated_time_seconds" in estimate
        assert "estimated_time_minutes" in estimate
        assert "base_time_per_item_ms" in estimate

        assert estimate["estimated_items"] == 100
        assert estimate["estimated_time_seconds"] > 0
        assert estimate["estimated_time_minutes"] > 0

    def test_different_db_types_estimation(self):
        """Тест оценки для разных типов баз данных."""
        meetings_estimate = estimate_retag_time("meetings", None, 100)
        commits_estimate = estimate_retag_time("commits", None, 100)

        # Встречи должны занимать больше времени чем коммиты
        assert (
            meetings_estimate["estimated_time_seconds"] > commits_estimate["estimated_time_seconds"]
        )
        assert (
            meetings_estimate["base_time_per_item_ms"] > commits_estimate["base_time_per_item_ms"]
        )

    def test_default_limit_estimation(self):
        """Тест оценки с лимитом по умолчанию."""
        estimate = estimate_retag_time("meetings")

        # Должен использовать значение по умолчанию
        assert estimate["estimated_items"] == 1000


class TestRetagFunction:
    """Тесты основной функции перетегирования."""

    @patch("app.core.retag_service.iter_meetings")
    @patch("app.core.retag_service.update_meeting_tags")
    @patch("app.core.retag_service.tag_text")
    def test_retag_meetings_dry_run(self, mock_tag_text, mock_update, mock_iter):
        """Тест dry-run режима для встреч."""
        # Мокаем данные
        mock_iter.return_value = [
            [
                {
                    "id": "test-meeting-1",
                    "Name": "Тест встреча",
                    "Summary MD": "Обсудили бюджет",
                    "Tags": ["Finance/Budget"],
                }
            ]
        ]
        mock_tag_text.return_value = ["Finance/Budget", "Topic/Planning"]

        # Выполняем dry-run
        stats = retag(db="meetings", dry_run=True)

        # Проверяем что update не вызывался
        mock_update.assert_not_called()

        # Проверяем статистику
        assert stats.scanned == 1
        assert stats.updated == 1  # В dry-run считается как обновленный
        assert stats.errors == 0

    @patch("app.core.retag_service.iter_commits")
    @patch("app.core.retag_service.update_commit_tags")
    @patch("app.core.retag_service.tag_text")
    def test_retag_commits_real_run(self, mock_tag_text, mock_update, mock_iter):
        """Тест реального режима для коммитов."""
        # Мокаем данные
        mock_iter.return_value = [
            [
                {
                    "id": "test-commit-1",
                    "Text": "подготовить отчет",
                    "Tags": ["Topic/Task"],
                    "Context": "",
                }
            ]
        ]
        mock_tag_text.return_value = ["Topic/Task", "Finance/Reporting"]
        mock_update.return_value = True

        # Выполняем реальное обновление
        stats = retag(db="commits", dry_run=False)

        # Проверяем что update вызывался (порядок может отличаться из-за сортировки)
        mock_update.assert_called_once()
        call_args = mock_update.call_args[0]
        assert call_args[0] == "test-commit-1"
        assert set(call_args[1]) == {"Topic/Task", "Finance/Reporting"}

        # Проверяем статистику
        assert stats.scanned == 1
        assert stats.updated == 1
        assert stats.errors == 0

    @patch("app.core.retag_service.iter_meetings")
    def test_retag_with_limit(self, mock_iter):
        """Тест работы с лимитом записей."""
        # Мокаем большой набор данных
        large_batch = [
            {"id": f"meeting-{i}", "Name": f"Meeting {i}", "Summary MD": "Test", "Tags": []}
            for i in range(150)
        ]
        mock_iter.return_value = [large_batch]

        # Применяем лимит
        stats = retag(db="meetings", limit=50, dry_run=True)

        # Должно обработать только 50 записей
        assert stats.scanned == 50

    @patch("app.core.retag_service.iter_meetings")
    def test_retag_no_changes_scenario(self, mock_iter):
        """Тест сценария без изменений."""
        # Мокаем данные где новые теги совпадают со старыми
        mock_iter.return_value = [
            [
                {
                    "id": "test-meeting-1",
                    "Name": "Test",
                    "Summary MD": "Test content",
                    "Tags": ["Finance/Budget"],
                }
            ]
        ]

        with patch("app.core.retag_service.tag_text") as mock_tag_text:
            mock_tag_text.return_value = ["Finance/Budget"]  # Те же теги

            stats = retag(db="meetings", dry_run=True)

            assert stats.scanned == 1
            assert stats.skipped == 1  # Пропущено из-за отсутствия изменений
            assert stats.updated == 0

    @patch("app.core.retag_service.iter_meetings")
    def test_retag_error_handling(self, mock_iter):
        """Тест обработки ошибок."""
        # Мокаем данные с проблемным элементом
        mock_iter.return_value = [
            [
                {
                    "id": "test-meeting-1",
                    "Name": "Test",
                    "Summary MD": "Test content",
                    "Tags": ["Finance/Budget"],
                }
            ]
        ]

        with patch("app.core.retag_service.tag_text") as mock_tag_text:
            mock_tag_text.side_effect = Exception("Test error")

            stats = retag(db="meetings", dry_run=True)

            assert stats.scanned == 1
            assert stats.errors == 1
            assert stats.updated == 0

    def test_retag_empty_text_handling(self):
        """Тест обработки пустого текста."""
        with patch("app.core.retag_service.iter_meetings") as mock_iter:
            mock_iter.return_value = [
                [
                    {
                        "id": "test-meeting-1",
                        "Name": "",
                        "Summary MD": "   ",  # Только пробелы
                        "Tags": [],
                    }
                ]
            ]

            stats = retag(db="meetings", dry_run=True)

            assert stats.scanned == 1
            assert stats.empty_text == 1
            assert stats.skipped == 1


# Дублирующиеся классы TestParameterValidation и TestTimeEstimation удалены - используются версии выше


class TestIntegrationScenarios:
    """Тесты интеграционных сценариев."""

    @patch("app.core.retag_service.iter_meetings")
    @patch("app.core.retag_service.update_meeting_tags")
    @patch("app.core.retag_service.tag_text")
    @patch("app.core.retag_service.dedup_fuse")
    def test_both_mode_with_dedup_metrics(self, mock_dedup, mock_tag_text, mock_update, mock_iter):
        """Тест режима 'both' с метриками дедупликации."""
        # Мокаем данные
        mock_iter.return_value = [
            [
                {
                    "id": "test-meeting-1",
                    "Name": "Test Meeting",
                    "Summary MD": "Test content",
                    "Tags": ["Finance/Budget"],
                }
            ]
        ]

        # Мокаем результаты тегирования
        mock_tag_text.side_effect = [
            ["Topic/Planning", "Finance/Budget"],  # v0 результат
            ["Finance/IFRS", "Business/Lavka"],  # v1 результат
        ]

        # Мокаем дедупликацию
        from app.core.tags_dedup import DedupMetrics

        mock_metrics = DedupMetrics()
        mock_metrics.conflicts_resolved = 1
        mock_metrics.v1_priority_wins = 1
        mock_dedup.return_value = (
            ["Finance/IFRS", "Business/Lavka", "Topic/Planning"],
            mock_metrics,
        )

        mock_update.return_value = True

        # Выполняем операцию
        stats = retag(db="meetings", mode="both", dry_run=False)

        # Проверяем что dedup_fuse вызывался
        mock_dedup.assert_called_once()

        # Проверяем что метрики дедупликации собираются
        assert len(stats.dedup_metrics_total) > 0

        # Проверяем что tag_text вызывался дважды (для v0 и v1)
        assert mock_tag_text.call_count == 2

    def test_since_date_filtering(self):
        """Тест фильтрации по дате."""
        with patch("app.core.retag_service.iter_meetings") as mock_iter:
            mock_iter.return_value = []  # Пустой результат

            stats = retag(db="meetings", since_iso="2024-12-01", dry_run=True)

            # Проверяем что итератор вызывался с правильными параметрами
            mock_iter.assert_called_once_with(since_iso="2024-12-01", page_size=100)

            assert stats.scanned == 0


class TestErrorHandling:
    """Тесты обработки ошибок."""

    @patch("app.core.retag_service.iter_meetings")
    def test_iterator_exception_handling(self, mock_iter):
        """Тест обработки исключений в итераторе."""
        mock_iter.side_effect = Exception("Iterator error")

        stats = retag(db="meetings", dry_run=True)

        # Операция должна завершиться с ошибкой но не упасть
        assert stats.errors >= 1
        assert stats.latency_s > 0

    @patch("app.core.retag_service.iter_meetings")
    @patch("app.core.retag_service.tag_text")
    def test_tagging_exception_handling(self, mock_tag_text, mock_iter):
        """Тест обработки исключений в тегировании."""
        mock_iter.return_value = [
            [{"id": "test-1", "Name": "Test", "Summary MD": "Content", "Tags": []}]
        ]
        mock_tag_text.side_effect = Exception("Tagging error")

        stats = retag(db="meetings", dry_run=True)

        assert stats.scanned == 1
        assert stats.errors == 1
        assert stats.updated == 0

    @patch("app.core.retag_service.iter_meetings")
    @patch("app.core.retag_service.update_meeting_tags")
    @patch("app.core.retag_service.tag_text")
    def test_update_exception_handling(self, mock_tag_text, mock_update, mock_iter):
        """Тест обработки исключений при обновлении."""
        mock_iter.return_value = [
            [{"id": "test-1", "Name": "Test", "Summary MD": "Content", "Tags": []}]
        ]
        mock_tag_text.return_value = ["Finance/Budget"]
        mock_update.side_effect = Exception("Update error")

        stats = retag(db="meetings", dry_run=False)

        assert stats.scanned == 1
        assert stats.api_errors == 1
        assert stats.errors == 1
        assert stats.updated == 0
