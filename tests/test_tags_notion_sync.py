"""Тесты для сервиса синхронизации правил тегирования."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.tags_notion_sync import (
    TagsSyncResult,
    _calculate_kind_breakdown,
    _convert_notion_rules_to_yaml_format,
    _load_rules_cache,
    _save_rules_cache,
    get_sync_status,
    smart_sync,
    sync_from_cache,
    sync_from_notion,
    sync_from_yaml,
)


class TestTagsSyncResult:
    """Тесты для класса TagsSyncResult."""

    def test_sync_result_creation(self):
        """Тест создания результата синхронизации."""
        result = TagsSyncResult(
            success=True,
            source="notion",
            rules_count=10,
            kind_breakdown={"Finance": 5, "Business": 5},
        )

        assert result.success is True
        assert result.source == "notion"
        assert result.rules_count == 10
        assert result.kind_breakdown == {"Finance": 5, "Business": 5}
        assert result.error is None

    def test_sync_result_to_dict(self):
        """Тест конвертации результата в словарь."""
        result = TagsSyncResult(success=False, source="yaml", rules_count=0, error="Test error")

        result_dict = result.to_dict()

        assert result_dict["success"] is False
        assert result_dict["source"] == "yaml"
        assert result_dict["rules_count"] == 0
        assert result_dict["error"] == "Test error"
        assert "timestamp" in result_dict


class TestUtilityFunctions:
    """Тесты для вспомогательных функций."""

    def test_calculate_kind_breakdown(self):
        """Тест подсчета breakdown по категориям."""
        rules = [
            {"tag": "Finance/IFRS"},
            {"tag": "Finance/Budget"},
            {"tag": "Business/Lavka"},
            {"tag": "People/Ivan"},
        ]

        breakdown = _calculate_kind_breakdown(rules)

        assert breakdown == {"Finance": 2, "Business": 1, "People": 1}

    def test_calculate_kind_breakdown_empty(self):
        """Тест подсчета для пустого списка."""
        assert _calculate_kind_breakdown([]) == {}

    def test_convert_notion_rules_to_yaml_format(self):
        """Тест конвертации правил из Notion в YAML формат."""
        notion_rules = [
            {
                "tag": "Finance/IFRS",
                "patterns": ["ifrs", "reporting"],
                "exclude": ["email"],
                "weight": 2.0,
            },
            {"tag": "Business/Lavka", "patterns": ["lavka"], "exclude": [], "weight": 1.0},
        ]

        yaml_format = _convert_notion_rules_to_yaml_format(notion_rules)

        expected = {
            "Finance/IFRS": {
                "patterns": ["ifrs", "reporting"],
                "exclude": ["email"],
                "weight": 2.0,
            },
            "Business/Lavka": {"patterns": ["lavka"], "exclude": [], "weight": 1.0},
        }

        assert yaml_format == expected


class TestCacheOperations:
    """Тесты для операций с кэшем."""

    def test_save_and_load_rules_cache(self):
        """Тест сохранения и загрузки кэша правил."""
        test_rules = [{"tag": "Finance/IFRS", "patterns": ["ifrs"], "weight": 1.0}]

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "test_rules.json"

            with patch("app.core.tags_notion_sync.RULES_CACHE_PATH", cache_path):
                # Сохраняем
                _save_rules_cache(test_rules)

                # Загружаем
                loaded_rules = _load_rules_cache()

                assert loaded_rules == test_rules

    def test_load_rules_cache_missing_file(self):
        """Тест загрузки несуществующего кэша."""
        with patch("app.core.tags_notion_sync.RULES_CACHE_PATH", Path("/nonexistent/path")):
            result = _load_rules_cache()
            assert result is None

    def test_load_rules_cache_invalid_format(self):
        """Тест загрузки кэша с неправильным форматом."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "invalid_cache.json"

            # Сохраняем неправильный формат
            with open(cache_path, "w") as f:
                json.dump({"invalid": "format"}, f)

            with patch("app.core.tags_notion_sync.RULES_CACHE_PATH", cache_path):
                result = _load_rules_cache()
                assert result is None


class TestSyncFunctions:
    """Тесты для функций синхронизации."""

    @patch("app.core.tags_notion_sync.fetch_tag_catalog")
    @patch("app.core.tags_notion_sync.validate_tag_catalog_access")
    def test_sync_from_notion_success(self, mock_validate, mock_fetch):
        """Тест успешной синхронизации из Notion."""
        # Мокаем данные
        mock_validate.return_value = True
        mock_fetch.return_value = [{"tag": "Finance/IFRS", "patterns": ["ifrs"], "weight": 1.0}]

        with (
            patch("app.core.tags_notion_sync._save_rules_cache"),
            patch("app.core.tags_notion_sync._save_sync_metadata"),
            patch("app.core.tagger_v1_scored._get_tagger") as mock_get_tagger,
        ):
            mock_tagger = MagicMock()
            mock_get_tagger.return_value = mock_tagger

            result = sync_from_notion()

            assert result.success is True
            assert result.source == "notion"
            assert result.rules_count == 1
            mock_tagger._load_and_compile_rules_from_dict.assert_called_once()

    @patch("app.core.tags_notion_sync.validate_tag_catalog_access")
    def test_sync_from_notion_not_accessible(self, mock_validate):
        """Тест синхронизации когда Notion недоступен."""
        mock_validate.return_value = False

        result = sync_from_notion()

        assert result.success is False
        assert result.source == "notion"
        assert "not accessible" in result.error

    @patch("app.core.tagger_v1_scored._get_tagger")
    def test_sync_from_yaml_success(self, mock_get_tagger):
        """Тест успешной синхронизации из YAML."""
        mock_tagger = MagicMock()
        mock_tagger.reload_rules.return_value = 5
        mock_tagger._compiled_rules = {"Finance/IFRS": {}, "Business/Lavka": {}}
        mock_get_tagger.return_value = mock_tagger

        with patch("app.core.tags_notion_sync._save_sync_metadata"):
            result = sync_from_yaml()

            assert result.success is True
            assert result.source == "yaml"
            assert result.rules_count == 5

    def test_sync_from_cache_no_cache(self):
        """Тест синхронизации из кэша когда кэш отсутствует."""
        with patch("app.core.tags_notion_sync._load_rules_cache", return_value=None):
            result = sync_from_cache()

            assert result.success is False
            assert result.source == "cache"
            assert "No cached rules" in result.error


class TestSmartSync:
    """Тесты для умной синхронизации."""

    def test_smart_sync_notion_priority(self):
        """Тест приоритета Notion в умной синхронизации."""
        with (
            patch("app.core.tags_notion_sync.settings.notion_sync_enabled", True),
            patch("app.core.tags_notion_sync.validate_tag_catalog_access", return_value=True),
            patch("app.core.tags_notion_sync.sync_from_notion") as mock_sync_notion,
        ):
            mock_sync_notion.return_value = TagsSyncResult(
                success=True, source="notion", rules_count=10
            )

            result = smart_sync()

            assert result.source == "notion"
            mock_sync_notion.assert_called_once_with(False)

    def test_smart_sync_yaml_fallback(self):
        """Тест fallback на YAML при недоступности Notion."""
        with (
            patch("app.core.tags_notion_sync.settings.notion_sync_enabled", True),
            patch("app.core.tags_notion_sync.settings.notion_sync_fallback_to_yaml", True),
            patch("app.core.tags_notion_sync.validate_tag_catalog_access", return_value=False),
            patch("app.core.tags_notion_sync.sync_from_yaml") as mock_sync_yaml,
        ):
            mock_sync_yaml.return_value = TagsSyncResult(success=True, source="yaml", rules_count=5)

            result = smart_sync()

            assert result.source == "yaml"
            mock_sync_yaml.assert_called_once()

    def test_smart_sync_cache_fallback(self):
        """Тест fallback на кэш при недоступности всех источников."""
        with (
            patch("app.core.tags_notion_sync.settings.notion_sync_enabled", False),
            patch("app.core.tags_notion_sync.settings.notion_sync_fallback_to_yaml", False),
            patch("app.core.tags_notion_sync.sync_from_cache") as mock_sync_cache,
        ):
            mock_sync_cache.return_value = TagsSyncResult(
                success=True, source="cache", rules_count=3
            )

            result = smart_sync()

            assert result.source == "cache"
            mock_sync_cache.assert_called_once()


class TestSyncStatus:
    """Тесты для статуса синхронизации."""

    def test_get_sync_status_never_synced(self):
        """Тест статуса когда синхронизация никогда не выполнялась."""
        with patch("app.core.tags_notion_sync._load_sync_metadata", return_value=None):
            status = get_sync_status()

            assert status["last_sync"] is None
            assert status["status"] == "never_synced"
            assert status["rules_count"] == 0

    def test_get_sync_status_with_metadata(self):
        """Тест статуса с сохраненными метаданными."""
        import time

        metadata = {
            "success": True,
            "source": "notion",
            "rules_count": 15,
            "kind_breakdown": {"Finance": 10, "Business": 5},
            "timestamp": time.time() - 3600,  # час назад
        }

        with patch("app.core.tags_notion_sync._load_sync_metadata", return_value=metadata):
            status = get_sync_status()

            assert status["status"] == "success"
            assert status["source"] == "notion"
            assert status["rules_count"] == 15
            assert status["hours_since_sync"] == pytest.approx(1.0, rel=0.1)
            # Не проверяем cache_available и notion_accessible из-за сложности мокинга
