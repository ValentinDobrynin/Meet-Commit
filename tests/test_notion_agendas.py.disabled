"""Тесты для gateway работы с базой Agendas."""

from unittest.mock import Mock, patch

import pytest

from app.gateways.notion_agendas import (
    _build_agenda_properties,
    create_agenda,
    find_agenda_by_hash,
    get_agenda_statistics,
    query_agendas_by_context,
)


class TestBuildAgendaProperties:
    """Тесты построения properties для Agenda."""

    def test_build_agenda_properties_minimal(self):
        """Тест создания минимальных properties."""
        props = _build_agenda_properties(
            name="Agenda — Test",
            date_iso="2025-09-24",
            context_type="Meeting",
            context_key="meeting-123",
            summary_md="# Test agenda",
            tags=["Finance/Test"],
            people=["John Doe"],
            raw_hash="abc123",
        )

        assert props["Name"]["title"][0]["text"]["content"] == "Agenda — Test"
        assert props["Date"]["date"]["start"] == "2025-09-24"
        assert props["Context type"]["select"]["name"] == "Meeting"
        assert props["Context key"]["rich_text"][0]["text"]["content"] == "meeting-123"
        assert props["Summary MD"]["rich_text"][0]["text"]["content"] == "# Test agenda"
        assert props["Tags"]["multi_select"][0]["name"] == "Finance/Test"
        assert props["People"]["multi_select"][0]["name"] == "John Doe"
        assert props["Raw hash"]["rich_text"][0]["text"]["content"] == "abc123"

    def test_build_agenda_properties_with_commits(self):
        """Тест создания properties с связанными коммитами."""
        props = _build_agenda_properties(
            name="Agenda — Test",
            date_iso="2025-09-24",
            context_type="Person",
            context_key="People/Valya",
            summary_md="# Personal agenda",
            tags=["People/Valya"],
            people=["Valya Dobrynin"],
            raw_hash="def456",
            commit_ids=["commit-1", "commit-2"],
        )

        assert "Commits linked" in props
        assert len(props["Commits linked"]["relation"]) == 2
        assert props["Commits linked"]["relation"][0]["id"] == "commit-1"
        assert props["Commits linked"]["relation"][1]["id"] == "commit-2"

    def test_build_agenda_properties_long_summary(self):
        """Тест обрезки длинного summary."""
        long_summary = "# Very long summary\n" + "Content line\n" * 200

        props = _build_agenda_properties(
            name="Test",
            date_iso="2025-09-24",
            context_type="Tag",
            context_key="Finance/IFRS",
            summary_md=long_summary,
            tags=[],
            people=[],
            raw_hash="long123",
        )

        # Проверяем, что summary обрезан до 2000 символов
        summary_content = props["Summary MD"]["rich_text"][0]["text"]["content"]
        assert len(summary_content) <= 2000


class TestFindAgendaByHash:
    """Тесты поиска повестки по хэшу."""

    @patch("app.gateways.notion_agendas._create_client")
    def test_find_agenda_by_hash_found(self, mock_create_client):
        """Тест успешного поиска повестки."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {"results": [{"id": "agenda-123", "properties": {}}]}
        mock_client.post.return_value = mock_response

        result = find_agenda_by_hash("test-hash")

        assert result is not None
        assert result["id"] == "agenda-123"
        mock_client.post.assert_called_once()

    @patch("app.gateways.notion_agendas._create_client")
    def test_find_agenda_by_hash_not_found(self, mock_create_client):
        """Тест поиска несуществующей повестки."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response

        result = find_agenda_by_hash("nonexistent-hash")

        assert result is None

    @patch("app.gateways.notion_agendas._create_client")
    def test_find_agenda_by_hash_error(self, mock_create_client):
        """Тест обработки ошибки при поиске."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client
        mock_client.post.side_effect = Exception("API Error")

        result = find_agenda_by_hash("error-hash")

        assert result is None


class TestCreateAgenda:
    """Тесты создания повестки."""

    @patch("app.gateways.notion_agendas.find_agenda_by_hash")
    @patch("app.gateways.notion_agendas._create_client")
    def test_create_agenda_success(self, mock_create_client, mock_find_hash):
        """Тест успешного создания повестки."""
        # Настраиваем мок для дедупликации
        mock_find_hash.return_value = None  # Повестки не существует

        # Настраиваем мок клиента
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "new-agenda-123"}
        mock_client.post.return_value = mock_response

        result = create_agenda(
            name="Agenda — Test Meeting",
            date_iso="2025-09-24",
            context_type="Meeting",
            context_key="meeting-123",
            summary_md="# Test agenda content",
            tags=["Finance/Test"],
            people=["John Doe"],
            raw_hash="test-hash",
        )

        assert result == "new-agenda-123"
        mock_client.post.assert_called_once()

    @patch("app.gateways.notion_agendas.find_agenda_by_hash")
    def test_create_agenda_duplicate(self, mock_find_hash):
        """Тест создания дублирующейся повестки."""
        # Повестка уже существует
        mock_find_hash.return_value = {"id": "existing-agenda-123"}

        result = create_agenda(
            name="Duplicate Agenda",
            date_iso="2025-09-24",
            context_type="Meeting",
            context_key="meeting-123",
            summary_md="# Duplicate content",
            tags=[],
            people=[],
            raw_hash="duplicate-hash",
        )

        assert result == "existing-agenda-123"

    @patch("app.gateways.notion_agendas.find_agenda_by_hash")
    @patch("app.gateways.notion_agendas._create_client")
    def test_create_agenda_api_error(self, mock_create_client, mock_find_hash):
        """Тест обработки ошибки API при создании."""
        mock_find_hash.return_value = None

        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_client.post.return_value = mock_response

        with pytest.raises(RuntimeError, match="Notion API error: 400"):
            create_agenda(
                name="Error Agenda",
                date_iso="2025-09-24",
                context_type="Meeting",
                context_key="meeting-123",
                summary_md="# Error content",
                tags=[],
                people=[],
                raw_hash="error-hash",
            )


class TestQueryAgendas:
    """Тесты запросов повесток."""

    @patch("app.gateways.notion_agendas._create_client")
    def test_query_agendas_by_context_type_only(self, mock_create_client):
        """Тест запроса по типу контекста."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [{"id": "agenda-1", "properties": {}}, {"id": "agenda-2", "properties": {}}]
        }
        mock_client.post.return_value = mock_response

        result = query_agendas_by_context("Meeting")

        assert len(result) == 2
        assert result[0]["id"] == "agenda-1"

        # Проверяем payload
        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["filter"]["property"] == "Context type"
        assert payload["filter"]["select"]["equals"] == "Meeting"

    @patch("app.gateways.notion_agendas._create_client")
    def test_query_agendas_by_context_with_key(self, mock_create_client):
        """Тест запроса по типу и ключу контекста."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response

        result = query_agendas_by_context("Person", "People/Valya", limit=5)

        assert result == []

        # Проверяем payload с AND фильтром
        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert "and" in payload["filter"]
        assert len(payload["filter"]["and"]) == 2
        assert payload["page_size"] == 5

    @patch("app.gateways.notion_agendas._create_client")
    def test_query_agendas_error(self, mock_create_client):
        """Тест обработки ошибки при запросе."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client
        mock_client.post.side_effect = Exception("Network error")

        result = query_agendas_by_context("Tag")

        assert result == []


class TestAgendaStatistics:
    """Тесты статистики повесток."""

    @patch("app.gateways.notion_agendas._create_client")
    def test_get_agenda_statistics_success(self, mock_create_client):
        """Тест получения статистики."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "agenda-1",
                    "properties": {
                        "Name": {"title": [{"plain_text": "Agenda — Meeting Test"}]},
                        "Date": {"date": {"start": "2025-09-24"}},
                        "Context type": {"select": {"name": "Meeting"}},
                        "Tags": {
                            "multi_select": [{"name": "Finance/IFRS"}, {"name": "Topic/Meeting"}]
                        },
                        "People": {"multi_select": [{"name": "John Doe"}, {"name": "Jane Smith"}]},
                    },
                },
                {
                    "id": "agenda-2",
                    "properties": {
                        "Name": {"title": [{"plain_text": "Agenda — Person Valya"}]},
                        "Date": {"date": {"start": "2025-09-23"}},
                        "Context type": {"select": {"name": "Person"}},
                        "Tags": {"multi_select": [{"name": "People/Valya"}]},
                        "People": {"multi_select": [{"name": "Valya Dobrynin"}]},
                    },
                },
            ]
        }
        mock_client.post.return_value = mock_response

        stats = get_agenda_statistics()

        assert stats["total_agendas"] == 2
        assert stats["by_context_type"]["Meeting"] == 1
        assert stats["by_context_type"]["Person"] == 1
        assert stats["by_context_type"]["Tag"] == 0

        assert len(stats["recent_agendas"]) == 2
        assert stats["recent_agendas"][0]["name"] == "Agenda — Meeting Test"

        assert "Finance/IFRS" in stats["top_tags"]
        assert stats["top_tags"]["Finance/IFRS"] == 1

        assert "John Doe" in stats["top_people"]
        assert stats["top_people"]["John Doe"] == 1

    @patch("app.gateways.notion_agendas._create_client")
    def test_get_agenda_statistics_empty(self, mock_create_client):
        """Тест статистики для пустой базы."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response

        stats = get_agenda_statistics()

        assert stats["total_agendas"] == 0
        assert stats["by_context_type"]["Meeting"] == 0
        assert len(stats["recent_agendas"]) == 0
        assert len(stats["top_tags"]) == 0

    @patch("app.gateways.notion_agendas._create_client")
    def test_get_agenda_statistics_error(self, mock_create_client):
        """Тест обработки ошибки при получении статистики."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client
        mock_client.post.side_effect = Exception("API Error")

        stats = get_agenda_statistics()

        assert stats == {}


class TestIntegration:
    """Интеграционные тесты."""

    @patch("app.gateways.notion_agendas._create_client")
    def test_full_workflow_create_and_find(self, mock_create_client):
        """Тест полного цикла: создание → поиск → дедупликация."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        # Первый вызов - поиск (не найдено)
        mock_response_search = Mock()
        mock_response_search.json.return_value = {"results": []}

        # Второй вызов - создание
        mock_response_create = Mock()
        mock_response_create.status_code = 200
        mock_response_create.json.return_value = {"id": "new-agenda-123"}

        mock_client.post.side_effect = [mock_response_search, mock_response_create]

        # Создаем повестку
        agenda_id = create_agenda(
            name="Agenda — Integration Test",
            date_iso="2025-09-24",
            context_type="Meeting",
            context_key="meeting-test",
            summary_md="# Integration test agenda",
            tags=["Test/Integration"],
            people=["Test User"],
            raw_hash="integration-hash",
        )

        assert agenda_id == "new-agenda-123"
        assert mock_client.post.call_count == 2  # Поиск + создание

    @patch("app.gateways.notion_agendas._create_client")
    def test_context_types_validation(self, mock_create_client):
        """Тест валидации типов контекста."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response

        # Тестируем все валидные типы контекста
        valid_types = ["Meeting", "Person", "Tag"]

        for context_type in valid_types:
            result = query_agendas_by_context(context_type)
            assert isinstance(result, list)

        assert mock_client.post.call_count == len(valid_types)


class TestErrorHandling:
    """Тесты обработки ошибок."""

    @patch("app.gateways.notion_agendas._create_client")
    def test_client_creation_error(self, mock_create_client):
        """Тест ошибки создания клиента."""
        mock_create_client.side_effect = RuntimeError("No credentials")

        with pytest.raises(RuntimeError, match="No credentials"):
            create_agenda(
                name="Error Test",
                date_iso="2025-09-24",
                context_type="Meeting",
                context_key="error-test",
                summary_md="# Error",
                tags=[],
                people=[],
                raw_hash="error-hash",
            )

    @patch("app.gateways.notion_agendas.find_agenda_by_hash")
    @patch("app.gateways.notion_agendas._create_client")
    def test_create_agenda_network_error(self, mock_create_client, mock_find_hash):
        """Тест сетевой ошибки при создании."""
        mock_find_hash.return_value = None

        mock_client = Mock()
        mock_create_client.return_value = mock_client
        mock_client.post.side_effect = Exception("Network timeout")

        with pytest.raises(Exception, match="Network timeout"):
            create_agenda(
                name="Network Error Test",
                date_iso="2025-09-24",
                context_type="Meeting",
                context_key="network-test",
                summary_md="# Network error",
                tags=[],
                people=[],
                raw_hash="network-hash",
            )


class TestMetricsIntegration:
    """Тесты интеграции с системой метрик."""

    @patch("app.gateways.notion_agendas._create_client")
    def test_metrics_tracking(self, mock_create_client):
        """Тест отслеживания метрик."""
        from app.core.metrics import reset_metrics, snapshot

        # Сбрасываем метрики
        reset_metrics()

        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {"results": []}
        mock_client.post.return_value = mock_response

        # Выполняем запрос
        query_agendas_by_context("Meeting")

        # Проверяем метрики
        metrics = snapshot()
        assert "notion.query_agendas.success" in metrics.counters
        assert metrics.counters["notion.query_agendas.success"] == 1
        assert "notion.query_agendas" in metrics.latency
