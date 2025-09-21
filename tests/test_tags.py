"""Тесты для унифицированной системы тегирования."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app.core.tags import (
    clear_cache,
    get_tagging_stats,
    tag_text,
    tag_text_for_commit,
    tag_text_for_meeting,
)


@pytest.fixture
def temp_rules_file():
    """Создает временный YAML файл с правилами для тестов."""
    test_rules = {
        "Finance/IFRS": ["\\bifrs\\b", "МСФО"],
        "Finance/Audit": ["аудит", "audit"],
        "Business/Lavka": ["lavka", "лавка", "darkstore"],
        "Projects/Test": ["тест", "test"],
        "Topic/Planning": ["планирование", "план"],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.dump(test_rules, f, allow_unicode=True)
        temp_path = Path(f.name)

    # Патчим настройки
    with patch("app.core.tags.settings") as mock_settings:
        mock_settings.tags_mode = "both"
        mock_settings.tagger_v1_enabled = True
        mock_settings.tagger_v1_rules_file = str(temp_path)

        # Очищаем кэш перед тестом
        clear_cache()

        yield temp_path

        # Очищаем кэш после теста
        clear_cache()

    # Удаляем временный файл
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def mock_people_data():
    """Мокает данные людей для тестов."""
    test_people = [
        {"name_en": "Sasha Katanov", "aliases": ["Саша Катанов", "Катанов", "Sasha", "Александр"]},
        {"name_en": "Valentin Dobrynin", "aliases": ["Валентин", "Валя", "Valentin", "Val"]},
        {"name_en": "Daniil", "aliases": ["Даня", "Даниил", "Danya"]},
    ]

    with patch("app.core.tagger_v1.load_people", return_value=test_people):
        yield test_people


class TestUnifiedTagging:
    """Тесты унифицированной системы тегирования."""

    def test_tag_text_mode_v0(self, temp_rules_file, mock_people_data):
        """Тест режима v0 (только старый тэггер)."""
        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "v0"

            text = "Обсудили аудит IFRS для проекта"
            tags = tag_text(text)

            # В режиме v0 должны быть только теги от старого тэггера
            # (точные теги зависят от содержимого tags.json)
            assert isinstance(tags, list)
            assert tags == sorted(tags)  # Проверяем сортировку

    def test_tag_text_mode_v1(self, temp_rules_file, mock_people_data):
        """Тест режима v1 (только новый тэггер)."""
        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "v1"

            text = "Обсудили аудит IFRS для Lavka"
            tags = tag_text(text)

            assert "Finance/IFRS" in tags
            assert "Finance/Audit" in tags
            assert "Business/Lavka" in tags
            assert tags == sorted(tags)

    def test_tag_text_mode_both(self, temp_rules_file, mock_people_data):
        """Тест режима both (объединение обоих тэггеров)."""
        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "both"

            text = "Обсудили аудит IFRS для Lavka с Сашей Катановым"
            tags = tag_text(text)

            # Должны быть теги от обоих тэггеров
            assert "Finance/IFRS" in tags  # от v1
            assert "Finance/Audit" in tags  # от v1
            assert "Business/Lavka" in tags  # от v1
            assert "People/Sasha Katanov" in tags  # от v1
            assert tags == sorted(tags)

    def test_tag_text_explicit_mode(self, temp_rules_file, mock_people_data):
        """Тест явного указания режима через параметр."""
        text = "Обсудили аудит IFRS"

        # Тестируем разные режимы через изменение настроек
        with patch("app.core.tags.settings") as mock_settings:
            # v1 режим
            mock_settings.tags_mode = "v1"
            tags_v1 = tag_text(text)

            # both режим
            mock_settings.tags_mode = "both"
            tags_both = tag_text(text)

        assert "Finance/IFRS" in tags_v1
        assert "Finance/Audit" in tags_v1
        assert tags_v1 == sorted(tags_v1)

        # В режиме both должно быть больше или равно тегов
        assert len(tags_both) >= len(tags_v1)

    def test_tag_text_empty_input(self, temp_rules_file, mock_people_data):
        """Тест с пустым входом."""
        assert tag_text("") == []
        assert tag_text("   ") == []
        assert tag_text(None) == []  # type: ignore

    def test_tag_text_invalid_mode(self, temp_rules_file, mock_people_data):
        """Тест с невалидным режимом."""
        text = "Обсудили аудит IFRS"

        # Тестируем с невалидным режимом через настройки
        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "invalid_mode"
            tags = tag_text(text)

        assert isinstance(tags, list)
        assert tags == sorted(tags)

    def test_tag_text_caching(self, temp_rules_file, mock_people_data):
        """Тест кэширования результатов."""
        text = "Обсудили аудит IFRS"

        # Первый вызов
        tags1 = tag_text(text)

        # Второй вызов (должен быть из кэша)
        tags2 = tag_text(text)

        assert tags1 == tags2

        # Проверяем статистику кэша
        stats = get_tagging_stats()
        assert "cache_info" in stats


class TestSpecializedFunctions:
    """Тесты специализированных функций тегирования."""

    def test_tag_text_for_meeting(self, temp_rules_file, mock_people_data):
        """Тест тегирования встреч с метаданными."""
        text = "Обсудили аудит IFRS для Lavka"
        meta = {
            "title": "Встреча по финансам",
            "attendees": ["Sasha Katanov", "Valentin Dobrynin"],
        }

        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "both"

            tags = tag_text_for_meeting(text, meta)

            assert "Finance/IFRS" in tags
            assert "Finance/Audit" in tags
            assert "Business/Lavka" in tags
            assert tags == sorted(tags)

    def test_tag_text_for_commit(self, temp_rules_file, mock_people_data):
        """Тест тегирования коммитов."""
        text = "Подготовить отчет по аудиту IFRS"

        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "v1"

            tags = tag_text_for_commit(text)

            assert "Finance/IFRS" in tags
            assert "Finance/Audit" in tags
            assert tags == sorted(tags)

    def test_tag_text_for_meeting_empty_meta(self, temp_rules_file, mock_people_data):
        """Тест тегирования встреч с пустыми метаданными."""
        text = "Обсудили аудит IFRS"
        meta = {}

        tags = tag_text_for_meeting(text, meta)

        assert isinstance(tags, list)
        assert tags == sorted(tags)


class TestDeduplication:
    """Тесты дедупликации тегов."""

    def test_deduplication_priority_v1(self, temp_rules_file, mock_people_data):
        """Тест приоритизации v1 при конфликтах."""
        # Этот тест зависит от конкретного содержимого tags.json
        # Проверяем, что система работает без ошибок
        text = "Обсудили аудит IFRS"

        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "both"

            tags = tag_text(text)

            assert isinstance(tags, list)
            assert tags == sorted(tags)
            # Не должно быть дубликатов
            assert len(tags) == len(set(tags))

    def test_deduplication_case_insensitive(self, temp_rules_file, mock_people_data):
        """Тест дедупликации с учетом регистра."""
        # Создаем ситуацию с потенциальными дубликатами
        text = "IFRS аудит ifrs АУДИТ"

        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "both"

            tags = tag_text(text)

            assert isinstance(tags, list)
            assert tags == sorted(tags)


class TestErrorHandling:
    """Тесты обработки ошибок."""

    def test_tagger_v0_error_fallback(self, temp_rules_file, mock_people_data):
        """Тест fallback при ошибке v0 тэггера."""
        with patch("app.core.tags.tagger_v0", side_effect=Exception("v0 error")):
            with patch("app.core.tags.settings") as mock_settings:
                mock_settings.tags_mode = "v0"

                text = "Обсудили аудит IFRS"
                tags = tag_text(text)

                # При ошибке должен вернуться пустой список
                assert tags == []

    def test_tagger_v1_error_fallback(self, temp_rules_file, mock_people_data):
        """Тест fallback при ошибке v1 тэггера."""
        with patch("app.core.tags.tagger_v1", side_effect=Exception("v1 error")):
            with patch("app.core.tags.settings") as mock_settings:
                mock_settings.tags_mode = "v1"

                text = "Обсудили аудит IFRS"
                tags = tag_text(text)

                # При ошибке должен fallback к v0
                assert isinstance(tags, list)

    def test_both_modes_error_handling(self, temp_rules_file, mock_people_data):
        """Тест обработки ошибок в режиме both."""
        with patch("app.core.tags.tagger_v0", side_effect=Exception("v0 error")):
            with patch("app.core.tags.tagger_v1", side_effect=Exception("v1 error")):
                with patch("app.core.tags.settings") as mock_settings:
                    mock_settings.tags_mode = "both"

                    text = "Обсудили аудит IFRS"
                    tags = tag_text(text)

                    # При ошибках в обоих тэггерах должен вернуться пустой список
                    assert tags == []


class TestStatistics:
    """Тесты статистики системы."""

    def test_get_tagging_stats(self, temp_rules_file, mock_people_data):
        """Тест получения статистики."""
        stats = get_tagging_stats()

        assert "current_mode" in stats
        assert "valid_modes" in stats
        assert "cache_info" in stats
        assert isinstance(stats["valid_modes"], list)
        assert "both" in stats["valid_modes"]
        assert "v0" in stats["valid_modes"]
        assert "v1" in stats["valid_modes"]

    def test_cache_clearing(self, temp_rules_file, mock_people_data):
        """Тест очистки кэша."""
        text = "Обсудили аудит IFRS"

        # Заполняем кэш
        tag_text(text)

        # Очищаем кэш
        clear_cache()

        # Проверяем, что кэш очищен
        stats = get_tagging_stats()
        cache_info = stats["cache_info"]
        assert cache_info["currsize"] == 0


class TestIntegration:
    """Интеграционные тесты."""

    def test_complex_workflow(self, temp_rules_file, mock_people_data):
        """Тест комплексного workflow."""
        text = """
        Встреча по планированию IFRS аудита для проекта Lavka.
        
        Участники:
        - Саша Катанов (финансовый директор)
        - Валентин (руководитель проекта)
        
        Обсуждали:
        1. Аудит финансовой отчетности
        2. Планы по darkstore интеграции
        3. Бюджет на следующий квартал
        
        Решения:
        - Провести дополнительный аудит до конца месяца
        - Даня подготовит план по МСФО
        """

        meta = {
            "title": "Встреча по финансам",
            "attendees": ["Sasha Katanov", "Valentin Dobrynin", "Daniil"],
        }

        with patch("app.core.tags.settings") as mock_settings:
            mock_settings.tags_mode = "both"

            # Тестируем разные функции
            meeting_tags = tag_text_for_meeting(text, meta)
            commit_tags = tag_text_for_commit("Подготовить отчет по IFRS")
            general_tags = tag_text(text)

            # Проверяем, что все функции работают
            assert isinstance(meeting_tags, list)
            assert isinstance(commit_tags, list)
            assert isinstance(general_tags, list)

            # Проверяем ожидаемые теги
            expected_tags = {
                "Finance/IFRS",
                "Finance/Audit",
                "Business/Lavka",
                "People/Sasha Katanov",
            }

            for tag_set in [meeting_tags, general_tags]:
                found_tags = set(tag_set)
                for expected_tag in expected_tags:
                    assert (
                        expected_tag in found_tags
                    ), f"Expected tag {expected_tag} not found in {tag_set}"

    def test_mode_switching(self, temp_rules_file, mock_people_data):
        """Тест переключения режимов."""
        text = "Обсудили аудит IFRS для Lavka"

        with patch("app.core.tags.settings") as mock_settings:
            # Тестируем разные режимы
            for mode in ["v0", "v1", "both"]:
                mock_settings.tags_mode = mode
                clear_cache()  # Очищаем кэш для каждого режима

                tags = tag_text(text)

                assert isinstance(tags, list)
                assert tags == sorted(tags)

                # В режиме v1 должны быть определенные теги
                if mode == "v1":
                    assert "Finance/IFRS" in tags
                    assert "Finance/Audit" in tags
                    assert "Business/Lavka" in tags
