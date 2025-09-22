"""Тесты для валидатора YAML правил тегирования."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app.core.tagger_v1_scored import validate_rules


@pytest.fixture
def valid_yaml_file():
    """Создает валидный YAML файл для тестов."""
    valid_rules = {
        "Finance/IFRS": {
            "patterns": ["\\bifrs\\b", "МСФО"],
            "exclude": ["@ifrs"],
            "weight": 1.2,
        },
        "Finance/Audit": {
            "patterns": ["аудит", "audit"],
            "weight": 1.0,
        },
        "Topic/Planning": ["планирование", "план"],  # Старый формат
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.dump(valid_rules, f, allow_unicode=True)
        temp_path = Path(f.name)

    yield temp_path

    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def invalid_yaml_file():
    """Создает невалидный YAML файл для тестов."""
    invalid_rules = {
        "Finance/IFRS": {
            "patterns": ["[invalid regex"],  # Битый regex
            "weight": 15.0,  # Неправильный вес
        },
        "InvalidTag": {  # Без категории
            "patterns": ["test"],
        },
        "Finance/Duplicate1": ["pattern1"],
        "Finance/Duplicate2": ["pattern2"],  # Переименованный для теста
        "Finance/Empty": {
            "patterns": [],  # Пустые паттерны
        },
        "Finance/BadTypes": {
            "patterns": "not_a_list",  # Неправильный тип
            "exclude": 123,  # Неправильный тип
            "weight": "not_a_number",  # Неправильный тип
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.dump(invalid_rules, f, allow_unicode=True)
        temp_path = Path(f.name)

    yield temp_path

    if temp_path.exists():
        temp_path.unlink()


class TestYamlValidator:
    """Тесты валидатора YAML."""

    def test_validate_valid_yaml(self, valid_yaml_file):
        """Тест валидации корректного YAML."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_rules_file = str(valid_yaml_file)

            errors = validate_rules()
            assert errors == []

    def test_validate_invalid_yaml(self, invalid_yaml_file):
        """Тест валидации некорректного YAML."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_rules_file = str(invalid_yaml_file)

            errors = validate_rules()
            assert len(errors) > 0

            # Проверяем специфические ошибки
            error_text = " ".join(errors)
            assert "Invalid regex" in error_text  # Битый regex
            assert "Weight must be" in error_text  # Неправильный вес
            assert "category/subcategory" in error_text  # Формат тега
            assert "No patterns" in error_text  # Пустые паттерны
            # Не проверяем дубликаты, так как Python автоматически их убирает

    def test_validate_missing_file(self):
        """Тест валидации отсутствующего файла."""
        with patch("app.core.tagger_v1_scored.settings") as mock_settings:
            mock_settings.tagger_v1_rules_file = "/nonexistent/file.yaml"

            errors = validate_rules()
            assert len(errors) == 1
            assert "not found" in errors[0]

    def test_validate_invalid_yaml_syntax(self):
        """Тест валидации файла с невалидным YAML синтаксисом."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: syntax: [")
            invalid_syntax_path = f.name

        try:
            with patch("app.core.tagger_v1_scored.settings") as mock_settings:
                mock_settings.tagger_v1_rules_file = invalid_syntax_path

                errors = validate_rules()
                assert len(errors) > 0
                assert any("Error validating rules" in error for error in errors)

        finally:
            Path(invalid_syntax_path).unlink()

    def test_validate_non_dict_yaml(self):
        """Тест валидации YAML, который не является словарем."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(["not", "a", "dict"], f)
            non_dict_path = f.name

        try:
            with patch("app.core.tagger_v1_scored.settings") as mock_settings:
                mock_settings.tagger_v1_rules_file = non_dict_path

                errors = validate_rules()
                assert len(errors) == 1
                assert "must be a dictionary" in errors[0]

        finally:
            Path(non_dict_path).unlink()

    def test_validate_performance_warnings(self):
        """Тест предупреждений о производительности."""
        # Создаем YAML с большим количеством паттернов
        many_patterns = {
            f"Test/Tag{i}": {
                "patterns": [f"pattern{j}" for j in range(50)],  # 50 паттернов на тег
                "exclude": [f"exclude{j}" for j in range(10)],  # 10 исключений на тег
            }
            for i in range(15)  # 15 тегов = 750 паттернов, 150 исключений
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(many_patterns, f)
            many_patterns_path = f.name

        try:
            with patch("app.core.tagger_v1_scored.settings") as mock_settings:
                mock_settings.tagger_v1_rules_file = many_patterns_path

                errors = validate_rules()

                # Должны быть предупреждения о производительности
                warning_errors = [e for e in errors if "WARNING" in e]
                assert len(warning_errors) >= 1
                assert any("Too many patterns" in e for e in warning_errors)

        finally:
            Path(many_patterns_path).unlink()

    def test_validate_weight_bounds(self):
        """Тест валидации границ весов."""
        weight_test_rules = {
            "Test/NegativeWeight": {
                "patterns": ["test"],
                "weight": -1.0,  # Отрицательный вес
            },
            "Test/TooHighWeight": {
                "patterns": ["test"],
                "weight": 15.0,  # Слишком большой вес
            },
            "Test/ValidWeight": {
                "patterns": ["test"],
                "weight": 5.0,  # Валидный вес
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(weight_test_rules, f)
            weight_test_path = f.name

        try:
            with patch("app.core.tagger_v1_scored.settings") as mock_settings:
                mock_settings.tagger_v1_rules_file = weight_test_path

                errors = validate_rules()

                # Должны быть ошибки для неправильных весов
                weight_errors = [e for e in errors if "Weight must be" in e]
                assert len(weight_errors) >= 2  # Для отрицательного и слишком большого

        finally:
            Path(weight_test_path).unlink()

    def test_validate_empty_patterns_and_excludes(self):
        """Тест валидации пустых паттернов и исключений."""
        empty_rules = {
            "Test/EmptyPattern": {
                "patterns": ["", "  ", "valid"],  # Пустые строки
                "exclude": ["", "valid_exclude"],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(empty_rules, f)
            empty_path = f.name

        try:
            with patch("app.core.tagger_v1_scored.settings") as mock_settings:
                mock_settings.tagger_v1_rules_file = empty_path

                errors = validate_rules()

                # Должны быть ошибки для пустых паттернов
                empty_errors = [e for e in errors if "Empty" in e]
                assert len(empty_errors) >= 2  # Для pattern и exclude

        finally:
            Path(empty_path).unlink()


class TestValidatorIntegration:
    """Интеграционные тесты валидатора."""

    def test_validator_with_real_rules_file(self):
        """Тест валидатора с реальным файлом правил."""
        # Используем реальный файл правил проекта
        errors = validate_rules()

        # Реальный файл должен быть валидным
        assert isinstance(errors, list)
        # Если есть ошибки, они должны быть только предупреждениями
        critical_errors = [e for e in errors if not e.startswith("WARNING")]
        assert len(critical_errors) == 0

    def test_validator_error_handling(self):
        """Тест обработки ошибок валидатора."""
        with patch("app.core.tagger_v1_scored._get_tagger", side_effect=Exception("Tagger error")):
            errors = validate_rules()

            assert len(errors) >= 1
            assert any("Error validating rules" in error for error in errors)
