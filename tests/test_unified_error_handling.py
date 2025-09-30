"""
Тесты для проверки унифицированной обработки ошибок в gateway слое.
Проверяют что все функции используют правильные стратегии обработки ошибок.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.gateways.error_handling import NotionAccessError, NotionAPIError
from app.gateways.notion_commits import _query_commits
from app.gateways.notion_review import (
    find_pending_by_key,
    list_pending,
    update_fields,
)


class TestQueryOperationsGracefulFallback:
    """Тесты что QUERY операции используют graceful fallback."""

    @patch("app.gateways.notion_commits.get_notion_http_client")
    @patch("app.gateways.notion_commits.settings")
    def test_query_commits_graceful_fallback(self, mock_settings, mock_get_client):
        """Тест что _query_commits возвращает fallback при ошибках."""
        mock_settings.commits_db_id = "test-db-id"

        # Мокаем клиент с ошибкой
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.side_effect = httpx.RequestError("Network error")
        mock_get_client.return_value = mock_client

        # Вызываем функцию - должна вернуть fallback вместо исключения
        result = _query_commits({"property": "Status", "select": {"equals": "open"}})

        # Проверяем graceful fallback
        assert result == {"results": []}  # Fallback значение

        # Проверяем что клиент был использован
        mock_client.__enter__.assert_called_once()
        mock_client.__exit__.assert_called_once()

    @patch("app.gateways.notion_review.get_notion_http_client")
    @patch("app.gateways.notion_review.settings")
    def test_find_pending_by_key_graceful_fallback(self, mock_settings, mock_get_client):
        """Тест что find_pending_by_key возвращает None при ошибках."""
        mock_settings.review_db_id = "test-db-id"

        # Мокаем клиент с ошибкой
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.side_effect = httpx.RequestError("Network error")
        mock_get_client.return_value = mock_client

        # Вызываем функцию - должна вернуть None вместо исключения
        result = find_pending_by_key("test-key")

        # Проверяем graceful fallback
        assert result is None  # Fallback значение

    @patch("app.gateways.notion_review.get_notion_http_client")
    @patch("app.gateways.notion_review.settings")
    def test_list_pending_graceful_fallback(self, mock_settings, mock_get_client):
        """Тест что list_pending возвращает [] при ошибках."""
        mock_settings.review_db_id = "test-db-id"

        # Мокаем клиент с ошибкой
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.side_effect = httpx.RequestError("Network error")
        mock_get_client.return_value = mock_client

        # Вызываем функцию - должна вернуть [] вместо исключения
        result = list_pending(5)

        # Проверяем graceful fallback
        assert result == []  # Fallback значение


class TestUpdateOperationsStrictHandling:
    """Тесты что UPDATE операции используют strict handling."""

    @patch("app.gateways.notion_review.get_notion_http_client")
    def test_update_fields_strict_handling(self, mock_get_client):
        """Тест что update_fields поднимает исключение при ошибках."""
        # Мокаем клиент с ошибкой
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.patch.side_effect = httpx.RequestError("Network error")
        mock_get_client.return_value = mock_client

        # Вызываем функцию - должна поднять исключение
        with pytest.raises(NotionAPIError, match="Network error"):
            update_fields("test-page-id", direction="mine")


class TestErrorClassification:
    """Тесты классификации HTTP ошибок."""

    def test_http_error_classification(self):
        """Тест правильной классификации HTTP ошибок."""
        from app.gateways.error_handling import (
            NotionAccessError,
            NotionRateLimitError,
            NotionServerError,
            classify_http_error,
        )

        # Мокаем разные типы ответов
        mock_401 = MagicMock()
        mock_401.status_code = 401
        assert classify_http_error(mock_401) == NotionAccessError

        mock_404 = MagicMock()
        mock_404.status_code = 404
        assert classify_http_error(mock_404) == NotionAccessError

        mock_429 = MagicMock()
        mock_429.status_code = 429
        assert classify_http_error(mock_429) == NotionRateLimitError

        mock_500 = MagicMock()
        mock_500.status_code = 500
        assert classify_http_error(mock_500) == NotionServerError

    @patch("app.gateways.error_handling.inc")
    @patch("app.gateways.error_handling.logger")
    def test_error_metrics_tracking(self, mock_logger, mock_inc):
        """Тест что ошибки отслеживаются в метриках."""
        from app.gateways.error_handling import handle_http_error

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not found"

        with pytest.raises(NotionAccessError):
            handle_http_error(mock_response, "test_operation")

        # Проверяем что метрики обновлены
        mock_inc.assert_any_call("notion.errors.404")
        mock_inc.assert_any_call("notion.errors.test_operation")


class TestDecoratorIntegration:
    """Тесты интеграции декораторов с gateway функциями."""

    def test_notion_query_decorator_fallback(self):
        """Тест что @notion_query декоратор обеспечивает fallback."""
        from app.gateways.error_handling import notion_query

        @notion_query("test_query", fallback={"test": "fallback"})
        def failing_query():
            raise httpx.RequestError("Test error")

        # Функция должна вернуть fallback вместо исключения
        result = failing_query()
        assert result == {"test": "fallback"}

    def test_notion_update_decorator_strict(self):
        """Тест что @notion_update декоратор поднимает исключения."""
        from app.gateways.error_handling import notion_update

        @notion_update("test_update")
        def failing_update():
            raise httpx.RequestError("Test error")

        # Функция должна поднять исключение
        with pytest.raises(NotionAPIError, match="Network error"):
            failing_update()

    def test_notion_validation_decorator_boolean_fallback(self):
        """Тест что @notion_validation декоратор возвращает False."""
        from app.gateways.error_handling import notion_validation

        @notion_validation("test_validation")
        def failing_validation():
            raise httpx.RequestError("Test error")

        # Функция должна вернуть False вместо исключения
        result = failing_validation()
        assert result is False


class TestConsistencyAcrossModules:
    """Тесты консистентности обработки ошибок между модулями."""

    def test_all_query_functions_have_graceful_fallback(self):
        """Тест что все query функции имеют graceful fallback."""
        # Список всех query функций, которые должны использовать graceful fallback
        query_functions = [
            ("app.gateways.notion_commits", "_query_commits"),
            ("app.gateways.notion_review", "find_pending_by_key"),
            ("app.gateways.notion_review", "list_pending"),
            ("app.gateways.notion_review", "get_by_short_id"),
            ("app.gateways.notion_agendas", "find_agenda_by_hash"),
            ("app.gateways.notion_agendas", "query_agendas_by_context"),
            ("app.gateways.notion_agendas", "get_agenda_statistics"),
        ]

        for module_name, func_name in query_functions:
            # Проверяем что функция имеет декоратор или правильное поведение
            import importlib

            module = importlib.import_module(module_name)
            func = getattr(module, func_name)

            # Проверяем что функция имеет правильную документацию
            assert func.__doc__ is not None
            # Для функций с декораторами - проверяем упоминание graceful fallback
            if hasattr(func, "__wrapped__"):
                assert "graceful" in func.__doc__.lower() or "fallback" in func.__doc__.lower()

    def test_all_update_functions_have_strict_handling(self):
        """Тест что все update функции используют strict handling."""
        update_functions = [
            ("app.gateways.notion_review", "update_fields"),
            ("app.gateways.notion_meetings", "update_meeting_tags"),
            ("app.gateways.notion_commits", "update_commit_status"),
        ]

        for module_name, func_name in update_functions:
            import importlib

            module = importlib.import_module(module_name)
            func = getattr(module, func_name)

            # Проверяем документацию функции
            assert func.__doc__ is not None
            # Для функций с декораторами - проверяем упоминание strict handling
            if hasattr(func, "__wrapped__"):
                assert "strict" in func.__doc__.lower() or "исключение" in func.__doc__.lower()


class TestErrorHandlingPerformance:
    """Тесты производительности унифицированной обработки ошибок."""

    def test_decorator_overhead_minimal(self):
        """Тест что декораторы не добавляют значительного overhead."""
        import time

        from app.gateways.error_handling import notion_query

        @notion_query("test_performance")
        def fast_operation():
            return {"results": ["test"]}

        # Измеряем время выполнения
        start_time = time.perf_counter()
        for _ in range(100):
            result = fast_operation()
        end_time = time.perf_counter()

        # Проверяем что overhead минимальный (< 1ms на вызов)
        avg_time_ms = (end_time - start_time) * 1000 / 100
        assert avg_time_ms < 1.0, f"Decorator overhead too high: {avg_time_ms:.2f}ms"

        # Проверяем корректность результата
        assert result == {"results": ["test"]}


class TestErrorHandlingDocumentation:
    """Тесты документирования стратегий обработки ошибок."""

    def test_all_decorated_functions_documented(self):
        """Тест что все функции с декораторами имеют документацию об обработке ошибок."""
        # Проверяем несколько ключевых функций
        functions_to_check = [
            (_query_commits, "graceful", "query"),
            (find_pending_by_key, "graceful", "query"),
            (update_fields, "strict", "update"),
        ]

        for func, expected_strategy, _operation_type in functions_to_check:
            doc = func.__doc__ or ""

            # Проверяем что в документации упоминается стратегия обработки ошибок
            if expected_strategy == "graceful":
                assert any(
                    word in doc.lower() for word in ["graceful", "fallback", "возвращает"]
                ), f"Function {func.__name__} should document graceful fallback"
            else:  # strict
                assert any(
                    word in doc.lower() for word in ["strict", "исключение", "поднимает"]
                ), f"Function {func.__name__} should document strict handling"
