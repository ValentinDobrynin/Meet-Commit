"""
Тесты для модуля app/core/review_queue.py
"""

from unittest.mock import patch

from app.core.review_queue import (
    CLOSED_STATUSES,
    OPEN_STATUSES,
    _get_item_status,
    get_review_stats,
    is_review_closed,
    list_open_reviews,
    should_skip_duplicate,
    validate_review_action,
)


class TestReviewQueueFiltering:
    """Тесты фильтрации открытых Review записей."""

    def test_open_statuses_constants(self):
        """Проверяем константы открытых и закрытых статусов."""
        assert "pending" in OPEN_STATUSES
        assert "needs-review" in OPEN_STATUSES
        assert "resolved" in CLOSED_STATUSES
        assert "dropped" in CLOSED_STATUSES

    def test_is_review_closed(self):
        """Тестируем определение закрытых записей."""
        assert is_review_closed("resolved") is True
        assert is_review_closed("dropped") is True
        assert is_review_closed("pending") is False
        assert is_review_closed("needs-review") is False
        assert is_review_closed("unknown") is False

    def test_get_item_status(self):
        """Тестируем извлечение статуса из элемента."""
        assert _get_item_status({"status": "resolved"}) == "resolved"
        assert _get_item_status({"status": "pending"}) == "pending"
        assert _get_item_status({}) == "pending"  # fallback
        assert _get_item_status({"other": "field"}) == "pending"  # fallback

    @patch('app.core.review_queue._list_pending_raw')
    def test_list_open_reviews_success(self, mock_list_pending):
        """Тестируем успешную загрузку открытых записей."""
        mock_list_pending.return_value = [
            {"id": "1", "status": "pending", "text": "Task 1"},
            {"id": "2", "status": "resolved", "text": "Task 2"},  # Будет отфильтрована
            {"id": "3", "status": "needs-review", "text": "Task 3"},
        ]

        result = list_open_reviews(limit=5)
        
        assert len(result) == 2
        assert result[0]["status"] == "pending"
        assert result[1]["status"] == "needs-review"
        mock_list_pending.assert_called_once_with(5)

    @patch('app.core.review_queue._list_pending_raw')
    def test_list_open_reviews_error_handling(self, mock_list_pending):
        """Тестируем обработку ошибок при загрузке."""
        mock_list_pending.side_effect = Exception("API Error")

        result = list_open_reviews(limit=5)
        
        assert result == []
        mock_list_pending.assert_called_once_with(5)

    def test_should_skip_duplicate_no_duplicates(self):
        """Тестируем случай без дубликатов."""
        existing_reviews = [
            {"key": "key1", "status": "pending"},
            {"key": "key2", "status": "needs-review"},
        ]
        
        assert should_skip_duplicate("key3", existing_reviews) is False

    def test_should_skip_duplicate_with_open_duplicate(self):
        """Тестируем пропуск при наличии открытого дубликата."""
        existing_reviews = [
            {"key": "key1", "status": "pending"},
            {"key": "key2", "status": "needs-review"},
        ]
        
        assert should_skip_duplicate("key1", existing_reviews) is True

    def test_should_skip_duplicate_with_closed_duplicate(self):
        """Тестируем НЕ пропуск при наличии только закрытого дубликата."""
        existing_reviews = [
            {"key": "key1", "status": "resolved"},
            {"key": "key2", "status": "dropped"},
        ]
        
        # Не пропускаем, так как дубликаты закрыты
        assert should_skip_duplicate("key1", existing_reviews) is False


class TestReviewStats:
    """Тесты статистики Review Queue."""

    @patch('app.core.review_queue.list_open_reviews')
    def test_get_review_stats_success(self, mock_list_open):
        """Тестируем успешное получение статистики."""
        mock_list_open.return_value = [
            {"status": "pending"},
            {"status": "pending"},
            {"status": "needs-review"},
        ]

        stats = get_review_stats()
        
        assert stats["total_open"] == 3
        assert stats["status_breakdown"]["pending"] == 2
        assert stats["status_breakdown"]["needs-review"] == 1
        assert stats["open_statuses"] == list(OPEN_STATUSES)
        assert stats["closed_statuses"] == list(CLOSED_STATUSES)

    @patch('app.core.review_queue.list_open_reviews')
    def test_get_review_stats_error(self, mock_list_open):
        """Тестируем обработку ошибок при получении статистики."""
        mock_list_open.side_effect = Exception("Database error")

        stats = get_review_stats()
        
        assert stats["total_open"] == 0
        assert stats["status_breakdown"] == {}
        assert "error" in stats


class TestReviewValidation:
    """Тесты валидации действий над Review записями."""

    def test_validate_review_action_missing_item(self):
        """Тестируем валидацию отсутствующей записи."""
        is_valid, error = validate_review_action(None, "confirm")
        
        assert is_valid is False
        assert "не найдена" in error

    def test_validate_review_action_closed_item(self):
        """Тестируем валидацию закрытой записи."""
        item = {"status": "resolved", "text": "Some task"}
        
        is_valid, error = validate_review_action(item, "confirm")
        
        assert is_valid is False
        assert "закрытой записи" in error
        assert "resolved" in error

    def test_validate_review_action_confirm_no_text(self):
        """Тестируем валидацию confirm без текста."""
        item = {"status": "pending", "text": "", "direction": "mine"}
        
        is_valid, error = validate_review_action(item, "confirm")
        
        assert is_valid is False
        assert "без текста" in error

    def test_validate_review_action_confirm_invalid_direction(self):
        """Тестируем валидацию confirm с некорректным направлением."""
        item = {"status": "pending", "text": "Task text", "direction": "invalid"}
        
        is_valid, error = validate_review_action(item, "confirm")
        
        assert is_valid is False
        assert "Некорректное направление" in error

    def test_validate_review_action_confirm_valid(self):
        """Тестируем успешную валидацию confirm."""
        item = {"status": "pending", "text": "Task text", "direction": "mine"}
        
        is_valid, error = validate_review_action(item, "confirm")
        
        assert is_valid is True
        assert error == ""

    def test_validate_review_action_delete_valid(self):
        """Тестируем успешную валидацию delete."""
        item = {"status": "pending", "text": "Task text"}
        
        is_valid, error = validate_review_action(item, "delete")
        
        assert is_valid is True
        assert error == ""

    def test_validate_review_action_other_actions(self):
        """Тестируем валидацию других действий."""
        item = {"status": "pending", "text": "Task text"}
        
        # flip и assign не требуют специальной валидации
        is_valid, error = validate_review_action(item, "flip")
        assert is_valid is True
        
        is_valid, error = validate_review_action(item, "assign")
        assert is_valid is True


class TestReviewQueueIntegration:
    """Интеграционные тесты Review Queue."""

    @patch('app.core.review_queue._list_pending_raw')
    def test_full_workflow(self, mock_list_pending):
        """Тестируем полный workflow с фильтрацией."""
        # Мокаем данные с разными статусами
        mock_list_pending.return_value = [
            {"id": "1", "status": "pending", "text": "Open task 1", "key": "key1"},
            {"id": "2", "status": "resolved", "text": "Closed task", "key": "key2"},
            {"id": "3", "status": "needs-review", "text": "Open task 2", "key": "key3"},
            {"id": "4", "status": "dropped", "text": "Dropped task", "key": "key4"},
        ]

        # Получаем открытые записи
        open_items = list_open_reviews(limit=10)
        assert len(open_items) == 2  # Только pending и needs-review

        # Проверяем дедупликацию
        assert should_skip_duplicate("key1", open_items) is True  # Есть открытый дубликат
        assert should_skip_duplicate("key2", open_items) is False  # Закрытый дубликат, можно создавать
        assert should_skip_duplicate("key5", open_items) is False  # Нет дубликата

        # Проверяем статистику
        with patch('app.core.review_queue.list_open_reviews', return_value=open_items):
            stats = get_review_stats()
            assert stats["total_open"] == 2
            assert stats["status_breakdown"]["pending"] == 1
            assert stats["status_breakdown"]["needs-review"] == 1
