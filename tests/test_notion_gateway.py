"""Тесты для app.gateways.notion_gateway"""

from unittest.mock import Mock, patch

import pytest

from app.gateways.notion_gateway import _client, _settings, upsert_meeting


def test_notion_settings():
    """Тест получения настроек Notion."""
    with patch.dict(
        "os.environ", {"NOTION_TOKEN": "test_token", "NOTION_DB_MEETINGS_ID": "test_db_id"}
    ):
        settings = _settings()
        assert settings.notion_token == "test_token"
        assert settings.notion_db_meetings_id == "test_db_id"


def test_notion_client_creation():
    """Тест создания Notion клиента."""
    with patch.dict(
        "os.environ", {"NOTION_TOKEN": "test_token", "NOTION_DB_MEETINGS_ID": "test_db_id"}
    ):
        client = _client()
        assert client is not None


def test_upsert_meeting_success():
    """Тест успешного создания записи в Notion."""
    mock_page = {"id": "page_123", "url": "https://notion.so/page_123"}

    mock_client = Mock()
    mock_client.pages.create.return_value = mock_page
    mock_client.pages.retrieve.return_value = mock_page

    with patch("app.gateways.notion_gateway._client", return_value=mock_client):
        with patch("app.gateways.notion_gateway._settings") as mock_settings:
            mock_settings.return_value.notion_db_meetings_id = "test_db_id"

            payload = {
                "title": "Test Meeting",
                "date": "2024-03-25",
                "attendees": ["Valentin", "Daniil"],
                "source": "telegram",
                "raw_hash": "abc123",
                "summary_md": "Meeting summary",
                "tags": ["area/ifrs", "person/valentin"],
            }

            result = upsert_meeting(payload)

            assert result == "https://notion.so/page_123"
            mock_client.pages.create.assert_called_once()
            mock_client.pages.retrieve.assert_called_once_with("page_123")


def test_upsert_meeting_with_minimal_data():
    """Тест создания записи с минимальными данными."""
    mock_page = {"id": "page_456", "url": "https://notion.so/page_456"}

    mock_client = Mock()
    mock_client.pages.create.return_value = mock_page
    mock_client.pages.retrieve.return_value = mock_page

    with patch("app.gateways.notion_gateway._client", return_value=mock_client):
        with patch("app.gateways.notion_gateway._settings") as mock_settings:
            mock_settings.return_value.notion_db_meetings_id = "test_db_id"

            payload = {"title": "Minimal Meeting", "raw_hash": "def456"}

            result = upsert_meeting(payload)

            assert result == "https://notion.so/page_456"

            # Проверяем, что вызов был с правильными параметрами
            create_call = mock_client.pages.create.call_args
            assert create_call[1]["parent"]["database_id"] == "test_db_id"

            properties = create_call[1]["properties"]
            assert properties["Name"]["title"][0]["text"]["content"] == "Minimal Meeting"
            assert properties["Raw hash"]["rich_text"][0]["text"]["content"] == "def456"


def test_upsert_meeting_with_long_title():
    """Тест обрезания длинного заголовка."""
    mock_page = {"id": "page_789", "url": "https://notion.so/page_789"}

    mock_client = Mock()
    mock_client.pages.create.return_value = mock_page
    mock_client.pages.retrieve.return_value = mock_page

    with patch("app.gateways.notion_gateway._client", return_value=mock_client):
        with patch("app.gateways.notion_gateway._settings") as mock_settings:
            mock_settings.return_value.notion_db_meetings_id = "test_db_id"

            long_title = "A" * 250  # Длиннее лимита в 200 символов
            payload = {"title": long_title, "raw_hash": "ghi789"}

            result = upsert_meeting(payload)

            assert result == "https://notion.so/page_789"

            create_call = mock_client.pages.create.call_args
            properties = create_call[1]["properties"]
            title_content = properties["Name"]["title"][0]["text"]["content"]
            assert len(title_content) == 200  # Обрезано до 200 символов


def test_upsert_meeting_with_long_summary():
    """Тест обрезания длинного саммари."""
    mock_page = {"id": "page_999", "url": "https://notion.so/page_999"}

    mock_client = Mock()
    mock_client.pages.create.return_value = mock_page
    mock_client.pages.retrieve.return_value = mock_page

    with patch("app.gateways.notion_gateway._client", return_value=mock_client):
        with patch("app.gateways.notion_gateway._settings") as mock_settings:
            mock_settings.return_value.notion_db_meetings_id = "test_db_id"

            long_summary = "B" * 2000  # Длиннее лимита в 1900 символов
            payload = {"title": "Test", "raw_hash": "jkl000", "summary_md": long_summary}

            result = upsert_meeting(payload)

            assert result == "https://notion.so/page_999"

            create_call = mock_client.pages.create.call_args
            properties = create_call[1]["properties"]
            summary_content = properties["Summary MD"]["rich_text"][0]["text"]["content"]
            assert len(summary_content) == 1900  # Обрезано до 1900 символов


def test_upsert_meeting_api_error():
    """Тест обработки ошибки API Notion."""
    mock_client = Mock()
    mock_client.pages.create.side_effect = Exception("Notion API Error")

    with patch("app.gateways.notion_gateway._client", return_value=mock_client):
        with patch("app.gateways.notion_gateway._settings") as mock_settings:
            mock_settings.return_value.notion_db_meetings_id = "test_db_id"

            payload = {"title": "Test", "raw_hash": "error123"}

            with pytest.raises(Exception, match="Notion API Error"):
                upsert_meeting(payload)
