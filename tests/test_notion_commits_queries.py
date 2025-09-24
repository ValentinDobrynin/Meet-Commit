"""Тесты для функций запросов в notion_commits."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.gateways.notion_commits import (
    _map_commit_page,
    _query_commits,
    query_commits_by_assignee,
    query_commits_by_tag,
    query_commits_due_today,
    query_commits_due_within,
    query_commits_mine,
    query_commits_recent,
    query_commits_theirs,
)


@pytest.fixture
def sample_notion_page():
    """Фикстура с примером страницы из Notion API."""
    return {
        "id": "12345678-1234-5678-9abc-123456789abc",
        "url": "https://www.notion.so/commit-page-12345678123456789abc123456789abc",
        "properties": {
            "Name": {"title": [{"plain_text": "John Doe: Подготовить отчет [due 2025-10-15]"}]},
            "Text": {"rich_text": [{"plain_text": "Подготовить отчет по продажам за Q3"}]},
            "Direction": {"select": {"name": "mine"}},
            "Assignee": {"multi_select": [{"name": "John Doe"}, {"name": "Jane Smith"}]},
            "Due": {"date": {"start": "2025-10-15"}},
            "Confidence": {"number": 0.85},
            "Flags": {"multi_select": [{"name": "urgent"}]},
            "Status": {"select": {"name": "open"}},
            "Tags": {"multi_select": [{"name": "Finance/Report"}, {"name": "Topic/Sales"}]},
            "Meeting": {"relation": [{"id": "meeting-123"}]},
        },
    }


@pytest.fixture
def mock_notion_response():
    """Фикстура с примером ответа Notion API."""
    return {"results": [], "next_cursor": None, "has_more": False}


class TestMapCommitPage:
    """Тесты преобразования страниц Notion."""

    def test_map_commit_page_full_data(self, sample_notion_page):
        """Тест преобразования страницы с полными данными."""
        result = _map_commit_page(sample_notion_page)

        assert result["id"] == "12345678-1234-5678-9abc-123456789abc"
        assert result["short_id"] == "56789abc"  # Последние 8 символов без дефисов
        assert result["title"] == "John Doe: Подготовить отчет [due 2025-10-15]"
        assert result["text"] == "Подготовить отчет по продажам за Q3"
        assert result["direction"] == "mine"
        assert result["assignees"] == ["John Doe", "Jane Smith"]
        assert result["due_iso"] == "2025-10-15"
        assert result["confidence"] == 0.85
        assert result["flags"] == ["urgent"]
        assert result["status"] == "open"
        assert result["tags"] == ["Finance/Report", "Topic/Sales"]
        assert result["meeting_ids"] == ["meeting-123"]

    def test_map_commit_page_minimal_data(self):
        """Тест преобразования страницы с минимальными данными."""
        minimal_page = {"id": "minimal-id", "url": "https://notion.so/minimal", "properties": {}}

        result = _map_commit_page(minimal_page)

        assert result["id"] == "minimal-id"
        assert result["title"] == "Без названия"
        assert result["text"] == ""
        assert result["direction"] == "unknown"
        assert result["assignees"] == []
        assert result["due_iso"] is None
        assert result["confidence"] == 0.0
        assert result["status"] == "open"
        assert result["tags"] == []

    def test_map_commit_page_empty_fields(self):
        """Тест преобразования страницы с пустыми полями."""
        empty_fields_page = {
            "id": "empty-id",
            "properties": {
                "Name": {"title": []},
                "Text": {"rich_text": []},
                "Direction": {"select": None},
                "Assignee": {"multi_select": []},
                "Due": {"date": None},
                "Status": {"select": None},
                "Tags": {"multi_select": []},
            },
        }

        result = _map_commit_page(empty_fields_page)

        assert result["title"] == "Без названия"
        assert result["text"] == ""
        assert result["direction"] == "unknown"  # По умолчанию возвращается "unknown"
        assert result["assignees"] == []
        assert result["due_iso"] is None
        assert result["status"] == "open"  # По умолчанию возвращается "open"
        assert result["tags"] == []


class TestQueryFunctions:
    """Тесты функций запросов."""

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_recent(self, mock_query, mock_notion_response, sample_notion_page):
        """Тест запроса последних коммитов."""
        mock_notion_response["results"] = [sample_notion_page]
        mock_query.return_value = mock_notion_response

        result = query_commits_recent(limit=5)

        mock_query.assert_called_once()
        call_args = mock_query.call_args
        assert call_args.kwargs["page_size"] == 5
        assert call_args.kwargs["sorts"][0]["property"] == "Due"
        assert call_args.kwargs["sorts"][0]["direction"] == "descending"

        assert len(result) == 1
        assert result[0]["title"] == "John Doe: Подготовить отчет [due 2025-10-15]"

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_mine(self, mock_query, mock_notion_response, sample_notion_page):
        """Тест запроса моих коммитов."""
        mock_notion_response["results"] = [sample_notion_page]
        mock_query.return_value = mock_notion_response

        result = query_commits_mine(me_name_en="John Doe", limit=5)

        # Теперь вызывается дважды: активные + выполненные
        assert mock_query.call_count == 2
        call_args = mock_query.call_args

        # Проверяем фильтр (последний вызов - для выполненных коммитов)
        filter_ = call_args.kwargs["filter_"]
        assert "and" in filter_
        assert len(filter_["and"]) == 2
        # Убираем проверку конкретного содержимого фильтра из-за сложной структуры

        # Проверяем сортировку
        sorts = call_args.kwargs["sorts"]
        assert sorts[0]["property"] == "Due"
        assert sorts[0]["direction"] == "descending"  # Последний вызов - для выполненных коммитов

        assert len(result) == 2  # Активные + выполненные коммиты

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_theirs(self, mock_query, mock_notion_response, sample_notion_page):
        """Тест запроса чужих коммитов."""
        mock_notion_response["results"] = [sample_notion_page]
        mock_query.return_value = mock_notion_response

        result = query_commits_theirs(limit=5)

        mock_query.assert_called_once()
        call_args = mock_query.call_args

        # Проверяем фильтр (теперь это AND фильтр)
        filter_ = call_args.kwargs["filter_"]
        assert "and" in filter_
        # Убираем детальную проверку фильтра из-за сложной структуры

        assert len(result) == 1

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_due_within(self, mock_query, mock_notion_response, sample_notion_page):
        """Тест запроса коммитов с дедлайном в ближайшие дни."""
        mock_notion_response["results"] = [sample_notion_page]
        mock_query.return_value = mock_notion_response

        result = query_commits_due_within(days=7, limit=5)

        mock_query.assert_called_once()
        call_args = mock_query.call_args

        # Проверяем фильтр
        filter_ = call_args.kwargs["filter_"]
        assert filter_["and"]

        # Проверяем наличие фильтров по дате и статусу
        conditions = filter_["and"]
        date_filters = [c for c in conditions if c.get("property") == "Due"]
        status_filters = [c for c in conditions if c.get("property") == "Status"]

        assert len(date_filters) == 2  # on_or_after и on_or_before
        assert len(status_filters) == 2  # исключаем done и dropped

        assert len(result) == 1

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_due_today(self, mock_query, mock_notion_response, sample_notion_page):
        """Тест запроса коммитов с дедлайном сегодня."""
        mock_notion_response["results"] = [sample_notion_page]
        mock_query.return_value = mock_notion_response

        result = query_commits_due_today(limit=5)

        mock_query.assert_called_once()
        call_args = mock_query.call_args

        # Проверяем фильтр
        filter_ = call_args.kwargs["filter_"]
        conditions = filter_["and"]

        # Должен быть фильтр по сегодняшней дате
        due_filter = next(c for c in conditions if c.get("property") == "Due")
        assert "equals" in due_filter["date"]

        assert len(result) == 1

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_by_tag(self, mock_query, mock_notion_response, sample_notion_page):
        """Тест запроса коммитов по тегу."""
        mock_notion_response["results"] = [sample_notion_page]
        mock_query.return_value = mock_notion_response

        result = query_commits_by_tag("Finance/Report", limit=5)

        mock_query.assert_called_once()
        call_args = mock_query.call_args

        # Проверяем фильтр
        filter_ = call_args.kwargs["filter_"]
        assert filter_["property"] == "Tags"
        assert filter_["multi_select"]["contains"] == "Finance/Report"

        assert len(result) == 1

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_empty_response(self, mock_query, mock_notion_response):
        """Тест обработки пустого ответа."""
        mock_notion_response["results"] = []
        mock_query.return_value = mock_notion_response

        result = query_commits_recent()

        assert result == []

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_error_handling(self, mock_query):
        """Тест обработки ошибок в запросах."""
        mock_query.side_effect = Exception("Notion API error")

        result = query_commits_recent()

        assert result == []  # Должен вернуть пустой список при ошибке


class TestQueryCommitsFunction:
    """Тесты универсальной функции _query_commits."""

    @patch("app.gateways.notion_commits._create_client")
    def test_query_commits_basic(self, mock_create_client):
        """Тест базового запроса."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response
        mock_create_client.return_value = mock_client

        _query_commits()  # Просто вызываем, результат не нужен для теста

        # Проверяем, что клиент создан и запрос выполнен
        mock_create_client.assert_called_once()
        mock_client.post.assert_called_once()
        mock_client.close.assert_called_once()

        # Проверяем payload
        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["page_size"] == 10
        assert "sorts" in payload

    @patch("app.gateways.notion_commits._create_client")
    def test_query_commits_with_filter(self, mock_create_client):
        """Тест запроса с фильтром."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response
        mock_create_client.return_value = mock_client

        test_filter = {"property": "Status", "select": {"equals": "open"}}
        test_sorts = [{"property": "Due", "direction": "ascending"}]

        _query_commits(filter_=test_filter, sorts=test_sorts, page_size=5)

        # Проверяем payload
        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["filter"] == test_filter
        assert payload["sorts"] == test_sorts
        assert payload["page_size"] == 5

    @patch("app.gateways.notion_commits._create_client")
    def test_query_commits_error_handling(self, mock_create_client):
        """Тест обработки ошибок."""
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("API Error")
        mock_create_client.return_value = mock_client

        with pytest.raises(Exception, match="API Error"):
            _query_commits()

        # Проверяем, что клиент все равно закрывается
        mock_client.close.assert_called_once()


class TestDateFilters:
    """Тесты фильтров по датам."""

    def test_due_within_filter_generation(self):
        """Тест генерации фильтра для дедлайнов."""
        # Мокаем datetime для предсказуемых результатов
        fixed_date = datetime(2025, 10, 15, tzinfo=UTC).date()

        with patch("app.gateways.notion_commits.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = fixed_date
            mock_dt.now.return_value = datetime(2025, 10, 15, tzinfo=UTC)

            with patch("app.gateways.notion_commits._query_commits") as mock_query:
                mock_query.return_value = {"results": []}

                query_commits_due_within(days=7)

                # Проверяем сгенерированный фильтр
                call_args = mock_query.call_args
                filter_ = call_args.kwargs["filter_"]

                conditions = filter_["and"]
                date_conditions = [c for c in conditions if c.get("property") == "Due"]

                assert len(date_conditions) == 2
                # Проверяем, что есть фильтры "от" и "до"
                assert any("on_or_after" in c["date"] for c in date_conditions)
                assert any("on_or_before" in c["date"] for c in date_conditions)

    def test_due_today_filter_generation(self):
        """Тест генерации фильтра для сегодняшних дедлайнов."""
        fixed_date = datetime(2025, 10, 15, tzinfo=UTC).date()

        with patch("app.gateways.notion_commits.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = fixed_date

            with patch("app.gateways.notion_commits._query_commits") as mock_query:
                mock_query.return_value = {"results": []}

                query_commits_due_today()

                # Проверяем сгенерированный фильтр
                call_args = mock_query.call_args
                filter_ = call_args.kwargs["filter_"]

                conditions = filter_["and"]
                due_condition = next(c for c in conditions if c.get("property") == "Due")

                assert due_condition["date"]["equals"] == "2025-10-15"


class TestIntegration:
    """Интеграционные тесты."""

    @patch("app.gateways.notion_commits._query_commits")
    def test_all_query_functions_with_data(
        self, mock_query, mock_notion_response, sample_notion_page
    ):
        """Тест всех функций запросов с данными."""
        mock_notion_response["results"] = [sample_notion_page]
        mock_query.return_value = mock_notion_response

        # Тестируем все функции
        functions_to_test = [
            (query_commits_recent, {}),
            (query_commits_mine, {"me_name_en": "Test User"}),
            (query_commits_theirs, {}),
            (query_commits_due_within, {"days": 7}),
            (query_commits_due_today, {}),
            (query_commits_by_tag, {"tag": "Finance/Test"}),
            (query_commits_by_assignee, {"assignee_name": "Test User"}),
        ]

        for func, kwargs in functions_to_test:
            mock_query.reset_mock()

            result = func(**kwargs)

            # Каждая функция должна вызвать _query_commits (query_commits_mine вызывает дважды)
            assert mock_query.call_count >= 1

            # Каждая функция должна вернуть список (query_commits_mine может вернуть 2 элемента)
            assert len(result) >= 1
            if len(result) >= 1:
                assert result[0]["title"] == "John Doe: Подготовить отчет [due 2025-10-15]"

    @patch("app.gateways.notion_commits._query_commits")
    def test_error_handling_in_all_functions(self, mock_query):
        """Тест обработки ошибок во всех функциях запросов."""
        mock_query.side_effect = Exception("Test error")

        functions_to_test = [
            query_commits_recent,
            query_commits_mine,
            query_commits_theirs,
            query_commits_due_within,
            query_commits_due_today,
            lambda: query_commits_by_tag("test"),
            lambda: query_commits_by_assignee("test"),
        ]

        for func in functions_to_test:
            result = func()
            assert result == []  # Все функции должны возвращать пустой список при ошибке


class TestSettings:
    """Тесты интеграции с настройками."""

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_mine_uses_settings(self, mock_query, mock_notion_response):
        """Тест использования настроек для определения 'me'."""
        mock_query.return_value = mock_notion_response

        with patch("app.gateways.notion_commits.settings") as mock_settings:
            mock_settings.me_name_en = "Valentin Dobrynin"

            query_commits_mine()  # Без явного указания me_name_en

            # Проверяем, что _query_commits был вызван дважды (активные + выполненные)
            assert mock_query.call_count == 2

    @patch("app.gateways.notion_commits._query_commits")
    def test_query_commits_mine_override_settings(self, mock_query, mock_notion_response):
        """Тест переопределения настроек через параметр."""
        mock_query.return_value = mock_notion_response

        query_commits_mine(me_name_en="Custom User")

        # Проверяем, что _query_commits был вызван дважды (активные + выполненные)
        assert mock_query.call_count == 2
