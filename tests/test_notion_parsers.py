"""
Тесты для общих парсеров Notion properties.
Проверяют корректность парсинга всех типов Notion полей.
"""

from app.gateways.notion_parsers import (
    COMMIT_FIELD_MAPPING,
    MEETING_FIELD_MAPPING,
    REVIEW_FIELD_MAPPING,
    build_properties,
    extract_page_fields,
    parse_checkbox,
    parse_date,
    parse_multi_select,
    parse_number,
    parse_relation,
    parse_relation_single,
    parse_rich_text,
    parse_select,
    parse_title,
)


class TestBasicParsers:
    """Тесты базовых парсеров для отдельных типов полей."""

    def test_parse_rich_text_success(self):
        """Тест успешного парсинга rich_text."""
        prop = {
            "type": "rich_text",
            "rich_text": [{"plain_text": "Hello "}, {"plain_text": "World!"}],
        }
        result = parse_rich_text(prop)
        assert result == "Hello World!"

    def test_parse_rich_text_empty(self):
        """Тест парсинга пустого rich_text."""
        assert parse_rich_text(None) == ""
        assert parse_rich_text({}) == ""
        assert parse_rich_text({"type": "rich_text", "rich_text": []}) == ""

    def test_parse_title_success(self):
        """Тест успешного парсинга title."""
        prop = {"type": "title", "title": [{"plain_text": "Test "}, {"plain_text": "Meeting"}]}
        result = parse_title(prop)
        assert result == "Test Meeting"

    def test_parse_select_success(self):
        """Тест успешного парсинга select."""
        prop = {"type": "select", "select": {"name": "open"}}
        result = parse_select(prop)
        assert result == "open"

    def test_parse_select_empty(self):
        """Тест парсинга пустого select."""
        assert parse_select(None) is None
        assert parse_select({"type": "select", "select": None}) is None

    def test_parse_multi_select_success(self):
        """Тест успешного парсинга multi_select."""
        prop = {
            "type": "multi_select",
            "multi_select": [{"name": "Finance/IFRS"}, {"name": "Business/Lavka"}],
        }
        result = parse_multi_select(prop)
        assert result == ["Finance/IFRS", "Business/Lavka"]

    def test_parse_multi_select_empty(self):
        """Тест парсинга пустого multi_select."""
        assert parse_multi_select(None) == []
        assert parse_multi_select({"type": "multi_select", "multi_select": []}) == []

    def test_parse_date_success(self):
        """Тест успешного парсинга date."""
        prop = {"type": "date", "date": {"start": "2025-09-27"}}
        result = parse_date(prop)
        assert result == "2025-09-27"

    def test_parse_number_success(self):
        """Тест успешного парсинга number."""
        prop = {"type": "number", "number": 0.85}
        result = parse_number(prop)
        assert result == 0.85

    def test_parse_number_default(self):
        """Тест парсинга number с fallback на 1.0."""
        assert parse_number(None) == 1.0
        assert parse_number({"type": "number", "number": None}) == 1.0

    def test_parse_checkbox_success(self):
        """Тест успешного парсинга checkbox."""
        prop = {"type": "checkbox", "checkbox": True}
        result = parse_checkbox(prop)
        assert result is True

    def test_parse_relation_success(self):
        """Тест успешного парсинга relation."""
        prop = {"type": "relation", "relation": [{"id": "page-1"}, {"id": "page-2"}]}
        result = parse_relation(prop)
        assert result == ["page-1", "page-2"]

    def test_parse_relation_single_success(self):
        """Тест парсинга relation для одного элемента."""
        prop = {"type": "relation", "relation": [{"id": "page-1"}]}
        result = parse_relation_single(prop)
        assert result == "page-1"


class TestExtractPageFields:
    """Тесты автоматического извлечения полей из страниц."""

    def test_extract_meeting_fields(self):
        """Тест извлечения полей встречи."""
        page_data = {
            "id": "meeting-123",
            "url": "https://notion.so/meeting-123",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Weekly Sync"}]},
                "Summary MD": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "Meeting summary"}],
                },
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "Finance/IFRS"}, {"name": "Topic/Planning"}],
                },
            },
        }

        field_mapping = {
            "title": ("Name", "title"),
            "summary_md": ("Summary MD", "rich_text"),
            "tags": ("Tags", "multi_select"),
        }

        result = extract_page_fields(page_data, field_mapping)

        assert result["id"] == "meeting-123"
        assert result["url"] == "https://notion.so/meeting-123"
        assert result["title"] == "Weekly Sync"
        assert result["summary_md"] == "Meeting summary"
        assert result["tags"] == ["Finance/IFRS", "Topic/Planning"]

    def test_extract_with_missing_fields(self):
        """Тест извлечения когда некоторые поля отсутствуют."""
        page_data = {
            "id": "page-123",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Test"}]}
                # Tags отсутствует
            },
        }

        field_mapping = {
            "title": ("Name", "title"),
            "tags": ("Tags", "multi_select"),
            "active": ("Active", "checkbox"),
        }

        result = extract_page_fields(page_data, field_mapping)

        assert result["title"] == "Test"
        assert result["tags"] == []  # Default для multi_select
        assert result["active"] is False  # Default для checkbox


class TestBuildProperties:
    """Тесты автоматического построения properties."""

    def test_build_meeting_properties(self):
        """Тест построения properties для встречи."""
        data = {
            "title": "Test Meeting",
            "tags": ["Finance/IFRS", "Business/Lavka"],
            "date": "2025-09-27",
            "active": True,
        }

        field_mapping = {
            "title": ("Name", "title"),
            "tags": ("Tags", "multi_select"),
            "date": ("Date", "date"),
            "active": ("Active", "checkbox"),
        }

        result = build_properties(data, field_mapping)

        expected = {
            "Name": {"title": [{"text": {"content": "Test Meeting"}}]},
            "Tags": {"multi_select": [{"name": "Finance/IFRS"}, {"name": "Business/Lavka"}]},
            "Date": {"date": {"start": "2025-09-27"}},
            "Active": {"checkbox": True},
        }

        assert result == expected

    def test_build_properties_with_none_values(self):
        """Тест построения properties с None значениями."""
        data = {
            "title": "Test",
            "tags": None,  # Должно быть пропущено
            "date": "",  # Пустая дата
        }

        field_mapping = {
            "title": ("Name", "title"),
            "tags": ("Tags", "multi_select"),
            "date": ("Date", "date"),
        }

        result = build_properties(data, field_mapping)

        expected = {
            "Name": {"title": [{"text": {"content": "Test"}}]},
            "Date": {"date": None},  # Пустая дата
        }

        assert result == expected


class TestFieldMappings:
    """Тесты готовых маппингов полей."""

    def test_meeting_field_mapping_complete(self):
        """Тест что маппинг встреч содержит все необходимые поля."""
        required_fields = ["title", "summary_md", "tags", "attendees", "date", "source", "raw_hash"]

        for field in required_fields:
            assert field in MEETING_FIELD_MAPPING, f"Missing field: {field}"

        # Проверяем что все маппинги имеют правильную структуру
        for field, (notion_field, property_type) in MEETING_FIELD_MAPPING.items():
            assert isinstance(notion_field, str), f"Invalid notion_field for {field}"
            assert isinstance(property_type, str), f"Invalid property_type for {field}"

    def test_commit_field_mapping_complete(self):
        """Тест что маппинг коммитов содержит все необходимые поля."""
        required_fields = ["title", "text", "direction", "assignees", "due_iso", "status", "tags"]

        for field in required_fields:
            assert field in COMMIT_FIELD_MAPPING, f"Missing field: {field}"

    def test_review_field_mapping_complete(self):
        """Тест что маппинг ревью содержит все необходимые поля."""
        required_fields = ["text", "direction", "assignees", "status", "context"]

        for field in required_fields:
            assert field in REVIEW_FIELD_MAPPING, f"Missing field: {field}"


class TestParserRobustness:
    """Тесты устойчивости парсеров к некорректным данным."""

    def test_parsers_handle_malformed_data(self):
        """Тест что парсеры устойчивы к некорректным данным."""
        malformed_props = [
            None,
            {},
            {"type": "wrong_type"},
            {"type": "rich_text"},  # Без данных
            {"type": "rich_text", "rich_text": None},
        ]

        for prop in malformed_props:
            # Все парсеры должны возвращать разумные значения по умолчанию
            assert parse_rich_text(prop) == ""
            assert parse_title(prop) == ""
            assert parse_multi_select(prop) == []
            assert parse_relation(prop) == []
            assert parse_select(prop) is None
            assert parse_date(prop) is None
            assert parse_number(prop) == 1.0
            assert parse_checkbox(prop) is False
            assert parse_relation_single(prop) is None

    def test_extract_page_fields_with_parser_errors(self):
        """Тест что extract_page_fields устойчива к ошибкам парсинга."""
        page_data = {
            "id": "page-123",
            "properties": {
                "Name": {"type": "title", "title": "malformed"},  # Некорректные данные
                "Tags": {"type": "multi_select", "multi_select": None},
            },
        }

        field_mapping = {
            "title": ("Name", "title"),
            "tags": ("Tags", "multi_select"),
        }

        # Не должно поднимать исключение
        result = extract_page_fields(page_data, field_mapping)

        assert "id" in result
        assert "title" in result
        assert "tags" in result
        # Значения могут быть None или defaults - главное что нет исключений


class TestBackwardCompatibility:
    """Тесты обратной совместимости после рефакторинга."""

    def test_meeting_parsing_still_works(self):
        """Тест что парсинг встреч работает как раньше."""
        # Имитируем реальные данные из Notion
        page_data = {
            "id": "meeting-id",
            "url": "https://notion.so/meeting",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Planning Meeting"}]},
                "Summary MD": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "Discussed quarterly planning"}],
                },
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "Finance/Budget"}, {"name": "Topic/Planning"}],
                },
            },
        }

        # Используем extract_page_fields как в новом коде
        field_mapping = {
            "title": ("Name", "title"),
            "summary_md": ("Summary MD", "rich_text"),
            "current_tags": ("Tags", "multi_select"),
        }

        result = extract_page_fields(page_data, field_mapping)

        # Проверяем что результат соответствует ожиданиям
        assert result["title"] == "Planning Meeting"
        assert result["summary_md"] == "Discussed quarterly planning"
        assert result["current_tags"] == ["Finance/Budget", "Topic/Planning"]
        assert result["id"] == "meeting-id"
        assert result["url"] == "https://notion.so/meeting"
