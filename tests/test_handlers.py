"""
Тесты для модуля обработчиков бота app.bot.handlers
"""

from unittest.mock import Mock, patch

import pytest

from app.bot.handlers import _extract_page_id_from_url, run_commits_pipeline


class TestUtilityFunctions:
    """Тесты вспомогательных функций."""

    def test_extract_page_id_from_url_simple(self):
        """Тест извлечения page_id из простого URL."""
        url = "https://notion.so/page_123abc"
        result = _extract_page_id_from_url(url)
        assert result == "page_123abc"

    def test_extract_page_id_from_url_with_workspace(self):
        """Тест извлечения page_id из URL с workspace."""
        url = "https://www.notion.so/workspace/page_456def"
        result = _extract_page_id_from_url(url)
        assert result == "page_456def"

    def test_extract_page_id_from_url_with_trailing_slash(self):
        """Тест извлечения page_id из URL с завершающим слэшем."""
        url = "https://notion.so/page_789ghi/"
        result = _extract_page_id_from_url(url)
        assert result == "page_789ghi"

    def test_extract_page_id_from_url_complex(self):
        """Тест извлечения page_id из сложного URL."""
        url = "https://www.notion.so/myworkspace/Meeting-Notes-abc123def456?v=xyz"
        result = _extract_page_id_from_url(url)
        assert result == "Meeting-Notes-abc123def456?v=xyz"


class TestCommitsPipeline:
    """Тесты пайплайна обработки коммитов."""

    @pytest.mark.asyncio
    @patch("app.bot.handlers.extract_commits")
    @patch("app.bot.handlers.normalize_commits")
    @patch("app.bot.handlers.validate_and_partition")
    @patch("app.bot.handlers.upsert_commits")
    @patch("app.bot.handlers.enqueue_with_upsert")
    async def test_run_commits_pipeline_success(
        self,
        mock_enqueue,
        mock_upsert_commits,
        mock_validate_and_partition,
        mock_normalize_commits,
        mock_extract_commits,
    ):
        """Тест успешного выполнения пайплайна коммитов."""
        # Настраиваем моки
        mock_extract_commits.return_value = [Mock()]  # 1 извлеченный коммит
        mock_normalize_commits.return_value = [Mock()]  # 1 нормализованный коммит

        # Создаем правильные мок словари для review (как в commit_validate.py)
        review_dict = {
            "text": "review_item",
            "direction": "theirs",
            "assignees": ["John"],
            "due_iso": None,
            "confidence": 0.5,
            "flags": ["low_confidence"],
            "context": "test context",
            "status": "pending",
        }

        mock_partition_result = Mock()
        mock_partition_result.to_commits = [Mock(), Mock()]  # 2 качественных коммита
        mock_partition_result.to_review = [review_dict]  # 1 на ревью
        mock_validate_and_partition.return_value = mock_partition_result

        mock_upsert_commits.return_value = {"created": ["id1"], "updated": ["id2"]}
        mock_enqueue.return_value = {"created": 1, "updated": 0, "page_ids": ["review_id1"]}

        # Вызываем функцию
        result = await run_commits_pipeline(
            meeting_page_id="meeting_123",
            meeting_text="Test meeting text",
            attendees_en=["Valentin", "Daniil"],
            meeting_date_iso="2024-06-15",
            meeting_tags=["project/test"],
        )

        # Проверяем результат
        assert result == {"created": 1, "updated": 1, "review_created": 1, "review_updated": 0}

        # Проверяем вызовы функций
        mock_extract_commits.assert_called_once_with(
            text="Test meeting text",
            attendees_en=["Valentin", "Daniil"],
            meeting_date_iso="2024-06-15",
        )

        mock_normalize_commits.assert_called_once()
        mock_validate_and_partition.assert_called_once()
        mock_upsert_commits.assert_called_once()
        mock_enqueue.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.bot.handlers.extract_commits")
    @patch("app.bot.handlers.normalize_commits")
    @patch("app.bot.handlers.validate_and_partition")
    @patch("app.bot.handlers.upsert_commits")
    async def test_run_commits_pipeline_no_commits_to_review(
        self,
        mock_upsert_commits,
        mock_validate_and_partition,
        mock_normalize_commits,
        mock_extract_commits,
    ):
        """Тест пайплайна когда нет коммитов для ревью."""
        # Настраиваем моки
        mock_extract_commits.return_value = [Mock()]
        mock_normalize_commits.return_value = [Mock()]

        mock_partition_result = Mock()
        mock_partition_result.to_commits = [Mock()]  # 1 качественный коммит
        mock_partition_result.to_review = []  # нет коммитов на ревью
        mock_validate_and_partition.return_value = mock_partition_result

        mock_upsert_commits.return_value = {"created": ["id1"], "updated": []}

        # Вызываем функцию
        result = await run_commits_pipeline(
            meeting_page_id="meeting_123",
            meeting_text="Test meeting text",
            attendees_en=["Valentin"],
            meeting_date_iso="2024-06-15",
            meeting_tags=None,
        )

        # Проверяем результат
        assert result == {"created": 1, "updated": 0, "review_created": 0, "review_updated": 0}

    @pytest.mark.asyncio
    @patch("app.bot.handlers.extract_commits")
    @patch("app.bot.handlers.normalize_commits")
    @patch("app.bot.handlers.validate_and_partition")
    @patch("app.bot.handlers.upsert_commits")
    async def test_run_commits_pipeline_no_quality_commits(
        self,
        mock_upsert_commits,
        mock_validate_and_partition,
        mock_normalize_commits,
        mock_extract_commits,
    ):
        """Тест пайплайна когда нет качественных коммитов."""
        # Настраиваем моки
        mock_extract_commits.return_value = [Mock()]
        mock_normalize_commits.return_value = [Mock()]

        # Создаем правильные мок словари для review (как в commit_validate.py)
        review_dict1 = {
            "text": "review1",
            "direction": "theirs",
            "assignees": [],
            "due_iso": None,
            "confidence": 0.4,
            "flags": ["no_assignee"],
            "context": "context1",
            "status": "pending",
        }

        review_dict2 = {
            "text": "review2",
            "direction": "mine",
            "assignees": ["Jane"],
            "due_iso": "2024-12-31",
            "confidence": 0.6,
            "flags": [],
            "context": "context2",
            "status": "pending",
        }

        mock_partition_result = Mock()
        mock_partition_result.to_commits = []  # нет качественных коммитов
        mock_partition_result.to_review = [review_dict1, review_dict2]
        mock_validate_and_partition.return_value = mock_partition_result

        with patch("app.bot.handlers.enqueue_with_upsert") as mock_enqueue:
            mock_enqueue.return_value = {
                "created": 2,
                "updated": 0,
                "page_ids": ["review_id1", "review_id2"],
            }

            # Вызываем функцию
            result = await run_commits_pipeline(
                meeting_page_id="meeting_123",
                meeting_text="Test meeting text",
                attendees_en=["Valentin"],
                meeting_date_iso="2024-06-15",
                meeting_tags=["tag1"],
            )

        # Проверяем результат
        assert result == {"created": 0, "updated": 0, "review_created": 2, "review_updated": 0}

        # upsert_commits не должен вызываться
        mock_upsert_commits.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.bot.handlers.extract_commits")
    async def test_run_commits_pipeline_extract_error(self, mock_extract_commits):
        """Тест обработки ошибки в извлечении коммитов."""
        # Мокаем ошибку в extract_commits
        mock_extract_commits.side_effect = Exception("LLM API Error")

        # Вызываем функцию
        result = await run_commits_pipeline(
            meeting_page_id="meeting_123",
            meeting_text="Test meeting text",
            attendees_en=["Valentin"],
            meeting_date_iso="2024-06-15",
            meeting_tags=[],
        )

        # При ошибке должна возвращаться нулевая статистика
        assert result == {"created": 0, "updated": 0, "review_created": 0, "review_updated": 0}

    @pytest.mark.asyncio
    @patch("app.bot.handlers.extract_commits")
    @patch("app.bot.handlers.normalize_commits")
    @patch("app.bot.handlers.validate_and_partition")
    @patch("app.bot.handlers.upsert_commits")
    async def test_run_commits_pipeline_upsert_error(
        self,
        mock_upsert_commits,
        mock_validate_and_partition,
        mock_normalize_commits,
        mock_extract_commits,
    ):
        """Тест обработки ошибки в сохранении коммитов."""
        # Настраиваем моки
        mock_extract_commits.return_value = [Mock()]
        mock_normalize_commits.return_value = [Mock()]

        mock_partition_result = Mock()
        mock_partition_result.to_commits = [Mock()]
        mock_partition_result.to_review = []
        mock_validate_and_partition.return_value = mock_partition_result

        # Мокаем ошибку в upsert_commits
        mock_upsert_commits.side_effect = Exception("Notion API Error")

        # Вызываем функцию
        result = await run_commits_pipeline(
            meeting_page_id="meeting_123",
            meeting_text="Test meeting text",
            attendees_en=["Valentin"],
            meeting_date_iso="2024-06-15",
            meeting_tags=[],
        )

        # При ошибке должна возвращаться нулевая статистика
        assert result == {"created": 0, "updated": 0, "review_created": 0, "review_updated": 0}

    @pytest.mark.asyncio
    @patch("app.bot.handlers.extract_commits")
    @patch("app.bot.handlers.normalize_commits")
    @patch("app.bot.handlers.validate_and_partition")
    async def test_run_commits_pipeline_empty_extraction(
        self, mock_validate_and_partition, mock_normalize_commits, mock_extract_commits
    ):
        """Тест пайплайна когда LLM не извлек коммитов."""
        # Настраиваем моки
        mock_extract_commits.return_value = []  # нет извлеченных коммитов
        mock_normalize_commits.return_value = []

        mock_partition_result = Mock()
        mock_partition_result.to_commits = []
        mock_partition_result.to_review = []
        mock_validate_and_partition.return_value = mock_partition_result

        # Вызываем функцию
        result = await run_commits_pipeline(
            meeting_page_id="meeting_123",
            meeting_text="Meeting without commitments",
            attendees_en=["Valentin"],
            meeting_date_iso="2024-06-15",
            meeting_tags=[],
        )

        # Результат должен быть нулевым
        assert result == {"created": 0, "updated": 0, "review_created": 0, "review_updated": 0}

        # Все функции должны быть вызваны, но с пустыми данными
        mock_extract_commits.assert_called_once()
        mock_normalize_commits.assert_called_once_with(
            [], attendees_en=["Valentin"], meeting_date_iso="2024-06-15"
        )
        mock_validate_and_partition.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.bot.handlers.extract_commits")
    @patch("app.bot.handlers.normalize_commits")
    @patch("app.bot.handlers.validate_and_partition")
    @patch("app.bot.handlers.upsert_commits")
    @patch("app.bot.handlers.enqueue_with_upsert")
    async def test_run_commits_pipeline_with_tags(
        self,
        mock_enqueue,
        mock_upsert_commits,
        mock_validate_and_partition,
        mock_normalize_commits,
        mock_extract_commits,
    ):
        """Тест пайплайна с наследованием тегов встречи."""
        # Настраиваем моки
        mock_extract_commits.return_value = [Mock()]
        mock_normalize_commits.return_value = [Mock()]

        mock_commit = Mock()
        mock_commit.tags = ["existing_tag"]
        mock_partition_result = Mock()
        mock_partition_result.to_commits = [mock_commit]
        mock_partition_result.to_review = []
        mock_validate_and_partition.return_value = mock_partition_result

        mock_upsert_commits.return_value = {"created": ["id1"], "updated": []}

        meeting_tags = ["meeting_tag", "project/test"]

        # Вызываем функцию
        result = await run_commits_pipeline(
            meeting_page_id="meeting_123",
            meeting_text="Test meeting text",
            attendees_en=["Valentin"],
            meeting_date_iso="2024-06-15",
            meeting_tags=meeting_tags,
        )

        # Проверяем результат
        assert result == {"created": 1, "updated": 0, "review_created": 0, "review_updated": 0}

        # Проверяем, что validate_and_partition вызван с правильными тегами
        call_args = mock_validate_and_partition.call_args
        assert call_args[1]["meeting_tags"] == meeting_tags
