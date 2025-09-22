"""Тесты для scored версии tagger_v1."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app.core.tagger_v1_scored import (
    TaggerV1Scored,
    TagRule,
    get_rules_stats,
    reload_rules,
    tag_text,
    tag_text_scored,
)


@pytest.fixture
def temp_rules_file():
    """Создает временный YAML файл с правилами для тестов."""
    test_rules = {
        "Finance/IFRS": {
            "patterns": ["\\bifrs\\b", "МСФО"],
            "exclude": ["@ifrs", "ifrs\\.com"],
            "weight": 1.2,
        },
        "Finance/Audit": {
            "patterns": ["аудит", "audit"],
            "exclude": ["audio"],
            "weight": 1.0,
        },
        "Business/Lavka": {
            "patterns": ["lavka", "лавка", "darkstore"],
            "weight": 0.8,
        },
        "Projects/Test": {
            "patterns": ["тест", "test"],
            "weight": 1.5,
        },
        # Старый формат для совместимости
        "Topic/Planning": ["планирование", "план"],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.dump(test_rules, f, allow_unicode=True)
        temp_path = Path(f.name)

    yield temp_path

    # Очистка
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def mock_people_data():
    """Мокает данные людей для тестов."""
    test_people = [
        {"name_en": "Sasha Katanov", "aliases": ["Саша Катанов", "Катанов", "Sasha"]},
        {"name_en": "Valentin Dobrynin", "aliases": ["Валентин", "Валя", "Valentin"]},
        {"name_en": "Daniil", "aliases": ["Даня", "Даниил", "Danya"]},
    ]

    with patch("app.core.tagger_v1_scored.load_people", return_value=test_people):
        yield test_people


class TestTagRule:
    """Тесты модели TagRule."""

    def test_valid_rule(self):
        """Тест валидного правила."""
        rule = TagRule(patterns=["test", "\\btest\\b"], exclude=["testing"], weight=1.5)
        assert rule.patterns == ["test", "\\btest\\b"]
        assert rule.exclude == ["testing"]
        assert rule.weight == 1.5

    def test_default_values(self):
        """Тест значений по умолчанию."""
        rule = TagRule(patterns=["test"])
        assert rule.patterns == ["test"]
        assert rule.exclude == []
        assert rule.weight == 1.0

    def test_invalid_regex_pattern(self):
        """Тест невалидного regex паттерна."""
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            TagRule(patterns=["[invalid"])

    def test_weight_validation(self):
        """Тест валидации веса."""
        with pytest.raises(ValueError):
            TagRule(patterns=["test"], weight=-1.0)

        with pytest.raises(ValueError):
            TagRule(patterns=["test"], weight=11.0)


class TestTaggerV1Scored:
    """Тесты основного класса TaggerV1Scored."""

    def test_initialization(self, temp_rules_file, mock_people_data):
        """Тест инициализации тэггера."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)
            mock_settings.tags_min_score = 0.5

            tagger = TaggerV1Scored()

            assert len(tagger._compiled_rules) > 0
            assert tagger._stats.total_rules > 0

    def test_normalize_yaml_format_new(self, temp_rules_file):
        """Тест нормализации нового формата YAML."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()

            # Проверяем, что правила загрузились
            assert "Finance/IFRS" in tagger._compiled_rules
            assert "Finance/Audit" in tagger._compiled_rules

            # Проверяем веса
            ifrs_rule = tagger._compiled_rules["Finance/IFRS"]
            assert ifrs_rule.weight == 1.2

    def test_normalize_yaml_format_old(self):
        """Тест нормализации старого формата YAML."""
        old_format = {"Topic/Test": ["test", "testing"]}

        tagger = TaggerV1Scored()
        normalized = tagger._normalize_yaml_format(old_format)

        assert "Topic/Test" in normalized
        rule = normalized["Topic/Test"]
        assert rule.patterns == ["test", "testing"]
        assert rule.exclude == []
        assert rule.weight == 1.0

    def test_tag_text_scored_basic(self, temp_rules_file, mock_people_data):
        """Тест базового scoring."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()

            text = "Обсудили аудит IFRS для проекта. Саша Катанов участвовал."
            scored = tagger.tag_text_scored(text)

            # Проверяем, что теги найдены
            tags_dict = dict(scored)
            assert "Finance/IFRS" in tags_dict
            assert "Finance/Audit" in tags_dict
            assert "People/Sasha Katanov" in tags_dict

            # Проверяем веса
            assert tags_dict["Finance/IFRS"] == 1.2  # weight 1.2 * 1 hit
            assert tags_dict["Finance/Audit"] == 1.0  # weight 1.0 * 1 hit
            assert tags_dict["People/Sasha Katanov"] == 1.0  # люди всегда 1.0

    def test_tag_text_scored_multiple_hits(self, temp_rules_file, mock_people_data):
        """Тест множественных совпадений."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()

            text = "IFRS аудит и еще раз IFRS для проверки"
            scored = tagger.tag_text_scored(text)

            tags_dict = dict(scored)
            # IFRS встречается 2 раза: weight 1.2 * 2 = 2.4
            assert tags_dict["Finance/IFRS"] == 2.4

    def test_tag_text_scored_exclusions(self, temp_rules_file, mock_people_data):
        """Тест исключающих паттернов."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()

            # Текст с исключением
            text = "Контакт: support@ifrs.com для вопросов по IFRS"
            scored = tagger.tag_text_scored(text)

            # IFRS должен быть исключен из-за @ifrs в exclude
            tags_dict = dict(scored)
            assert "Finance/IFRS" not in tags_dict

    def test_tag_text_with_threshold(self, temp_rules_file, mock_people_data):
        """Тест фильтрации по порогу."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)
            mock_settings.tags_min_score = 1.0

            tagger = TaggerV1Scored()

            text = "Обсудили lavka проект"  # weight 0.8, не пройдет порог 1.0
            filtered_tags = tagger.tag_text(text)

            assert "Business/Lavka" not in filtered_tags

    def test_disabled_tagger(self, temp_rules_file, mock_people_data):
        """Тест отключенного тэггера."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = False
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()

            text = "Обсудили IFRS аудит"
            result = tagger.tag_text_scored(text)

            assert result == []

    def test_empty_text(self, temp_rules_file, mock_people_data):
        """Тест пустого текста."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()

            assert tagger.tag_text_scored("") == []
            assert tagger.tag_text_scored("   ") == []
            assert tagger.tag_text("") == []

    def test_reload_rules(self, temp_rules_file, mock_people_data):
        """Тест перезагрузки правил."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()
            initial_count = len(tagger._compiled_rules)

            # Перезагружаем
            reloaded_count = tagger.reload_rules()

            assert reloaded_count == initial_count
            assert len(tagger._compiled_rules) == initial_count

    def test_get_stats(self, temp_rules_file, mock_people_data):
        """Тест получения детальной статистики."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()
            stats = tagger.get_stats()

            # Проверяем основные поля
            assert "total_rules" in stats
            assert "total_patterns" in stats
            assert "total_excludes" in stats
            assert "average_weight" in stats
            assert stats["total_rules"] > 0

            # Проверяем новые метрики производительности
            assert "total_calls" in stats
            assert "total_tags_found" in stats
            assert "avg_score" in stats
            assert "top_tags" in stats
            assert "performance_ms" in stats
            assert "cache_hit_rate" in stats
            assert "total_unique_tags" in stats
            assert "most_frequent_tag" in stats
            assert "performance_samples" in stats

            # Проверяем типы
            assert isinstance(stats["total_calls"], int)
            assert isinstance(stats["total_tags_found"], int)
            assert isinstance(stats["avg_score"], float)
            assert isinstance(stats["top_tags"], list)
            assert isinstance(stats["performance_ms"], float)
            assert isinstance(stats["cache_hit_rate"], float)
            assert isinstance(stats["total_unique_tags"], int)
            assert isinstance(stats["performance_samples"], int)

    def test_performance_metrics(self, temp_rules_file, mock_people_data):
        """Тест метрик производительности."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            tagger = TaggerV1Scored()

            # Изначально метрики должны быть нулевыми
            stats = tagger.get_stats()
            assert stats["total_calls"] == 0
            assert stats["total_tags_found"] == 0
            assert stats["avg_score"] == 0.0
            assert stats["performance_ms"] == 0.0

            # Выполняем тегирование
            tagger.tag_text_scored("Обсудили IFRS аудит и планирование")

            # Проверяем, что метрики обновились
            stats = tagger.get_stats()
            assert stats["total_calls"] == 1
            assert stats["total_tags_found"] > 0
            assert stats["avg_score"] > 0.0
            assert stats["performance_ms"] > 0.0
            assert stats["total_unique_tags"] > 0
            assert stats["performance_samples"] == 1

            # Выполняем еще одно тегирование
            tagger.tag_text_scored("Тест lavka и darkstore")

            # Проверяем накопление метрик
            stats = tagger.get_stats()
            assert stats["total_calls"] == 2
            assert stats["total_tags_found"] > 0
            assert stats["performance_samples"] == 2


class TestPublicAPI:
    """Тесты публичного API."""

    def test_tag_text_scored_api(self, temp_rules_file, mock_people_data):
        """Тест публичной функции tag_text_scored."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)
            mock_settings.tags_min_score = 0.5

            text = "Обсудили IFRS аудит"
            scored = tag_text_scored(text)

            assert len(scored) > 0
            assert all(isinstance(item, tuple) and len(item) == 2 for item in scored)
            assert all(isinstance(score, float) for _, score in scored)

    def test_tag_text_api(self, temp_rules_file, mock_people_data):
        """Тест публичной функции tag_text."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)
            mock_settings.tags_min_score = 0.5

            text = "Обсудили IFRS аудит"
            tags = tag_text(text)

            assert isinstance(tags, list)
            assert all(isinstance(tag, str) for tag in tags)
            assert len(tags) > 0

    def test_reload_rules_api(self, temp_rules_file):
        """Тест публичной функции reload_rules."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            count = reload_rules()
            assert isinstance(count, int)
            assert count > 0

    def test_get_rules_stats_api(self, temp_rules_file):
        """Тест публичной функции get_rules_stats."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)

            stats = get_rules_stats()
            assert isinstance(stats, dict)
            assert "total_rules" in stats


class TestErrorHandling:
    """Тесты обработки ошибок."""

    def test_missing_rules_file(self, mock_people_data):
        """Тест отсутствующего файла правил."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = "/nonexistent/file.yaml"

            tagger = TaggerV1Scored()

            # Должен работать с пустыми правилами
            assert len(tagger._compiled_rules) == 0
            assert tagger.tag_text_scored("test text") == []

    def test_invalid_yaml_file(self, mock_people_data):
        """Тест невалидного YAML файла."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            invalid_yaml_path = f.name

        try:
            with patch("app.core.tagger_v1_scored.settings") as mock_settings:
                mock_settings.tagger_v1_enabled = True
                mock_settings.tagger_v1_rules_file = invalid_yaml_path

                tagger = TaggerV1Scored()

                # Должен работать с пустыми правилами при ошибке
                assert len(tagger._compiled_rules) == 0

        finally:
            Path(invalid_yaml_path).unlink()

    def test_invalid_regex_in_rules(self, mock_people_data):
        """Тест невалидных regex в правилах."""
        invalid_rules = {"Test/Invalid": {"patterns": ["[invalid", "valid"], "weight": 1.0}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(invalid_rules, f)
            temp_path = f.name

        try:
            with patch("app.core.tagger_v1_scored.settings") as mock_settings:
                mock_settings.tagger_v1_enabled = True
                mock_settings.tagger_v1_rules_file = temp_path

                tagger = TaggerV1Scored()

                # Правило должно быть пропущено из-за невалидного regex
                assert "Test/Invalid" not in tagger._compiled_rules

        finally:
            Path(temp_path).unlink()


class TestIntegration:
    """Интеграционные тесты."""

    def test_complex_workflow(self, temp_rules_file, mock_people_data):
        """Тест сложного workflow."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_enabled = True
            mock_settings.tagger_v1_rules_file = str(temp_rules_file)
            mock_settings.tags_min_score = 0.5

            text = """
            Встреча по планированию IFRS аудита для проекта Lavka.
            
            Участники:
            - Саша Катанов (финансовый директор)
            - Валентин (руководитель проекта)
            
            Обсуждали:
            1. Аудит финансовой отчетности
            2. Планы по darkstore интеграции
            3. Тестирование системы
            
            Решения:
            - Провести дополнительный аудит до конца месяца
            - Даня подготовит план по МСФО
            """

            # Тест scored версии
            scored = tag_text_scored(text)
            scored_dict = dict(scored)

            # Проверяем основные теги
            assert "Finance/IFRS" in scored_dict
            assert "Finance/Audit" in scored_dict
            assert "Business/Lavka" in scored_dict
            assert "Projects/Test" in scored_dict
            assert "People/Sasha Katanov" in scored_dict
            assert "People/Valentin Dobrynin" in scored_dict
            assert "People/Daniil" in scored_dict

            # Проверяем scoring
            assert scored_dict["Finance/IFRS"] >= 1.2  # минимум 1 hit с weight 1.2
            assert scored_dict["Projects/Test"] >= 1.5  # минимум 1 hit с weight 1.5

            # Тест фильтрованной версии
            filtered = tag_text(text)
            assert len(filtered) > 0
            assert all(tag in scored_dict for tag in filtered)

            # Проверяем алфавитную сортировку в filtered версии
            assert filtered == sorted(filtered)
