"""
Тесты для флага управления дедупликацией встреч.
"""

from unittest.mock import Mock, patch

from app.gateways.notion_gateway import upsert_meeting


class TestDedupFlag:
    """Тесты флага дедупликации."""

    @patch("app.gateways.notion_gateway.app_settings")
    @patch("app.gateways.notion_gateway._client")
    def test_dedup_enabled(self, mock_client, mock_settings):
        """Тест работы с включенной дедупликацией."""
        # Настраиваем мок
        mock_settings.enable_meetings_dedup = True

        mock_notion_client = Mock()
        mock_client.return_value = mock_notion_client

        # Мокаем поиск существующей встречи
        mock_notion_client.databases.query.return_value = {
            "results": [
                {
                    "id": "existing-meeting-id",
                    "url": "https://notion.so/existing-meeting",
                    "properties": {
                        "Tags": {"multi_select": [{"name": "Finance/IFRS"}]},
                        "Attendees": {"multi_select": [{"name": "Valya Dobrynin"}]},
                    },
                }
            ]
        }

        # Вызываем функцию
        result = upsert_meeting(
            {
                "title": "Test Meeting",
                "raw_hash": "test-hash-123",
                "summary_md": "Test summary",
                "tags": ["Business/Lavka"],
                "attendees": ["Sasha Katanov"],
                "date": "2025-09-25",
                "source": "telegram",
            }
        )

        # Проверяем что поиск был выполнен
        mock_notion_client.databases.query.assert_called_once()

        # Проверяем что обновление было выполнено (не создание)
        mock_notion_client.pages.update.assert_called_once()
        mock_notion_client.pages.create.assert_not_called()

        # Проверяем результат
        assert result == "https://notion.so/existing-meeting"

    @patch("app.gateways.notion_gateway.app_settings")
    @patch("app.gateways.notion_gateway._client")
    def test_dedup_disabled(self, mock_client, mock_settings):
        """Тест работы с отключенной дедупликацией."""
        # Настраиваем мок
        mock_settings.enable_meetings_dedup = False

        mock_notion_client = Mock()
        mock_client.return_value = mock_notion_client

        # Мокаем создание новой встречи
        mock_notion_client.pages.create.return_value = {"id": "new-meeting-id"}
        mock_notion_client.pages.retrieve.return_value = {"url": "https://notion.so/new-meeting"}

        # Вызываем функцию
        result = upsert_meeting(
            {
                "title": "Test Meeting",
                "raw_hash": "test-hash-123",
                "summary_md": "Test summary",
                "tags": ["Business/Lavka"],
                "attendees": ["Sasha Katanov"],
                "date": "2025-09-25",
                "source": "telegram",
            }
        )

        # Проверяем что поиск НЕ был выполнен
        mock_notion_client.databases.query.assert_not_called()

        # Проверяем что создание было выполнено
        mock_notion_client.pages.create.assert_called_once()
        mock_notion_client.pages.update.assert_not_called()

        # Проверяем результат
        assert result == "https://notion.so/new-meeting"

    @patch("app.gateways.notion_gateway.app_settings")
    @patch("app.gateways.notion_gateway._client")
    def test_dedup_enabled_no_hash(self, mock_client, mock_settings):
        """Тест работы без хэша (должно создавать новую встречу)."""
        # Настраиваем мок
        mock_settings.enable_meetings_dedup = True

        mock_notion_client = Mock()
        mock_client.return_value = mock_notion_client

        # Мокаем создание новой встречи
        mock_notion_client.pages.create.return_value = {"id": "new-meeting-id"}
        mock_notion_client.pages.retrieve.return_value = {"url": "https://notion.so/new-meeting"}

        # Вызываем функцию БЕЗ raw_hash
        result = upsert_meeting(
            {
                "title": "Test Meeting",
                "summary_md": "Test summary",
                "tags": ["Business/Lavka"],
                "attendees": ["Sasha Katanov"],
                "date": "2025-09-25",
                "source": "telegram",
            }
        )

        # Проверяем что поиск НЕ был выполнен (нет хэша)
        mock_notion_client.databases.query.assert_not_called()

        # Проверяем что создание было выполнено
        mock_notion_client.pages.create.assert_called_once()

        # Проверяем результат
        assert result == "https://notion.so/new-meeting"


class TestDedupMetrics:
    """Тесты метрик дедупликации."""

    @patch("app.gateways.notion_gateway.app_settings")
    @patch("app.gateways.notion_gateway._client")
    @patch("app.gateways.notion_gateway.inc")
    def test_metrics_hit(self, mock_inc, mock_client, mock_settings):
        """Тест метрики при попадании в кэш."""
        # Настраиваем мок
        mock_settings.enable_meetings_dedup = True

        mock_notion_client = Mock()
        mock_client.return_value = mock_notion_client

        # Мокаем найденную встречу
        mock_notion_client.databases.query.return_value = {
            "results": [
                {
                    "id": "existing-id",
                    "url": "https://notion.so/existing",
                    "properties": {"Tags": {"multi_select": []}, "Attendees": {"multi_select": []}},
                }
            ]
        }

        # Вызываем функцию
        upsert_meeting({"title": "Test", "raw_hash": "test-hash", "summary_md": "Test"})

        # Проверяем что метрика hit была увеличена
        mock_inc.assert_any_call("meetings.dedup.hit")

    @patch("app.gateways.notion_gateway.app_settings")
    @patch("app.gateways.notion_gateway._client")
    @patch("app.gateways.notion_gateway.inc")
    def test_metrics_miss(self, mock_inc, mock_client, mock_settings):
        """Тест метрики при промахе."""
        # Настраиваем мок
        mock_settings.enable_meetings_dedup = True

        mock_notion_client = Mock()
        mock_client.return_value = mock_notion_client

        # Мокаем отсутствие встреч
        mock_notion_client.databases.query.return_value = {"results": []}
        mock_notion_client.pages.create.return_value = {"id": "new-id"}
        mock_notion_client.pages.retrieve.return_value = {"url": "https://notion.so/new"}

        # Вызываем функцию
        upsert_meeting({"title": "Test", "raw_hash": "test-hash", "summary_md": "Test"})

        # Проверяем что метрика miss была увеличена
        mock_inc.assert_any_call("meetings.dedup.miss")


class TestDedupIntegration:
    """Интеграционные тесты дедупликации."""

    def test_settings_default_value(self):
        """Тест что дедупликация включена по умолчанию."""
        from app.settings import settings

        assert settings.enable_meetings_dedup is True

    @patch.dict("os.environ", {"APP_ENABLE_MEETINGS_DEDUP": "false"})
    def test_settings_env_override(self):
        """Тест переопределения через переменную окружения."""
        # Перезагружаем настройки
        from importlib import reload

        import app.settings

        reload(app.settings)

        assert app.settings.settings.enable_meetings_dedup is False
