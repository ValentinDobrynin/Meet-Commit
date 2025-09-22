"""Тесты для Notion meetings helper функций."""

from unittest.mock import Mock, patch

import pytest

from app.gateways.notion_meetings import (
    fetch_meeting_page,
    update_meeting_tags,
    validate_meeting_access,
)


class TestNotionMeetingsHelpers:
    """Тесты helper функций для Notion meetings."""

    def test_fetch_meeting_page_success(self):
        """Тест успешного получения данных страницы."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Test Meeting"}]},
                "Summary MD": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "Test summary content"}],
                },
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "Finance/IFRS"}, {"name": "Finance/Audit"}],
                },
            },
            "url": "https://notion.so/test-meeting",
        }
        mock_response.raise_for_status = Mock()

        with patch("app.gateways.notion_meetings._create_client") as mock_client_factory:
            mock_client = Mock()
            mock_client.get.return_value = mock_response
            mock_client_factory.return_value = mock_client

            result = fetch_meeting_page("12345678901234567890123456789012")

            assert result["title"] == "Test Meeting"
            assert result["summary_md"] == "Test summary content"
            assert result["current_tags"] == ["Finance/IFRS", "Finance/Audit"]
            assert result["url"] == "https://notion.so/test-meeting"
            mock_client.close.assert_called_once()

    def test_fetch_meeting_page_not_found(self):
        """Тест обработки отсутствующей страницы."""
        mock_response = Mock()
        mock_response.status_code = 404

        with patch("app.gateways.notion_meetings._create_client") as mock_client_factory:
            mock_client = Mock()
            mock_client.get.return_value = mock_response
            mock_client_factory.return_value = mock_client

            with pytest.raises(RuntimeError, match="Meeting page not found"):
                fetch_meeting_page("12345678901234567890123456789012")

    def test_fetch_meeting_page_invalid_id(self):
        """Тест обработки невалидного ID."""
        with pytest.raises(ValueError, match="Invalid page ID format"):
            fetch_meeting_page("invalid-id")

    def test_update_meeting_tags_success(self):
        """Тест успешного обновления тегов."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        with patch("app.gateways.notion_meetings._create_client") as mock_client_factory:
            mock_client = Mock()
            mock_client.patch.return_value = mock_response
            mock_client_factory.return_value = mock_client

            result = update_meeting_tags(
                "12345678901234567890123456789012", ["Finance/IFRS", "Finance/Audit"]
            )

            assert result is True
            mock_client.patch.assert_called_once()
            mock_client.close.assert_called_once()

    def test_update_meeting_tags_not_found(self):
        """Тест обработки отсутствующей страницы при обновлении."""
        mock_response = Mock()
        mock_response.status_code = 404

        with patch("app.gateways.notion_meetings._create_client") as mock_client_factory:
            mock_client = Mock()
            mock_client.patch.return_value = mock_response
            mock_client_factory.return_value = mock_client

            with pytest.raises(RuntimeError, match="Meeting page not found"):
                update_meeting_tags("12345678901234567890123456789012", ["Finance/IFRS"])

    def test_update_meeting_tags_invalid_id(self):
        """Тест обработки невалидного ID при обновлении."""
        with pytest.raises(ValueError, match="Invalid page ID format"):
            update_meeting_tags("invalid-id", ["Finance/IFRS"])

    def test_validate_meeting_access_success(self):
        """Тест успешной проверки доступа к странице."""
        with patch("app.gateways.notion_meetings.fetch_meeting_page") as mock_fetch:
            mock_fetch.return_value = {"title": "Test Meeting"}

            result = validate_meeting_access("12345678901234567890123456789012")
            assert result is True

    def test_validate_meeting_access_failure(self):
        """Тест неуспешной проверки доступа к странице."""
        with patch("app.gateways.notion_meetings.fetch_meeting_page") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("Access denied")

            result = validate_meeting_access("12345678901234567890123456789012")
            assert result is False


class TestPageIdFormatting:
    """Тесты форматирования page ID."""

    def test_page_id_formatting_with_dashes(self):
        """Тест форматирования ID с дефисами."""
        with patch("app.gateways.notion_meetings._create_client") as mock_client_factory:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "properties": {"Name": {"type": "title", "title": []}},
                "url": "test",
            }
            mock_client.get.return_value = mock_response
            mock_client_factory.return_value = mock_client

            # ID с дефисами должен обрабатываться корректно
            page_id = "12345678-9012-3456-7890-123456789012"
            result = fetch_meeting_page(page_id)

            # Проверяем, что ID был отформатирован правильно
            expected_formatted_id = "12345678-9012-3456-7890-123456789012"
            assert result["page_id"] == expected_formatted_id

    def test_page_id_formatting_without_dashes(self):
        """Тест форматирования ID без дефисов."""
        with patch("app.gateways.notion_meetings._create_client") as mock_client_factory:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "properties": {"Name": {"type": "title", "title": []}},
                "url": "test",
            }
            mock_client.get.return_value = mock_response
            mock_client_factory.return_value = mock_client

            # ID без дефисов должен форматироваться
            page_id = "12345678901234567890123456789012"
            result = fetch_meeting_page(page_id)

            # Проверяем правильное форматирование
            expected_formatted_id = "12345678-9012-3456-7890-123456789012"
            assert result["page_id"] == expected_formatted_id


class TestErrorHandling:
    """Тесты обработки ошибок."""

    def test_fetch_meeting_api_error(self):
        """Тест обработки ошибок API при получении страницы."""
        with patch("app.gateways.notion_meetings._create_client") as mock_client_factory:
            mock_client = Mock()
            mock_client.get.side_effect = Exception("API Error")
            mock_client_factory.return_value = mock_client

            with pytest.raises(RuntimeError, match="Failed to fetch meeting page"):
                fetch_meeting_page("12345678901234567890123456789012")

    def test_update_meeting_api_error(self):
        """Тест обработки ошибок API при обновлении."""
        with patch("app.gateways.notion_meetings._create_client") as mock_client_factory:
            mock_client = Mock()
            mock_client.patch.side_effect = Exception("API Error")
            mock_client_factory.return_value = mock_client

            with pytest.raises(RuntimeError, match="Failed to update meeting tags"):
                update_meeting_tags("12345678901234567890123456789012", ["Finance/IFRS"])
