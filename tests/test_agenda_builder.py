"""
Тесты для системы сборки повесток.
"""

from unittest.mock import Mock, patch

import pytest

from app.core.agenda_builder import (
    AgendaBundle,
    _extract_tags_and_people,
    _format_commit_line,
    _format_review_line,
    _generate_hash,
    _map_review_page,
    _query_commits,
    _query_review,
    build_for_meeting,
    build_for_person,
    build_for_tag,
)


class TestAgendaBundle:
    """Тесты для структуры данных AgendaBundle."""

    def test_agenda_bundle_creation(self):
        """Тест создания AgendaBundle."""
        bundle = AgendaBundle(
            context_type="Meeting",
            context_key="test-meeting-123",
            debts_mine=[{"id": "1", "text": "Test"}],
            debts_theirs=[],
            review_open=[],
            recent_done=[],
            commits_linked=["1"],
            summary_md="# Test",
            tags=["Test/Tag"],
            people=["Test User"],
            raw_hash="abcd1234",
        )

        assert bundle.context_type == "Meeting"
        assert bundle.context_key == "test-meeting-123"
        assert len(bundle.debts_mine) == 1
        assert bundle.raw_hash == "abcd1234"


class TestFormatting:
    """Тесты для функций форматирования."""

    def test_format_commit_line(self):
        """Тест форматирования строки коммита."""
        commit = {
            "text": "Test commit",
            "assignees": ["John Doe", "Jane Smith"],
            "due_date": "2025-10-15",
            "status": "open",
        }

        result = _format_commit_line(commit)

        assert "🟥" in result  # status emoji
        assert "Test commit" in result
        assert "John Doe, Jane Smith" in result
        assert "2025-10-15" in result

    def test_format_commit_line_no_assignees(self):
        """Тест форматирования коммита без исполнителей."""
        commit = {"text": "Test commit", "assignees": [], "due_date": None, "status": "done"}

        result = _format_commit_line(commit)

        assert "✅" in result  # done status
        assert "—" in result  # no assignees and due date

    def test_format_review_line(self):
        """Тест форматирования строки ревью."""
        review = {"text": "Review question", "reason": ["unclear", "missing info"]}

        result = _format_review_line(review)

        assert "❓" in result
        assert "Review question" in result
        assert "(unclear, missing info)" in result

    def test_format_review_line_no_reason(self):
        """Тест форматирования ревью без причины."""
        review = {"text": "Simple question", "reason": []}

        result = _format_review_line(review)

        assert "❓" in result
        assert "Simple question" in result
        assert "(" not in result  # no reason


class TestUtilities:
    """Тесты для вспомогательных функций."""

    def test_extract_tags_and_people(self):
        """Тест извлечения тегов и участников."""
        commits = [
            {"tags": ["Finance/IFRS", "People/John"], "assignees": ["John Doe", "Jane Smith"]},
            {"tags": ["Business/Lavka"], "assignees": ["John Doe"]},
        ]
        reviews = [{"tags": ["Finance/IFRS", "Topic/Meeting"]}]

        tags, people = _extract_tags_and_people(commits, reviews)

        assert "Finance/IFRS" in tags
        assert "Business/Lavka" in tags
        assert "People/John" in tags
        assert "Topic/Meeting" in tags
        assert "John Doe" in people
        assert "Jane Smith" in people

    def test_generate_hash(self):
        """Тест генерации хеша для дедупликации."""
        commits = [{"id": "commit-1"}, {"id": "commit-2"}]
        reviews = [{"id": "review-1"}]

        hash1 = _generate_hash("Meeting", "meeting-123", commits, reviews)
        hash2 = _generate_hash("Meeting", "meeting-123", commits, reviews)
        hash3 = _generate_hash("Person", "meeting-123", commits, reviews)

        assert len(hash1) == 16
        assert hash1 == hash2  # Same input = same hash
        assert hash1 != hash3  # Different context_type = different hash


class TestMapReviewPage:
    """Тесты для маппинга страниц ревью."""

    def test_map_review_page_full(self):
        """Тест маппинга полной страницы ревью."""
        page = {
            "id": "review-123",
            "url": "https://notion.so/review-123",
            "properties": {
                "Commit text": {"rich_text": [{"plain_text": "Review this commit"}]},
                "Reason": {"multi_select": [{"name": "unclear"}, {"name": "incomplete"}]},
                "Tags": {"multi_select": [{"name": "Finance/IFRS"}, {"name": "Topic/Review"}]},
                "Status": {"select": {"name": "pending"}},
                "Meeting": {"relation": [{"id": "meeting-123"}]},
            },
        }

        result = _map_review_page(page)

        assert result["id"] == "review-123"
        assert result["url"] == "https://notion.so/review-123"
        assert result["text"] == "Review this commit"
        assert result["reason"] == ["unclear", "incomplete"]
        assert result["tags"] == ["Finance/IFRS", "Topic/Review"]
        assert result["status"] == "pending"
        assert result["meeting_ids"] == ["meeting-123"]

    def test_map_review_page_empty_fields(self):
        """Тест маппинга страницы ревью с пустыми полями."""
        page = {
            "id": "review-456",
            "properties": {
                "Commit text": {"rich_text": []},
                "Reason": {"multi_select": []},
                "Tags": {"multi_select": []},
                "Status": {"select": None},
                "Meeting": {"relation": []},
            },
        }

        result = _map_review_page(page)

        assert result["id"] == "review-456"
        assert result["url"] == ""
        assert result["text"] == ""
        assert result["reason"] == []
        assert result["tags"] == []
        assert result["status"] is None
        assert result["meeting_ids"] == []


class TestBuildFunctions:
    """Тесты для функций построения повесток."""

    @patch("app.core.agenda_builder._query_commits")
    @patch("app.core.agenda_builder._query_review")
    def test_build_for_meeting(self, mock_query_review, mock_query_commits):
        """Тест построения повестки для встречи."""
        # Мокаем данные
        mock_query_commits.return_value = [
            {
                "id": "commit-1",
                "text": "Test commit 1",
                "assignees": ["John Doe"],
                "due_date": "2025-10-15",
                "status": "open",
                "tags": ["Finance/IFRS"],
                "url": "https://notion.so/commit-1",
            }
        ]

        mock_query_review.return_value = [
            {
                "id": "review-1",
                "text": "Review question",
                "reason": ["unclear"],
                "tags": ["Finance/IFRS"],
                "status": "pending",
                "meeting_ids": ["meeting-123"],
            }
        ]

        # Тестируем
        bundle = build_for_meeting("meeting-123")

        # Проверяем результат
        assert bundle.context_type == "Meeting"
        assert bundle.context_key == "meeting-123"
        assert len(bundle.debts_mine) == 1
        assert len(bundle.review_open) == 1
        assert "commit-1" in bundle.commits_linked
        assert "🧾" in bundle.summary_md
        assert "❓" in bundle.summary_md
        assert "Finance/IFRS" in bundle.tags
        assert "John Doe" in bundle.people

    @patch("app.core.agenda_builder._query_commits")
    @patch("app.core.agenda_builder._query_review")
    def test_build_for_person(self, mock_query_review, mock_query_commits):
        """Тест построения персональной повестки."""
        # Мокаем запросы (3 вызова для mine, theirs, done)
        mock_query_commits.side_effect = [
            # Mine debts
            [
                {
                    "id": "commit-1",
                    "text": "My debt",
                    "assignees": ["John Doe"],
                    "due_date": "2025-10-15",
                    "status": "open",
                    "tags": [],
                    "url": "",
                }
            ],
            # Their debts
            [
                {
                    "id": "commit-2",
                    "text": "Their debt",
                    "assignees": ["Jane Smith"],
                    "due_date": "2025-10-16",
                    "status": "open",
                    "tags": [],
                    "url": "",
                }
            ],
            # Recent done
            [
                {
                    "id": "commit-3",
                    "text": "Done task",
                    "assignees": ["John Doe"],
                    "due_date": "2025-10-10",
                    "status": "done",
                    "tags": [],
                    "url": "",
                }
            ],
        ]

        mock_query_review.return_value = []

        # Тестируем
        bundle = build_for_person("John Doe")

        # Проверяем результат
        assert bundle.context_type == "Person"
        assert bundle.context_key == "People/John Doe"
        assert len(bundle.debts_mine) == 1
        assert len(bundle.debts_theirs) == 1
        assert len(bundle.recent_done) == 1
        assert "👤" in bundle.summary_md
        assert "👥" in bundle.summary_md
        assert "✅" in bundle.summary_md

    @patch("app.core.agenda_builder._query_commits")
    @patch("app.core.agenda_builder._query_review")
    def test_build_for_tag(self, mock_query_review, mock_query_commits):
        """Тест построения тематической повестки."""
        # Мокаем запросы (2 вызова для active, done)
        mock_query_commits.side_effect = [
            # Active commits
            [
                {
                    "id": "commit-1",
                    "text": "Active task",
                    "assignees": ["John Doe"],
                    "due_date": "2025-10-15",
                    "status": "open",
                    "tags": ["Finance/IFRS"],
                    "url": "",
                }
            ],
            # Recent done
            [
                {
                    "id": "commit-2",
                    "text": "Done task",
                    "assignees": ["Jane Smith"],
                    "due_date": "2025-10-10",
                    "status": "done",
                    "tags": ["Finance/IFRS"],
                    "url": "",
                }
            ],
        ]

        mock_query_review.return_value = []

        # Тестируем
        bundle = build_for_tag("Finance/IFRS")

        # Проверяем результат
        assert bundle.context_type == "Tag"
        assert bundle.context_key == "Finance/IFRS"
        assert len(bundle.debts_mine) == 1
        assert len(bundle.recent_done) == 1
        assert "🏷️" in bundle.summary_md
        assert "✅" in bundle.summary_md
        assert "Finance/IFRS" in bundle.tags


class TestQueryFunctions:
    """Тесты для функций запросов."""

    @patch("app.core.agenda_builder._create_commits_client")
    def test_query_commits_success(self, mock_create_client):
        """Тест успешного запроса коммитов."""
        # Мокаем клиент и ответ
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "commit-1",
                    "properties": {
                        "Text": {"rich_text": [{"plain_text": "Test commit"}]},
                        "Status": {"select": {"name": "open"}},
                        "Assignee": {"multi_select": [{"name": "John Doe"}]},
                        "Due": {"date": {"start": "2025-10-15"}},
                        "Direction": {"select": {"name": "mine"}},
                        "Tags": {"multi_select": [{"name": "Test/Tag"}]},
                        "Meeting": {"relation": []},
                    },
                }
            ]
        }
        mock_client.post.return_value = mock_response
        mock_response.raise_for_status.return_value = None

        # Тестируем
        filter_ = {"property": "Status", "select": {"equals": "open"}}
        result = _query_commits(filter_)

        # Проверяем
        assert len(result) == 1
        assert result[0]["text"] == "Test commit"
        assert result[0]["status"] == "open"
        mock_client.close.assert_called_once()

    @patch("app.core.agenda_builder._create_review_client")
    def test_query_review_success(self, mock_create_client):
        """Тест успешного запроса ревью."""
        # Мокаем клиент и ответ
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "review-1",
                    "url": "https://notion.so/review-1",
                    "properties": {
                        "Commit text": {"rich_text": [{"plain_text": "Review question"}]},
                        "Reason": {"multi_select": [{"name": "unclear"}]},
                        "Tags": {"multi_select": [{"name": "Finance/IFRS"}]},
                        "Status": {"select": {"name": "pending"}},
                        "Meeting": {"relation": [{"id": "meeting-123"}]},
                    },
                }
            ]
        }
        mock_client.post.return_value = mock_response
        mock_response.raise_for_status.return_value = None

        # Тестируем
        filter_ = {"property": "Status", "select": {"equals": "pending"}}
        result = _query_review(filter_)

        # Проверяем
        assert len(result) == 1
        assert result[0]["text"] == "Review question"
        assert result[0]["reason"] == ["unclear"]
        mock_client.close.assert_called_once()


class TestErrorHandling:
    """Тесты обработки ошибок."""

    @patch("app.core.agenda_builder._query_commits")
    @patch("app.core.agenda_builder._query_review")
    def test_build_for_meeting_empty_data(self, mock_query_review, mock_query_commits):
        """Тест построения повестки с пустыми данными."""
        mock_query_commits.return_value = []
        mock_query_review.return_value = []

        bundle = build_for_meeting("empty-meeting")

        assert bundle.context_type == "Meeting"
        assert bundle.context_key == "empty-meeting"
        assert len(bundle.debts_mine) == 0
        assert len(bundle.review_open) == 0
        assert bundle.commits_linked == []
        assert "📋 Повестка пуста" in bundle.summary_md
        assert bundle.tags == []
        assert bundle.people == []

    @patch("app.core.agenda_builder._create_commits_client")
    def test_query_commits_http_error(self, mock_create_client):
        """Тест обработки HTTP ошибки при запросе коммитов."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 400")
        mock_client.post.return_value = mock_response

        # Тестируем
        filter_ = {"property": "Status", "select": {"equals": "open"}}

        with pytest.raises(Exception):  # noqa: B017
            _query_commits(filter_)

        mock_client.close.assert_called_once()


class TestIntegration:
    """Интеграционные тесты."""

    @patch("app.core.agenda_builder._query_commits")
    @patch("app.core.agenda_builder._query_review")
    def test_full_agenda_workflow(self, mock_query_review, mock_query_commits):
        """Тест полного цикла создания повестки."""
        # Подготавливаем данные
        mock_query_commits.return_value = [
            {
                "id": "commit-1",
                "text": "Important task",
                "assignees": ["John Doe", "Jane Smith"],
                "due_date": "2025-10-15",
                "status": "open",
                "tags": ["Finance/IFRS", "People/John Doe"],
                "url": "https://notion.so/commit-1",
            }
        ]

        mock_query_review.return_value = [
            {
                "id": "review-1",
                "text": "Need clarification",
                "reason": ["unclear", "incomplete"],
                "tags": ["Finance/IFRS"],
                "status": "pending",
                "meeting_ids": ["meeting-123"],
            }
        ]

        # Создаем повестку
        bundle = build_for_meeting("meeting-123")

        # Проверяем полную структуру
        assert bundle.context_type == "Meeting"
        assert bundle.context_key == "meeting-123"
        assert len(bundle.debts_mine) == 1
        assert len(bundle.review_open) == 1
        assert bundle.commits_linked == ["commit-1"]
        assert len(bundle.raw_hash) == 16

        # Проверяем содержимое summary
        assert "🧾" in bundle.summary_md
        assert "Important task" in bundle.summary_md
        assert "❓" in bundle.summary_md
        assert "Need clarification" in bundle.summary_md

        # Проверяем теги и участников
        assert "Finance/IFRS" in bundle.tags
        assert "People/John Doe" in bundle.tags
        assert "John Doe" in bundle.people
        assert "Jane Smith" in bundle.people
