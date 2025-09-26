"""
Тесты для единого модуля клиентов.
"""

from unittest.mock import patch

import pytest
from notion_client import Client as NotionClient
from openai import AsyncOpenAI, OpenAI

from app.core.clients import (
    ClientError,
    NotionClientError,
    OpenAIClientError,
    clear_clients_cache,
    get_clients_info,
    get_notion_client,
    get_notion_http_client,
    get_openai_client,
    get_openai_parse_client,
)


class TestNotionClients:
    """Тесты Notion клиентов."""

    @patch("app.core.clients.settings")
    def test_get_notion_client_success(self, mock_settings):
        """Тест успешного создания Notion SDK клиента."""
        mock_settings.notion_token = "test_token"
        
        clear_clients_cache()
        client = get_notion_client()
        
        assert isinstance(client, NotionClient)

    @patch("app.core.clients.settings")
    def test_get_notion_http_client_success(self, mock_settings):
        """Тест успешного создания HTTP клиента."""
        mock_settings.notion_token = "test_token"
        
        clear_clients_cache()
        client = get_notion_http_client()
        
        assert hasattr(client, "headers")
        assert "Authorization" in client.headers


class TestOpenAIClients:
    """Тесты OpenAI клиентов."""

    @patch("app.core.clients.settings")
    def test_get_openai_client_success(self, mock_settings):
        """Тест успешного создания OpenAI клиента."""
        mock_settings.openai_api_key = "test_key"
        
        clear_clients_cache()
        client = get_openai_client()
        
        assert isinstance(client, OpenAI)

    @patch("app.core.clients.settings")
    def test_get_openai_parse_client(self, mock_settings):
        """Тест специализированного клиента для парсинга."""
        mock_settings.openai_api_key = "test_key"
        
        clear_clients_cache()
        client = get_openai_parse_client()
        
        assert isinstance(client, OpenAI)

    @pytest.mark.asyncio
    @patch("app.core.clients.settings")
    async def test_get_async_openai_client(self, mock_settings):
        """Тест асинхронного OpenAI клиента."""
        mock_settings.openai_api_key = "test_key"
        
        from app.core.clients import get_async_openai_client
        client = await get_async_openai_client()
        
        assert isinstance(client, AsyncOpenAI)


class TestUtilities:
    """Тесты утилитарных функций."""

    def test_clear_clients_cache(self):
        """Тест очистки кэша клиентов."""
        clear_clients_cache()
        assert get_notion_client.cache_info().currsize == 0

    @patch("app.core.clients.settings")
    def test_get_clients_info(self, mock_settings):
        """Тест получения информации о клиентах."""
        mock_settings.notion_token = "token"
        mock_settings.openai_api_key = "key"
        
        info = get_clients_info()
        
        assert "notion" in info
        assert "openai" in info


class TestExceptions:
    """Тесты исключений."""

    def test_client_error_hierarchy(self):
        """Тест иерархии исключений."""
        assert issubclass(NotionClientError, ClientError)
        assert issubclass(OpenAIClientError, ClientError)
