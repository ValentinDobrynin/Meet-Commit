"""Тесты для app.tools.people_miner"""

import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.people_miner import (
    _already_known_aliases_lower,
    _clear_candidates,
    _print_stats,
)


@pytest.fixture
def temp_dict_dir():
    """Создает временную директорию для словарей."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Патчим все пути к файлам
        people_file = temp_path / "people.json"
        candidates_file = temp_path / "people_candidates.json"
        stopwords_file = temp_path / "people_stopwords.json"

        with (
            patch("app.core.people_store.DICT_DIR", temp_path),
            patch("app.core.people_store.PEOPLE", people_file),
            patch("app.core.people_store.CAND", candidates_file),
            patch("app.core.people_store.STOPS", stopwords_file),
        ):
            yield temp_path


@pytest.fixture
def mock_test_data(temp_dict_dir):
    """Создает тестовые данные."""
    # Создаем основной словарь людей
    people_data = {
        "people": [
            {"name_en": "John Doe", "aliases": ["John", "Johnny", "Джон"]},
            {"name_en": "Jane Smith", "aliases": ["Jane", "Джейн"]},
        ]
    }
    people_file = temp_dict_dir / "people.json"
    with open(people_file, "w", encoding="utf-8") as f:
        json.dump(people_data, f)

    # Создаем кандидатов
    candidates_data = {"candidates": {"Alice": 5, "Bob": 2, "Charlie": 1}}
    candidates_file = temp_dict_dir / "people_candidates.json"
    with open(candidates_file, "w", encoding="utf-8") as f:
        json.dump(candidates_data, f)

    return temp_dict_dir


def test_already_known_aliases_lower(mock_test_data):
    """Тест получения известных алиасов в нижнем регистре."""
    from app.core.people_store import load_people

    people = load_people()
    known = _already_known_aliases_lower(people)

    expected = {
        "john",
        "johnny",
        "джон",
        "john doe",  # из первой записи
        "jane",
        "джейн",
        "jane smith",  # из второй записи
    }
    assert known == expected


def test_already_known_aliases_lower_empty():
    """Тест получения алиасов из пустого списка людей."""
    known = _already_known_aliases_lower([])
    assert known == set()


def test_print_stats_empty(temp_dict_dir):
    """Тест вывода статистики для пустых данных."""
    with patch("sys.stdout", new=StringIO()) as fake_out:
        _print_stats()
        output = fake_out.getvalue()

    assert "Всего кандидатов: 0" in output
    assert "Людей в основном словаре: 0" in output


def test_print_stats_with_data(mock_test_data):
    """Тест вывода статистики с данными."""
    with patch("sys.stdout", new=StringIO()) as fake_out:
        _print_stats()
        output = fake_out.getvalue()

    assert "Всего кандидатов: 3" in output
    assert "Максимальная частота: 5" in output
    assert "Минимальная частота: 1" in output
    assert "Средняя частота: 2." in output  # Проверяем начало числа
    assert "Людей в основном словаре: 2" in output


def test_clear_candidates_empty(temp_dict_dir):
    """Тест очистки пустого словаря кандидатов."""
    with patch("sys.stdout", new=StringIO()) as fake_out:
        _clear_candidates()
        output = fake_out.getvalue()

    assert "Словарь кандидатов уже пуст" in output


def test_clear_candidates_with_confirmation(mock_test_data):
    """Тест очистки кандидатов с подтверждением."""
    with patch("builtins.input", return_value="yes"):
        with patch("sys.stdout", new=StringIO()) as fake_out:
            _clear_candidates()
            output = fake_out.getvalue()

    assert "Вы собираетесь удалить 3 кандидатов" in output
    assert "Словарь кандидатов очищен" in output

    # Проверяем, что кандидаты действительно очищены
    from app.core.people_store import load_candidates

    assert load_candidates() == {}


def test_clear_candidates_without_confirmation(mock_test_data):
    """Тест отмены очистки кандидатов."""
    with patch("builtins.input", return_value="no"):
        with patch("sys.stdout", new=StringIO()) as fake_out:
            _clear_candidates()
            output = fake_out.getvalue()

    assert "Операция отменена" in output

    # Проверяем, что кандидаты остались
    from app.core.people_store import load_candidates

    candidates = load_candidates()
    assert len(candidates) == 3


def test_clear_candidates_various_confirmations(mock_test_data):
    """Тест различных вариантов подтверждения."""
    from app.core.people_store import load_candidates

    # Тестируем разные варианты "да"
    for confirmation in ["yes", "y", "да", "д"]:
        # Восстанавливаем данные
        candidates_data = {"candidates": {"Test": 1}}
        candidates_file = mock_test_data / "people_candidates.json"
        with open(candidates_file, "w", encoding="utf-8") as f:
            json.dump(candidates_data, f)

        with patch("builtins.input", return_value=confirmation):
            with patch("sys.stdout", new=StringIO()):
                _clear_candidates()

        assert load_candidates() == {}


class TestPeopleMinerIntegration:
    """Интеграционные тесты для people_miner."""

    def test_main_stats_option(self, mock_test_data):
        """Тест запуска с опцией --stats."""
        from app.tools.people_miner import main

        with patch("sys.argv", ["people_miner.py", "--stats"]):
            with patch("sys.stdout", new=StringIO()) as fake_out:
                main()
                output = fake_out.getvalue()

        assert "Статистика кандидатов" in output
        assert "Всего кандидатов: 3" in output

    def test_main_clear_option_with_confirmation(self, mock_test_data):
        """Тест запуска с опцией --clear и подтверждением."""
        from app.tools.people_miner import main

        with patch("sys.argv", ["people_miner.py", "--clear"]):
            with patch("builtins.input", return_value="yes"):
                with patch("sys.stdout", new=StringIO()) as fake_out:
                    main()
                    output = fake_out.getvalue()

        assert "Словарь кандидатов очищен" in output

    def test_main_help_option(self):
        """Тест запуска с опцией --help."""
        from app.tools.people_miner import main

        with patch("sys.argv", ["people_miner.py", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.stdout", new=StringIO()):
                    main()

            assert exc_info.value.code == 0
            # Проверяем, что вывод содержит справочную информацию
            # (вывод идет в stdout до SystemExit)


def test_validate_person_entry_integration():
    """Интеграционный тест валидации записи."""
    from app.core.people_detect import validate_person_entry

    # Корректная запись
    valid_person = {"name_en": "Alice Johnson", "aliases": ["Alice", "Алиса"]}
    errors = validate_person_entry(valid_person)
    assert errors == []

    # Некорректная запись
    invalid_person = {"name_en": "", "aliases": []}
    errors = validate_person_entry(invalid_person)
    assert len(errors) > 0


def test_propose_name_en_integration():
    """Интеграционный тест предложения английского имени."""
    from app.core.people_detect import propose_name_en

    test_cases = [
        ("алиса", "Alisa"),
        ("Борис Петров", "Boris Petrov"),
        ("john doe", "John Doe"),
        ("mary-jane", "Mary-Jane"),
    ]

    for input_alias, expected_name in test_cases:
        result = propose_name_en(input_alias)
        assert result == expected_name
