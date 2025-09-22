"""Тесты для новых методов в notion_review.py."""

from unittest.mock import MagicMock, patch

import pytest

from app.gateways.notion_review import (
    _parse_date,
    _parse_multi_select,
    _parse_number,
    _parse_relation_id,
    _parse_rich_text,
    _parse_select,
    _short_id,
    enqueue_with_upsert,
    find_pending_by_key,
    get_by_short_id,
    list_pending,
    update_fields,
    upsert_review,
)


class TestNotionReviewHelpers:
    """Тесты для helper функций парсинга Notion properties."""

    def test_short_id(self):
        """Тест генерации короткого ID."""
        page_id = "12345678-1234-1234-1234-123456789012"
        result = _short_id(page_id)
        assert result == "789012"

    def test_short_id_with_no_dashes(self):
        """Тест генерации короткого ID без дефисов."""
        page_id = "123456789012345678901234567890ab"
        result = _short_id(page_id)
        assert result == "7890ab"

    def test_parse_rich_text_success(self):
        """Тест парсинга rich_text property."""
        prop = {
            "type": "rich_text",
            "rich_text": [{"plain_text": "Часть 1 "}, {"plain_text": "Часть 2"}],
        }
        result = _parse_rich_text(prop)
        assert result == "Часть 1 Часть 2"

    def test_parse_rich_text_empty(self):
        """Тест парсинга пустого rich_text property."""
        assert _parse_rich_text(None) == ""
        assert _parse_rich_text({"type": "title"}) == ""
        assert _parse_rich_text({"type": "rich_text", "rich_text": []}) == ""

    def test_parse_select_success(self):
        """Тест парсинга select property."""
        prop = {"type": "select", "select": {"name": "pending"}}
        result = _parse_select(prop)
        assert result == "pending"

    def test_parse_select_empty(self):
        """Тест парсинга пустого select property."""
        assert _parse_select(None) is None
        assert _parse_select({"type": "rich_text"}) is None
        assert _parse_select({"type": "select", "select": None}) is None

    def test_parse_multi_select_success(self):
        """Тест парсинга multi_select property."""
        prop = {
            "type": "multi_select",
            "multi_select": [
                {"name": "tag1"},
                {"name": "tag2"},
                {"name": ""},  # Пустое имя должно игнорироваться
            ],
        }
        result = _parse_multi_select(prop)
        assert result == ["tag1", "tag2"]

    def test_parse_multi_select_empty(self):
        """Тест парсинга пустого multi_select property."""
        assert _parse_multi_select(None) == []
        assert _parse_multi_select({"type": "select"}) == []
        assert _parse_multi_select({"type": "multi_select", "multi_select": []}) == []

    def test_parse_date_success(self):
        """Тест парсинга date property."""
        prop = {"type": "date", "date": {"start": "2025-10-15"}}
        result = _parse_date(prop)
        assert result == "2025-10-15"

    def test_parse_date_empty(self):
        """Тест парсинга пустого date property."""
        assert _parse_date(None) is None
        assert _parse_date({"type": "rich_text"}) is None
        assert _parse_date({"type": "date", "date": None}) is None

    def test_parse_number_success(self):
        """Тест парсинга number property."""
        prop = {"type": "number", "number": 0.85}
        result = _parse_number(prop)
        assert result == 0.85

    def test_parse_number_empty(self):
        """Тест парсинга пустого number property."""
        assert _parse_number(None) is None
        assert _parse_number({"type": "select"}) is None

    def test_parse_relation_id_success(self):
        """Тест парсинга relation property."""
        prop = {"type": "relation", "relation": [{"id": "meeting-page-id"}]}
        result = _parse_relation_id(prop)
        assert result == "meeting-page-id"

    def test_parse_relation_id_empty(self):
        """Тест парсинга пустого relation property."""
        assert _parse_relation_id(None) is None
        assert _parse_relation_id({"type": "select"}) is None
        assert _parse_relation_id({"type": "relation", "relation": []}) is None


class TestNotionReviewMethods:
    """Тесты для основных методов работы с Review queue."""

    @pytest.fixture
    def mock_notion_response(self):
        """Mock ответ от Notion API."""
        return {
            "results": [
                {
                    "id": "12345678-1234-1234-1234-123456789012",
                    "properties": {
                        "Commit text": {
                            "type": "rich_text",
                            "rich_text": [{"plain_text": "Подготовить отчет"}],
                        },
                        "Direction": {"type": "select", "select": {"name": "theirs"}},
                        "Assignee": {"type": "multi_select", "multi_select": [{"name": "Daniil"}]},
                        "Due": {"type": "date", "date": {"start": "2025-10-15"}},
                        "Confidence": {"type": "number", "number": 0.8},
                        "Reason": {
                            "type": "multi_select",
                            "multi_select": [{"name": "unclear_assignee"}],
                        },
                        "Context": {"type": "rich_text", "rich_text": [{"plain_text": "Контекст"}]},
                        "Meeting": {"type": "relation", "relation": [{"id": "meeting-id"}]},
                    },
                }
            ]
        }

    @patch("app.gateways.notion_review._create_client")
    def test_list_pending_success(self, mock_create_client, mock_notion_response):
        """Тест успешного получения списка pending элементов."""
        # Настройка mock
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = mock_notion_response
        mock_client.post.return_value = mock_response

        # Выполнение
        result = list_pending(limit=5)

        # Проверки
        assert len(result) == 1
        item = result[0]
        assert item["page_id"] == "12345678-1234-1234-1234-123456789012"
        assert item["short_id"] == "789012"
        assert item["text"] == "Подготовить отчет"
        assert item["direction"] == "theirs"
        assert item["assignees"] == ["Daniil"]
        assert item["due_iso"] == "2025-10-15"
        assert item["confidence"] == 0.8
        assert item["reasons"] == ["unclear_assignee"]
        assert item["context"] == "Контекст"
        assert item["meeting_page_id"] == "meeting-id"

        # Проверяем вызов API
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "databases" in call_args[0][0]
        # Новый формат фильтра использует "or" для нескольких статусов
        filter_data = call_args[1]["json"]["filter"]
        assert "or" in filter_data
        assert call_args[1]["json"]["page_size"] == 5

    @patch("app.gateways.notion_review._create_client")
    def test_get_by_short_id_found(self, mock_create_client):
        """Тест поиска элемента по короткому ID (найден)."""
        # Настройка mock
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "12345678-1234-1234-1234-123456789012",
                    "properties": {
                        "Commit text": {
                            "type": "rich_text",
                            "rich_text": [{"plain_text": "Тестовый элемент"}],
                        },
                        "Direction": {"type": "select", "select": {"name": "theirs"}},
                        "Assignee": {"type": "multi_select", "multi_select": []},
                        "Due": {"type": "date", "date": None},
                        "Confidence": {"type": "number", "number": 0.8},
                        "Reason": {"type": "multi_select", "multi_select": []},
                        "Context": {"type": "rich_text", "rich_text": []},
                        "Meeting": {"type": "relation", "relation": [{"id": "meeting-id"}]},
                    },
                }
            ],
            "has_more": False,
        }
        mock_client.post.return_value = mock_response

        result = get_by_short_id("789012")

        assert result is not None
        assert result["short_id"] == "789012"
        assert result["text"] == "Тестовый элемент"

    @patch("app.gateways.notion_review.list_pending")
    def test_get_by_short_id_not_found(self, mock_list_pending):
        """Тест поиска элемента по короткому ID (не найден)."""
        mock_list_pending.return_value = []

        result = get_by_short_id("abc123")

        assert result is None

    @patch("app.gateways.notion_review._create_client")
    def test_get_by_short_id_case_insensitive(self, mock_create_client):
        """Тест поиска элемента по короткому ID (регистронезависимый)."""
        # Настройка mock
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "12345678-1234-1234-1234-123456ABC123",
                    "properties": {
                        "Commit text": {
                            "type": "rich_text",
                            "rich_text": [{"plain_text": "Тестовый элемент"}],
                        },
                        "Direction": {"type": "select", "select": {"name": "theirs"}},
                        "Assignee": {"type": "multi_select", "multi_select": []},
                        "Due": {"type": "date", "date": None},
                        "Confidence": {"type": "number", "number": 0.8},
                        "Reason": {"type": "multi_select", "multi_select": []},
                        "Context": {"type": "rich_text", "rich_text": []},
                        "Meeting": {"type": "relation", "relation": [{"id": "meeting-id"}]},
                    },
                }
            ],
            "has_more": False,
        }
        mock_client.post.return_value = mock_response

        result = get_by_short_id("abc123")

        assert result is not None
        assert result["short_id"] == "ABC123"

    @patch("app.gateways.notion_review._create_client")
    def test_update_fields_success(self, mock_create_client):
        """Тест успешного обновления полей."""
        # Настройка mock
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_client.patch.return_value = mock_response

        # Выполнение
        result = update_fields(
            "test-page-id", direction="mine", assignees=["Valentin", "Daniil"], due_iso="2025-12-31"
        )

        # Проверки
        assert result is True
        mock_client.patch.assert_called_once()

        call_args = mock_client.patch.call_args
        assert "pages/test-page-id" in call_args[0][0]

        props = call_args[1]["json"]["properties"]
        assert props["Direction"]["select"]["name"] == "mine"
        assert len(props["Assignee"]["multi_select"]) == 2
        assert props["Assignee"]["multi_select"][0]["name"] == "Valentin"
        assert props["Due"]["date"]["start"] == "2025-12-31"

    @patch("app.gateways.notion_review._create_client")
    def test_update_fields_clear_due(self, mock_create_client):
        """Тест очистки поля due_iso."""
        # Настройка mock
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_client.patch.return_value = mock_response

        # Выполнение
        result = update_fields("test-page-id", due_iso="")

        # Проверки
        assert result is True
        call_args = mock_client.patch.call_args
        props = call_args[1]["json"]["properties"]
        assert props["Due"]["date"] is None

    @patch("app.gateways.notion_review._create_client")
    def test_update_fields_no_changes(self, mock_create_client):
        """Тест обновления без изменений."""
        result = update_fields("test-page-id")
        assert result is True
        # Клиент не должен быть создан, если нет изменений
        mock_create_client.assert_not_called()

    @patch("app.gateways.notion_review._create_client")
    def test_update_fields_error(self, mock_create_client):
        """Тест обработки ошибки при обновлении полей."""
        # Настройка mock для ошибки
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None

        mock_client.patch.side_effect = Exception("API Error")

        # Выполнение
        result = update_fields("test-page-id", direction="mine")

        # Проверки
        assert result is False


class TestUpsertReviewFunctions:
    """Тесты для новых функций upsert в Review Queue."""

    @patch("app.gateways.notion_review._create_client")
    def test_find_pending_by_key_found(self, mock_create_client):
        """Тест поиска pending элемента по ключу - элемент найден."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "test-page-id-123",
                    "properties": {
                        "Name": {"title": [{"text": {"content": "Test item"}}]},
                        "Key": {"rich_text": [{"text": {"content": "test-key-123"}}]},
                    },
                }
            ]
        }
        mock_client.post.return_value = mock_response

        result = find_pending_by_key("test-key-123")

        assert result is not None
        assert result["page_id"] == "test-page-id-123"
        assert "properties" in result
        mock_client.post.assert_called_once()

    @patch("app.gateways.notion_review._create_client")
    def test_find_pending_by_key_not_found(self, mock_create_client):
        """Тест поиска pending элемента по ключу - элемент не найден."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response

        result = find_pending_by_key("non-existent-key")

        assert result is None
        mock_client.post.assert_called_once()

    @patch("app.gateways.notion_review.find_pending_by_key")
    @patch("app.gateways.notion_review._create_client")
    def test_upsert_review_create_new(self, mock_create_client, mock_find_pending):
        """Тест создания нового элемента в Review Queue."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_find_pending.return_value = None  # Элемент не найден

        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "new-page-id-456"}
        mock_client.post.return_value = mock_response

        test_item = {
            "text": "Test commit text",
            "direction": "theirs",
            "assignees": ["John Doe"],
            "due_iso": "2025-01-15",
            "confidence": 0.75,
            "reason": "Test reason",
            "context": "Test context",
            "key": "test-key-456",
            "tags": ["urgent"],
        }

        result = upsert_review(test_item, "meeting-page-id")

        assert result["created"] == 1
        assert result["updated"] == 0
        assert result["page_id"] == "new-page-id-456"
        mock_client.post.assert_called_once()

    @patch("app.gateways.notion_review.find_pending_by_key")
    @patch("app.gateways.notion_review._create_client")
    def test_upsert_review_update_existing(self, mock_create_client, mock_find_pending):
        """Тест обновления существующего элемента в Review Queue."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_find_pending.return_value = {"page_id": "existing-page-id", "properties": {}}

        mock_response = MagicMock()
        mock_client.patch.return_value = mock_response

        test_item = {
            "text": "Updated commit text",
            "direction": "mine",
            "assignees": ["Jane Smith"],
            "due_iso": "2025-02-01",
            "confidence": 0.85,
            "reason": "Updated reason",
            "context": "Updated context",
            "key": "existing-key-789",
            "tags": ["high-priority"],
        }

        result = upsert_review(test_item, "meeting-page-id")

        assert result["created"] == 0
        assert result["updated"] == 1
        assert result["page_id"] == "existing-page-id"
        mock_client.patch.assert_called_once()

    @patch("app.gateways.notion_review.upsert_review")
    def test_enqueue_with_upsert_multiple_items(self, mock_upsert_review):
        """Тест добавления нескольких элементов через enqueue_with_upsert."""
        # Настраиваем mock для возврата разных результатов
        mock_upsert_review.side_effect = [
            {"created": 1, "updated": 0, "page_id": "page-1"},
            {"created": 0, "updated": 1, "page_id": "page-2"},
            {"created": 1, "updated": 0, "page_id": "page-3"},
        ]

        test_items = [
            {"key": "key-1", "text": "Item 1"},
            {"key": "key-2", "text": "Item 2"},
            {"key": "key-3", "text": "Item 3"},
        ]

        result = enqueue_with_upsert(test_items, "meeting-id")

        assert result["created"] == 2
        assert result["updated"] == 1
        assert len(result["page_ids"]) == 3
        assert mock_upsert_review.call_count == 3

    def test_enqueue_with_upsert_empty_list(self):
        """Тест enqueue_with_upsert с пустым списком."""
        result = enqueue_with_upsert([], "meeting-id")

        assert result["created"] == 0
        assert result["updated"] == 0
        assert result["page_ids"] == []
