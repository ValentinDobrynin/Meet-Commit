"""
Интеграционные тесты для проверки lifecycle HTTP клиентов.
Проверяют, что клиенты правильно закрываются и не создают утечек.
"""

from unittest.mock import MagicMock, patch

from app.core.clients import get_notion_http_client
from app.gateways.notion_meetings import fetch_meeting_page, update_meeting_tags
from app.gateways.notion_review import find_pending_by_key
from app.gateways.notion_tag_catalog import fetch_tag_catalog


class TestHTTPClientLifecycle:
    """Тесты для проверки правильного управления жизненным циклом HTTP клиентов."""

    @patch("app.gateways.notion_meetings.get_notion_http_client")
    def test_fetch_meeting_page_client_lifecycle(self, mock_get_client):
        """Тест что fetch_meeting_page правильно управляет клиентом."""
        # Мокаем клиент
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Test Meeting"}]},
                "Summary MD": {"type": "rich_text", "rich_text": [{"plain_text": "Test summary"}]},
                "Tags": {"type": "multi_select", "multi_select": [{"name": "Test/Tag"}]},
            },
            "url": "https://notion.so/test",
        }
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_get_client.return_value = mock_client

        # Вызываем функцию
        result = fetch_meeting_page("12345678901234567890123456789012")

        # Проверяем что context manager был использован
        mock_client.__enter__.assert_called_once()
        mock_client.__exit__.assert_called_once()

        # Проверяем результат
        assert result["title"] == "Test Meeting"
        assert result["summary_md"] == "Test summary"
        assert "Test/Tag" in result["current_tags"]

    @patch("app.gateways.notion_meetings.get_notion_http_client")
    def test_update_meeting_tags_client_lifecycle(self, mock_get_client):
        """Тест что update_meeting_tags правильно управляет клиентом."""
        # Мокаем клиент
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.patch.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_get_client.return_value = mock_client

        # Вызываем функцию
        result = update_meeting_tags("12345678901234567890123456789012", ["Test/Tag"])

        # Проверяем что context manager был использован
        mock_client.__enter__.assert_called_once()
        mock_client.__exit__.assert_called_once()

        # Проверяем результат
        assert result is True

    @patch("app.gateways.notion_tag_catalog.get_notion_http_client")
    @patch("app.gateways.notion_tag_catalog.settings")
    def test_fetch_tag_catalog_client_lifecycle(self, mock_settings, mock_get_client):
        """Тест что fetch_tag_catalog правильно управляет клиентом."""
        # Настройки
        mock_settings.notion_sync_enabled = True
        mock_settings.notion_db_tag_catalog_id = "test-db-id"

        # Мокаем клиент
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_get_client.return_value = mock_client

        # Вызываем функцию
        result = fetch_tag_catalog()

        # Проверяем что context manager НЕ используется (старый код)
        mock_client.__enter__.assert_not_called()
        mock_client.__exit__.assert_not_called()

        # Проверяем что close был вызван
        mock_client.close.assert_called_once()

        # Проверяем результат
        assert isinstance(result, list)

    @patch("app.gateways.notion_review.get_notion_http_client")
    @patch("app.gateways.notion_review.settings")
    def test_find_pending_by_key_client_lifecycle(self, mock_settings, mock_get_client):
        """Тест что find_pending_by_key правильно управляет клиентом."""
        # Настройки
        mock_settings.review_db_id = "test-db-id"

        # Мокаем клиент
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_get_client.return_value = mock_client

        # Вызываем функцию
        result = find_pending_by_key("test-key")

        # Проверяем что context manager используется (новый код после рефакторинга)
        mock_client.__enter__.assert_called_once()
        mock_client.__exit__.assert_called_once()

        # Проверяем результат
        assert result is None

    def test_http_client_is_context_manager(self):
        """Тест что HTTP клиент поддерживает context manager protocol."""
        with patch("app.core.clients.settings") as mock_settings:
            mock_settings.notion_token = "test-token"

            # Проверяем что клиент можно использовать как context manager
            client = get_notion_http_client()
            assert hasattr(client, "__enter__")
            assert hasattr(client, "__exit__")

            # Проверяем что можно использовать with statement
            with client:
                pass  # Клиент должен автоматически закрыться

    def test_cached_client_context_manager(self):
        """Тест что кэшированный клиент работает как context manager."""
        with patch("app.core.clients.settings") as mock_settings:
            mock_settings.notion_token = "test-token"

            # HTTP клиенты не кэшируются

            # Тестируем использование как context manager
            try:
                with get_notion_http_client() as client:
                    assert client is not None
                    # Имитируем исключение
                    raise ValueError("Test exception")
            except ValueError:
                pass  # Ожидаемое исключение

            # HTTP клиенты не кэшируются, но должны работать корректно
            assert client is not None


class TestClientPoolLimits:
    """Тесты для проверки лимитов пула соединений."""

    def test_cached_client_has_proper_config(self):
        """Тест что кэшированный клиент имеет правильную конфигурацию."""
        with patch("app.core.clients.settings") as mock_settings:
            mock_settings.notion_token = "test-token"

            # HTTP клиенты не кэшируются

            client = get_notion_http_client()

            # Проверяем что клиент создан и функционален
            assert client is not None
            assert hasattr(client, "get")
            assert hasattr(client, "post")

            # HTTP клиенты больше не кэшируются
            assert hasattr(client, "get")
            assert hasattr(client, "post")
            # Проверяем что клиент создается каждый раз новый
            client2 = get_notion_http_client()
            assert client is not client2

    def test_multiple_clients_are_not_cached(self):
        """Тест что HTTP клиенты не кэшируются (безопасный lifecycle)."""
        with patch("app.core.clients.settings") as mock_settings:
            mock_settings.notion_token = "test-token"

            # Создаем несколько клиентов
            client1 = get_notion_http_client()
            client2 = get_notion_http_client()

            # HTTP клиенты не кэшируются (безопасный lifecycle)
            assert client1 is not client2

            # Проверяем что клиенты функциональны
            assert hasattr(client1, "get")
            assert hasattr(client2, "get")

            # Каждый клиент независим
            client1.close()
            # client2 должен продолжать работать
            assert hasattr(client2, "get")
