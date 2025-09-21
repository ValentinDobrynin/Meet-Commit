"""Тесты для тэггера v1 с YAML правилами."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app.core.tagger_v1 import (
    clear_cache,
    get_rules_stats,
    tag_text,
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
    with patch("app.core.tagger_v1.settings") as mock_settings:
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


class TestTaggerV1:
    """Тесты для тэггера v1."""

    def test_tag_text_basic_rules(self, temp_rules_file, mock_people_data):
        """Тест базового тегирования по YAML правилам."""
        text = "Обсудили аудит IFRS для нового проекта"
        tags = tag_text(text)

        assert "Finance/IFRS" in tags
        assert "Finance/Audit" in tags
        # Проверяем сортировку
        assert tags == sorted(tags)

    def test_tag_text_people_detection(self, temp_rules_file, mock_people_data):
        """Тест детекции людей."""
        text = "Саша Катанов подтвердил план. Валентин согласился."
        tags = tag_text(text)

        assert "People/Sasha Katanov" in tags
        assert "People/Valentin Dobrynin" in tags
        assert "Topic/Planning" in tags  # "план"

    def test_tag_text_case_insensitive(self, temp_rules_file, mock_people_data):
        """Тест нечувствительности к регистру."""
        text = "АУДИТ ifrs LAVKA"
        tags = tag_text(text)

        assert "Finance/Audit" in tags
        assert "Finance/IFRS" in tags
        assert "Business/Lavka" in tags

    def test_tag_text_regex_patterns(self, temp_rules_file, mock_people_data):
        """Тест работы регулярных выражений."""
        # Тест word boundary для IFRS
        text1 = "ifrs отчетность"  # должно сработать
        text2 = "rifrs система"  # не должно сработать из-за \\b

        tags1 = tag_text(text1)
        tags2 = tag_text(text2)

        assert "Finance/IFRS" in tags1
        assert "Finance/IFRS" not in tags2

    def test_tag_text_empty_input(self, temp_rules_file, mock_people_data):
        """Тест с пустым входом."""
        assert tag_text("") == []
        assert tag_text("   ") == []
        assert tag_text(None) == []  # type: ignore

    def test_tag_text_no_matches(self, temp_rules_file, mock_people_data):
        """Тест с текстом без совпадений."""
        text = "Обычный текст без ключевых слов"
        tags = tag_text(text)

        assert tags == []

    def test_tag_text_multiple_patterns_same_tag(self, temp_rules_file, mock_people_data):
        """Тест что несколько паттернов одного тега дают один тег."""
        text = "Обсудили аудит и audit процессы"
        tags = tag_text(text)

        # Должен быть только один тег Finance/Audit, не два
        audit_tags = [t for t in tags if t == "Finance/Audit"]
        assert len(audit_tags) == 1

    def test_tag_text_people_deduplication(self, temp_rules_file, mock_people_data):
        """Тест дедупликации людей по разным алиасам."""
        text = "Саша Катанов и Катанов обсудили с Sasha план"
        tags = tag_text(text)

        # Должен быть только один тег для Саши, не три
        sasha_tags = [t for t in tags if "Sasha Katanov" in t]
        assert len(sasha_tags) == 1
        assert "People/Sasha Katanov" in tags

    def test_disabled_tagger(self, temp_rules_file, mock_people_data):
        """Тест отключенного тэггера."""
        with patch("app.core.tagger_v1.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = False
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            clear_cache()  # Очищаем кэш для применения новых настроек

            text = "Обсудили аудит IFRS"
            tags = tag_text(text)

            assert tags == []


class TestRulesLoading:
    """Тесты загрузки правил."""

    def test_get_rules_stats(self, temp_rules_file, mock_people_data):
        """Тест получения статистики правил."""
        stats = get_rules_stats()

        assert stats["total_tags"] == 5
        assert stats["total_patterns"] > 0
        assert stats["compiled_patterns"] > 0
        assert "Finance" in stats["categories"]
        assert "Business" in stats["categories"]
        assert stats["enabled"] is True

    def test_invalid_yaml_file(self, mock_people_data):
        """Тест обработки некорректного YAML файла."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("invalid: yaml: content: [")
            temp_path = Path(f.name)

        try:
            with patch("app.core.tagger_v1.settings") as mock_settings:
                mock_settings.tagger_v1_enabled = True
                mock_settings.tagger_v1_rules_file = str(temp_path)

                clear_cache()

                # Должен вернуть пустой список без ошибок
                tags = tag_text("test text")
                assert tags == []

        finally:
            temp_path.unlink()

    def test_missing_rules_file(self, mock_people_data):
        """Тест отсутствующего файла правил."""
        with patch("app.core.tagger_v1.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = "/nonexistent/path.yaml"

            clear_cache()

            # Должен вернуть пустой список без ошибок
            tags = tag_text("test text")
            assert tags == []

    def test_invalid_regex_patterns(self, mock_people_data):
        """Тест обработки некорректных regex паттернов."""
        invalid_rules = {
            "Test/Invalid": ["[invalid regex", "valid_pattern"],
            "Test/Valid": ["valid_pattern"],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(invalid_rules, f)
            temp_path = Path(f.name)

        try:
            with patch("app.core.tagger_v1.settings") as mock_settings:
                mock_settings.tagger_v1_enabled = True
                mock_settings.tagger_v1_rules_file = str(temp_path)

                clear_cache()

                # Должен работать с валидными паттернами, игнорируя невалидные
                tags = tag_text("valid_pattern test")
                assert "Test/Valid" in tags
                # Test/Invalid может быть или не быть в зависимости от обработки ошибок

        finally:
            temp_path.unlink()


class TestIntegration:
    """Интеграционные тесты."""

    def test_complex_text_analysis(self, temp_rules_file, mock_people_data):
        """Тест комплексного анализа реального текста."""
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

        tags = tag_text(text)

        # Проверяем ожидаемые теги
        expected_tags = {
            "Finance/IFRS",
            "Finance/Audit",
            "Business/Lavka",
            "Topic/Planning",
            "People/Sasha Katanov",
            "People/Valentin Dobrynin",
            "People/Daniil",
        }

        found_tags = set(tags)

        # Проверяем, что все ожидаемые теги найдены
        for expected_tag in expected_tags:
            assert expected_tag in found_tags, f"Expected tag {expected_tag} not found in {tags}"

        # Проверяем, что теги отсортированы
        assert tags == sorted(tags)

    def test_performance_with_large_text(self, temp_rules_file, mock_people_data):
        """Тест производительности с большим текстом."""
        # Создаем большой текст
        large_text = "Обсудили аудит IFRS. " * 1000

        # Должно работать быстро и без ошибок
        tags = tag_text(large_text)

        assert "Finance/IFRS" in tags
        assert "Finance/Audit" in tags
        assert len(tags) >= 2
