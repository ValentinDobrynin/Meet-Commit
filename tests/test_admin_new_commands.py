"""Тесты для новых административных команд."""

from unittest.mock import AsyncMock, patch

import pytest

from app.bot.handlers_admin import retag_handler, tags_validate_handler


class TestTagsValidateHandler:
    """Тесты команды /tags_validate."""

    @pytest.mark.asyncio
    async def test_tags_validate_success(self):
        """Тест успешной валидации YAML."""
        mock_message = AsyncMock()
        mock_message.text = "/tags_validate"

        with patch("app.bot.handlers_admin.validate_rules", return_value=[]):
            await tags_validate_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "✅" in call_args
            assert "валидация пройдена" in call_args

    @pytest.mark.asyncio
    async def test_tags_validate_with_errors(self):
        """Тест валидации с ошибками."""
        mock_message = AsyncMock()
        mock_message.text = "/tags_validate"

        test_errors = [
            "Invalid regex in Finance/IFRS pattern 0: '[invalid' -> missing closing bracket",
            "Weight must be 0.0-10.0 for tag Finance/Audit: 15.0",
            "Duplicate tag: Finance/IFRS",
        ]

        with patch("app.bot.handlers_admin.validate_rules", return_value=test_errors):
            await tags_validate_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert f"({len(test_errors)})" in call_args
            assert "Invalid regex" in call_args

    @pytest.mark.asyncio
    async def test_tags_validate_many_errors(self):
        """Тест валидации с большим количеством ошибок."""
        mock_message = AsyncMock()
        mock_message.text = "/tags_validate"

        # Создаем более 20 ошибок
        many_errors = [f"Error {i}" for i in range(25)]

        with patch("app.bot.handlers_admin.validate_rules", return_value=many_errors):
            await tags_validate_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "и еще 5 ошибок" in call_args  # 25 - 20 = 5

    @pytest.mark.asyncio
    async def test_tags_validate_exception(self):
        """Тест обработки исключений в валидации."""
        mock_message = AsyncMock()
        mock_message.text = "/tags_validate"

        with patch(
            "app.bot.handlers_admin.validate_rules", side_effect=Exception("Validation error")
        ):
            await tags_validate_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "Validation error" in call_args


class TestRetagHandler:
    """Тесты команды /retag."""

    @pytest.fixture
    def mock_page_data(self):
        """Мокает данные страницы встречи."""
        return {
            "page_id": "12345678-9012-3456-7890-123456789012",
            "title": "Test Meeting",
            "summary_md": "Обсудили IFRS аудит для Lavka проекта",
            "current_tags": ["Finance/IFRS", "Topic/Meeting"],
            "url": "https://notion.so/test-meeting",
        }

    @pytest.mark.asyncio
    async def test_retag_dry_run(self, mock_page_data):
        """Тест dry-run режима."""
        mock_message = AsyncMock()
        mock_message.text = "/retag 12345678901234567890123456789012 dry-run"

        with patch("app.gateways.notion_meetings.validate_meeting_access", return_value=True):
            with patch(
                "app.gateways.notion_meetings.fetch_meeting_page", return_value=mock_page_data
            ):
                with patch(
                    "app.core.tags.tag_text",
                    return_value=["Finance/IFRS", "Finance/Audit", "Business/Lavka"],
                ):
                    await retag_handler(mock_message)

                    # Проверяем, что было два вызова answer (статус + результат)
                    assert mock_message.answer.call_count == 2

                    # Проверяем содержимое последнего ответа
                    final_call = mock_message.answer.call_args_list[-1][0][0]
                    assert "🔍" in final_call  # Dry-run
                    assert "Test Meeting" in final_call
                    assert "Finance/Audit" in final_call  # Новый тег
                    assert "Business/Lavka" in final_call  # Новый тег

    @pytest.mark.asyncio
    async def test_retag_real_update(self, mock_page_data):
        """Тест реального обновления тегов."""
        mock_message = AsyncMock()
        mock_message.text = "/retag 12345678901234567890123456789012"

        with patch("app.gateways.notion_meetings.validate_meeting_access", return_value=True):
            with patch(
                "app.gateways.notion_meetings.fetch_meeting_page", return_value=mock_page_data
            ):
                with patch(
                    "app.core.tags.tag_text", return_value=["Finance/IFRS", "Finance/Audit"]
                ):
                    with patch(
                        "app.gateways.notion_meetings.update_meeting_tags", return_value=True
                    ) as mock_update:
                        await retag_handler(mock_message)

                        # Проверяем, что update_meeting_tags был вызван
                        mock_update.assert_called_once()
                        call_args = mock_update.call_args[0]
                        assert call_args[0] == "12345678901234567890123456789012"
                        assert "Finance/IFRS" in call_args[1]
                        assert "Finance/Audit" in call_args[1]

    @pytest.mark.asyncio
    async def test_retag_no_changes(self, mock_page_data):
        """Тест случая когда изменений нет."""
        mock_message = AsyncMock()
        mock_message.text = "/retag 12345678901234567890123456789012"

        # Возвращаем те же теги, что уже есть
        with patch("app.gateways.notion_meetings.validate_meeting_access", return_value=True):
            with patch(
                "app.gateways.notion_meetings.fetch_meeting_page", return_value=mock_page_data
            ):
                with patch(
                    "app.core.tags.tag_text", return_value=["Finance/IFRS", "Topic/Meeting"]
                ):
                    await retag_handler(mock_message)

                    final_call = mock_message.answer.call_args_list[-1][0][0]
                    assert "Изменений нет" in final_call

    @pytest.mark.asyncio
    async def test_retag_access_denied(self):
        """Тест случая когда нет доступа к странице."""
        mock_message = AsyncMock()
        mock_message.text = "/retag 12345678901234567890123456789012"

        with patch("app.gateways.notion_meetings.validate_meeting_access", return_value=False):
            await retag_handler(mock_message)

            mock_message.answer.assert_called()
            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "недоступна" in call_args

    @pytest.mark.asyncio
    async def test_retag_no_summary(self, mock_page_data):
        """Тест случая когда нет summary для пересчета."""
        mock_message = AsyncMock()
        mock_message.text = "/retag 12345678901234567890123456789012"

        # Убираем summary
        mock_page_data["summary_md"] = ""

        with patch("app.gateways.notion_meetings.validate_meeting_access", return_value=True):
            with patch(
                "app.gateways.notion_meetings.fetch_meeting_page", return_value=mock_page_data
            ):
                await retag_handler(mock_message)

                final_call = mock_message.answer.call_args_list[-1][0][0]
                assert "❌" in final_call
                assert "Нет summary" in final_call

    @pytest.mark.asyncio
    async def test_retag_update_error(self, mock_page_data):
        """Тест обработки ошибки при обновлении."""
        mock_message = AsyncMock()
        mock_message.text = "/retag 12345678901234567890123456789012"

        with patch("app.gateways.notion_meetings.validate_meeting_access", return_value=True):
            with patch(
                "app.gateways.notion_meetings.fetch_meeting_page", return_value=mock_page_data
            ):
                with patch("app.core.tags.tag_text", return_value=["Finance/Audit"]):
                    with patch(
                        "app.gateways.notion_meetings.update_meeting_tags",
                        side_effect=Exception("Update failed"),
                    ):
                        await retag_handler(mock_message)

                        final_call = mock_message.answer.call_args_list[-1][0][0]
                        assert "❌" in final_call
                        assert "Update failed" in final_call

    @pytest.mark.asyncio
    async def test_retag_invalid_command_format(self):
        """Тест неправильного формата команды."""
        mock_message = AsyncMock()
        mock_message.text = "/retag invalid-format"

        await retag_handler(mock_message)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "❌" in call_args
        assert "Неправильный формат" in call_args

    @pytest.mark.asyncio
    async def test_retag_general_exception(self):
        """Тест общей обработки исключений."""
        mock_message = AsyncMock()
        mock_message.text = "/retag 12345678901234567890123456789012"

        with patch(
            "app.gateways.notion_meetings.validate_meeting_access",
            side_effect=Exception("General error"),
        ):
            await retag_handler(mock_message)

            mock_message.answer.assert_called()
            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "General error" in call_args
