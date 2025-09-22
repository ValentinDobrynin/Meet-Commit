"""Тесты для административных команд синхронизации с Notion."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.bot.handlers_admin import sync_status_handler, sync_tags_handler
from app.core.tags_notion_sync import TagsSyncResult


@pytest.fixture(autouse=True)
def mock_is_admin():
    """Автоматически мокает _is_admin для всех тестов."""
    with patch("app.bot.handlers_admin._is_admin", return_value=True):
        yield


class TestSyncTagsHandler:
    """Тесты для команды /sync_tags."""

    @pytest.mark.asyncio
    async def test_sync_tags_success(self):
        """Тест успешной синхронизации."""
        mock_message = AsyncMock()
        mock_message.text = "/sync_tags"
        mock_message.answer = AsyncMock()

        # Мокаем результат синхронизации
        mock_result = TagsSyncResult(
            success=True,
            source="notion",
            rules_count=25,
            kind_breakdown={"Finance": 10, "Business": 8, "People": 7},
            cache_updated=True,
        )

        with patch("app.core.tags_notion_sync.smart_sync", return_value=mock_result):
            await sync_tags_handler(mock_message)

            # Проверяем, что было 2 вызова answer (начальное уведомление + результат)
            assert mock_message.answer.call_count == 2

            # Проверяем финальное сообщение
            final_call = mock_message.answer.call_args_list[1][0][0]
            assert "✅" in final_call
            assert "завершена" in final_call
            assert "25" in final_call
            assert "Finance=10" in final_call

    @pytest.mark.asyncio
    async def test_sync_tags_dry_run(self):
        """Тест dry-run синхронизации."""
        mock_message = AsyncMock()
        mock_message.text = "/sync_tags dry-run"
        mock_message.answer = AsyncMock()

        mock_result = TagsSyncResult(
            success=True,
            source="notion",
            rules_count=25,
            kind_breakdown={"Finance": 10, "Business": 15},
        )

        with patch("app.core.tags_notion_sync.smart_sync", return_value=mock_result) as mock_sync:
            await sync_tags_handler(mock_message)

            # Проверяем, что вызван с dry_run=True
            mock_sync.assert_called_once_with(dry_run=True)

            # Проверяем сообщение о dry-run
            final_call = mock_message.answer.call_args_list[1][0][0]
            assert "проверена" in final_call
            assert "Для применения запустите без dry-run" in final_call

    @pytest.mark.asyncio
    async def test_sync_tags_failure(self):
        """Тест неудачной синхронизации."""
        mock_message = AsyncMock()
        mock_message.text = "/sync_tags"
        mock_message.answer = AsyncMock()

        mock_result = TagsSyncResult(
            success=False, source="notion", rules_count=0, error="Connection timeout"
        )

        with patch("app.core.tags_notion_sync.smart_sync", return_value=mock_result):
            await sync_tags_handler(mock_message)

            # Проверяем сообщение об ошибке
            final_call = mock_message.answer.call_args_list[1][0][0]
            assert "❌" in final_call
            assert "Ошибка синхронизации" in final_call
            assert "Connection timeout" in final_call

    @pytest.mark.asyncio
    async def test_sync_tags_exception(self):
        """Тест обработки исключения."""
        mock_message = AsyncMock()
        mock_message.text = "/sync_tags"
        mock_message.answer = AsyncMock()

        with patch("app.core.tags_notion_sync.smart_sync", side_effect=Exception("Test error")):
            await sync_tags_handler(mock_message)

            # Проверяем обработку исключения
            final_call = mock_message.answer.call_args_list[1][0][0]
            assert "❌" in final_call
            assert "Test error" in final_call


class TestSyncStatusHandler:
    """Тесты для команды /sync_status."""

    @pytest.mark.asyncio
    async def test_sync_status_success(self):
        """Тест успешного получения статуса."""
        mock_message = AsyncMock()
        mock_message.answer = AsyncMock()

        mock_sync_status = {
            "last_sync": "2025-09-22 15:30:00",
            "hours_since_sync": 2.5,
            "source": "notion",
            "status": "success",
            "rules_count": 30,
            "kind_breakdown": {"Finance": 15, "Business": 10, "People": 5},
            "cache_available": True,
            "notion_accessible": True,
        }

        mock_catalog_info = {
            "accessible": True,
            "title": "Tag Catalog",
            "properties": ["Name", "Kind", "Pattern(s)", "Weight", "Active"],
        }

        with (
            patch("app.core.tags_notion_sync.get_sync_status", return_value=mock_sync_status),
            patch(
                "app.gateways.notion_tag_catalog.get_tag_catalog_info",
                return_value=mock_catalog_info,
            ),
        ):
            await sync_status_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]

            assert "📊" in call_args
            assert "2025-09-22 15:30:00" in call_args
            assert "2.5 часов" in call_args
            assert "notion" in call_args
            assert "success" in call_args
            assert "30" in call_args
            assert "Finance=15" in call_args

    @pytest.mark.asyncio
    async def test_sync_status_notion_not_accessible(self):
        """Тест статуса когда Notion недоступен."""
        mock_message = AsyncMock()
        mock_message.answer = AsyncMock()

        mock_sync_status = {
            "last_sync": "никогда",
            "status": "never_synced",
            "source": "unknown",
            "rules_count": 0,
        }

        mock_catalog_info = {"accessible": False, "error": "Database not found"}

        with (
            patch("app.core.tags_notion_sync.get_sync_status", return_value=mock_sync_status),
            patch(
                "app.gateways.notion_tag_catalog.get_tag_catalog_info",
                return_value=mock_catalog_info,
            ),
        ):
            await sync_status_handler(mock_message)

            call_args = mock_message.answer.call_args[0][0]
            assert "❌ Недоступен" in call_args
            assert "Database not found" in call_args

    @pytest.mark.asyncio
    async def test_sync_status_with_error(self):
        """Тест статуса с ошибкой."""
        mock_message = AsyncMock()
        mock_message.answer = AsyncMock()

        mock_sync_status = {
            "last_sync": "2025-09-22 15:30:00",
            "status": "failed",
            "source": "notion",
            "rules_count": 0,
            "error": "API timeout",
        }

        mock_catalog_info = {"accessible": False, "error": "timeout"}

        with (
            patch("app.core.tags_notion_sync.get_sync_status", return_value=mock_sync_status),
            patch(
                "app.gateways.notion_tag_catalog.get_tag_catalog_info",
                return_value=mock_catalog_info,
            ),
        ):
            await sync_status_handler(mock_message)

            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "API timeout" in call_args

    @pytest.mark.asyncio
    async def test_sync_status_exception(self):
        """Тест обработки исключения в sync_status."""
        mock_message = AsyncMock()
        mock_message.answer = AsyncMock()

        with patch(
            "app.core.tags_notion_sync.get_sync_status", side_effect=Exception("Test error")
        ):
            await sync_status_handler(mock_message)

            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "Test error" in call_args


class TestAdminAccessControl:
    """Тесты для контроля доступа к командам синхронизации."""

    @pytest.mark.asyncio
    async def test_sync_tags_non_admin_access(self):
        """Тест отказа в доступе для не-админа."""
        mock_message = AsyncMock()
        mock_message.text = "/sync_tags"
        mock_message.answer = AsyncMock()

        with patch("app.bot.handlers_admin._is_admin", return_value=False):
            await sync_tags_handler(mock_message)

            mock_message.answer.assert_called_once_with(
                "❌ Команда доступна только администраторам"
            )

    @pytest.mark.asyncio
    async def test_sync_status_non_admin_access(self):
        """Тест отказа в доступе для не-админа."""
        mock_message = AsyncMock()
        mock_message.answer = AsyncMock()

        with patch("app.bot.handlers_admin._is_admin", return_value=False):
            await sync_status_handler(mock_message)

            mock_message.answer.assert_called_once_with(
                "❌ Команда доступна только администраторам"
            )
