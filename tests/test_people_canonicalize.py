"""
Тесты для функции canonicalize_list из people_store.py
"""

from unittest.mock import patch

import pytest

from app.core.people_store import canonicalize_list


@pytest.fixture
def mock_people_data():
    """Мок данных для people.json"""
    return [
        {"name_en": "Valentin", "aliases": ["Валентин", "valentin", "val"]},
        {"name_en": "Daniil", "aliases": ["Даниил", "daniil", "danya"]},
        {"name_en": "Sasha Katanov", "aliases": ["Саша Катанов", "sasha", "katanov"]},
        {
            "name_en": "",  # Пустое имя - должно игнорироваться
            "aliases": ["empty"],
        },
    ]


@patch("app.core.people_store.load_people")
def test_canonicalize_basic(mock_load_people, mock_people_data):
    """Тест базовой канонизации имен"""
    mock_load_people.return_value = mock_people_data

    raw_names = ["Валентин", "Daniil", "Саша Катанов"]
    result = canonicalize_list(raw_names)

    assert result == ["Valentin", "Daniil", "Sasha Katanov"]


@patch("app.core.people_store.load_people")
def test_canonicalize_aliases(mock_load_people, mock_people_data):
    """Тест канонизации через алиасы"""
    mock_load_people.return_value = mock_people_data

    raw_names = ["val", "danya", "katanov"]
    result = canonicalize_list(raw_names)

    assert result == ["Valentin", "Daniil", "Sasha Katanov"]


@patch("app.core.people_store.load_people")
def test_canonicalize_duplicates(mock_load_people, mock_people_data):
    """Тест удаления дубликатов"""
    mock_load_people.return_value = mock_people_data

    raw_names = ["Валентин", "valentin", "val", "Valentin"]
    result = canonicalize_list(raw_names)

    assert result == ["Valentin"]


@patch("app.core.people_store.load_people")
def test_canonicalize_unknown_kept(mock_load_people, mock_people_data):
    """Тест сохранения неизвестных имен (изменена логика)"""
    mock_load_people.return_value = mock_people_data

    raw_names = ["Валентин", "Unknown Person", "Daniil", "Another Unknown"]
    result = canonicalize_list(raw_names)

    # Теперь неизвестные имена сохраняются как есть
    assert result == ["Valentin", "Unknown Person", "Daniil", "Another Unknown"]


@patch("app.core.people_store.load_people")
def test_canonicalize_empty_inputs(mock_load_people, mock_people_data):
    """Тест обработки пустых входных данных"""
    mock_load_people.return_value = mock_people_data

    # Пустой список
    assert canonicalize_list([]) == []

    # None
    assert canonicalize_list(None) == []

    # Список с пустыми строками
    assert canonicalize_list(["", "  ", "\t"]) == []


@patch("app.core.people_store.load_people")
def test_canonicalize_case_insensitive(mock_load_people, mock_people_data):
    """Тест нечувствительности к регистру"""
    mock_load_people.return_value = mock_people_data

    raw_names = ["ВАЛЕНТИН", "dAnIiL", "sAsHa"]
    result = canonicalize_list(raw_names)

    assert result == ["Valentin", "Daniil", "Sasha Katanov"]


@patch("app.core.people_store.load_people")
def test_canonicalize_whitespace_handling(mock_load_people, mock_people_data):
    """Тест обработки пробелов"""
    mock_load_people.return_value = mock_people_data

    raw_names = ["  Валентин  ", "\tDaniil\n", " val "]
    result = canonicalize_list(raw_names)

    assert result == ["Valentin", "Daniil"]


@patch("app.core.people_store.load_people")
def test_canonicalize_empty_people_data(mock_load_people):
    """Тест с пустыми данными people.json"""
    mock_load_people.return_value = []

    raw_names = ["Валентин", "Daniil"]
    result = canonicalize_list(raw_names)

    # Теперь неизвестные имена сохраняются как есть
    assert result == ["Валентин", "Daniil"]


@patch("app.core.people_store.load_people")
def test_canonicalize_mixed_valid_invalid(mock_load_people, mock_people_data):
    """Тест смешанного списка с валидными и невалидными именами"""
    mock_load_people.return_value = mock_people_data

    raw_names = ["Валентин", "", "Unknown", "Daniil", "  ", "empty", "sasha"]
    result = canonicalize_list(raw_names)

    # empty - алиас не найден в индексе (пустое name_en игнорируется при построении индекса)
    # Теперь неизвестные имена сохраняются, пустые строки игнорируются
    assert result == ["Valentin", "Unknown", "Daniil", "empty", "Sasha Katanov"]
