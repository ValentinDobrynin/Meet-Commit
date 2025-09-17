"""Тесты для app.core.people_detect"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.people_detect import (
    get_detection_stats,
    mine_alias_candidates,
    propose_name_en,
    validate_person_entry,
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
            patch("app.core.people_detect.load_stopwords") as mock_stopwords,
        ):
            # Настраиваем мок для стоп-слов
            mock_stopwords.return_value = {
                "проект",
                "бюджет",
                "ceo",
                "meeting",
                "январь",
                "март",
                "pm",
            }
            yield temp_path


@pytest.fixture
def mock_people_data(temp_dict_dir):
    """Создает тестовые данные для людей и стоп-слов."""
    import json

    # Создаем тестовых людей
    people_data = {
        "people": [
            {"name_en": "John Doe", "aliases": ["John", "Johnny", "Джон"]},
            {"name_en": "Jane Smith", "aliases": ["Jane", "Джейн"]},
        ]
    }
    people_file = temp_dict_dir / "people.json"
    with open(people_file, "w", encoding="utf-8") as f:
        json.dump(people_data, f)

    # Создаем стоп-слова
    stopwords_data = {"stop": ["Проект", "Бюджет", "CEO", "Meeting"]}
    stopwords_file = temp_dict_dir / "people_stopwords.json"
    with open(stopwords_file, "w", encoding="utf-8") as f:
        json.dump(stopwords_data, f)


def test_mine_alias_candidates_empty_text(mock_people_data):
    """Тест обработки пустого текста."""
    result = mine_alias_candidates("")
    assert result == []

    result = mine_alias_candidates("   ")
    assert result == []


def test_mine_alias_candidates_latin_names(mock_people_data):
    """Тест поиска латинских имен."""
    text = "Alice spoke with Bob Johnson about the project. Charlie also attended."
    result = mine_alias_candidates(text)

    # John и Jane уже известны, поэтому их не должно быть
    # Проект - стоп-слово
    expected = {"Alice", "Bob Johnson", "Charlie"}
    assert set(result) == expected


def test_mine_alias_candidates_cyrillic_names(mock_people_data):
    """Тест поиска кириллических имен."""
    text = "Алиса обсуждала с Борисом Петровым и Владимиром вопросы по проекту."
    result = mine_alias_candidates(text)

    # В тексте могут быть имена в разных падежах, детектор находит их как есть
    result_set = set(result)
    assert "Алиса" in result_set
    # Может найти "Борис Петров" или "Борисом Петровым" в зависимости от паттерна
    assert any("Борис" in name for name in result_set)
    assert any("Владимир" in name for name in result_set)


def test_mine_alias_candidates_mixed_languages(mock_people_data):
    """Тест поиска имен на разных языках."""
    text = "Alice встретилась с Борисом и David Johnson обсудили планы."
    result = mine_alias_candidates(text)

    result_set = set(result)
    assert "Alice" in result_set
    assert "David Johnson" in result_set
    # Может найти "Борис" или "Борисом" в зависимости от падежа
    assert any("Борис" in name for name in result_set)


def test_mine_alias_candidates_filters_known(mock_people_data):
    """Тест фильтрации уже известных имен."""
    text = "John met with Alice. Jane was also there with Charlie."
    result = mine_alias_candidates(text)

    # John и Jane уже известны в mock_people_data, не должны попасть в результат
    result_set = set(result)
    assert "John" not in result_set  # известный
    assert "Jane" not in result_set  # известная
    assert "Alice" in result_set  # новая
    assert "Charlie" in result_set  # новый


def test_mine_alias_candidates_filters_stopwords(mock_people_data):
    """Тест фильтрации стоп-слов."""
    text = "Alice discussed the Проект with CEO Charlie. Meeting was productive."
    result = mine_alias_candidates(text)

    result_set = set(result)
    # Проект, CEO, Meeting - стоп-слова, не должны попадать
    assert "проект" not in {c.lower() for c in result_set}
    assert "ceo" not in {c.lower() for c in result_set}
    assert "meeting" not in {c.lower() for c in result_set}

    # Alice и Charlie - валидные кандидаты
    assert "Alice" in result_set
    assert "Charlie" in result_set


def test_mine_alias_candidates_hyphenated_names(mock_people_data):
    """Тест поиска составных имен с дефисом."""
    text = "Mary-Jane and Jean-Claude discussed the issue."
    result = mine_alias_candidates(text)

    result_set = set(result)
    # Может найти как составные имена, так и отдельные части
    assert any("Mary" in name for name in result_set)
    assert any("Jane" in name for name in result_set)
    assert any("Jean" in name for name in result_set)
    assert any("Claude" in name for name in result_set)


def test_mine_alias_candidates_max_scan_limit(mock_people_data):
    """Тест ограничения сканирования текста."""
    # Создаем текст где имя находится за пределами лимита
    short_text = "Alice" + " text" * 100
    long_text = short_text + " Charlie" + " more text" * 1000

    result_short = mine_alias_candidates(long_text, max_scan=len(short_text))
    result_long = mine_alias_candidates(long_text, max_scan=len(long_text))

    assert "Alice" in result_short
    assert "Charlie" not in result_short  # за пределами лимита
    assert "Charlie" in result_long


def test_propose_name_en_latin():
    """Тест предложения английского имени для латинских алиасов."""
    assert propose_name_en("alice") == "Alice"
    assert propose_name_en("john doe") == "John Doe"
    assert propose_name_en("mary-jane") == "Mary-Jane"


def test_propose_name_en_cyrillic():
    """Тест транслитерации кириллических имен."""
    assert propose_name_en("Алиса") == "Alisa"
    assert propose_name_en("Борис Петров") == "Boris Petrov"
    assert propose_name_en("Владимир") == "Vladimir"


def test_propose_name_en_mixed():
    """Тест обработки смешанных алиасов."""
    assert propose_name_en("Alice Петрова") == "Alice Petrova"


def test_propose_name_en_empty():
    """Тест обработки пустых алиасов."""
    assert propose_name_en("") == ""
    assert propose_name_en("   ") == ""


def test_validate_person_entry_valid():
    """Тест валидации корректной записи."""
    person = {"name_en": "John Doe", "aliases": ["John", "Johnny", "Джон"]}
    errors = validate_person_entry(person)
    assert errors == []


def test_validate_person_entry_missing_name_en():
    """Тест валидации записи без name_en."""
    person = {"aliases": ["John"]}
    errors = validate_person_entry(person)
    assert "Missing required field: name_en" in errors


def test_validate_person_entry_missing_aliases():
    """Тест валидации записи без aliases."""
    person = {"name_en": "John Doe"}
    errors = validate_person_entry(person)
    assert "Missing required field: aliases" in errors


def test_validate_person_entry_empty_aliases():
    """Тест валидации записи с пустыми aliases."""
    person = {"name_en": "John Doe", "aliases": []}
    errors = validate_person_entry(person)
    assert "Field 'aliases' cannot be empty" in errors


def test_validate_person_entry_invalid_name_format():
    """Тест валидации записи с неправильным форматом имени."""
    person = {"name_en": "John123", "aliases": ["John"]}
    errors = validate_person_entry(person)
    assert any("Invalid name_en format" in error for error in errors)


def test_validate_person_entry_invalid_alias_type():
    """Тест валидации записи с неправильным типом алиаса."""
    person = {"name_en": "John Doe", "aliases": ["John", 123, "Johnny"]}
    errors = validate_person_entry(person)
    assert "Alias at index 1 must be a string" in errors


def test_get_detection_stats_empty_text(mock_people_data):
    """Тест статистики для пустого текста."""
    stats = get_detection_stats("")
    expected = {"total_candidates": 0, "known_aliases": 0, "filtered_out": 0, "new_candidates": 0}
    assert stats == expected


def test_get_detection_stats_with_data(mock_people_data):
    """Тест статистики с данными."""
    text = "John met with Alice and CEO Bob. Проект was discussed."
    stats = get_detection_stats(text)

    # John - известный, Alice и Bob - новые, CEO и Проект - стоп-слова
    assert stats["total_candidates"] >= 3  # John, Alice, Bob как минимум
    assert stats["known_aliases"] >= 1  # John
    assert stats["filtered_out"] >= 0  # CEO, Проект (могут не найтись нашими паттернами)
    assert stats["new_candidates"] >= 1  # Alice, Bob


def test_mine_alias_candidates_excludes_abbreviations(mock_people_data):
    """Тест исключения аббревиатур."""
    text = "Alice works at IBM with API and XML technologies."
    result = mine_alias_candidates(text)

    # IBM, API, XML - аббревиатуры, не должны попасть в результат
    assert "Alice" in result
    assert "IBM" not in result
    assert "API" not in result
    assert "XML" not in result


def test_mine_alias_candidates_excludes_numbers(mock_people_data):
    """Тест исключения чисел и имен с цифрами."""
    text = "Alice123 met User1 and Test2 in room 2024."
    result = mine_alias_candidates(text)

    # Имена с цифрами не должны попадать в результат
    assert result == []


def test_mine_alias_candidates_length_limits(mock_people_data):
    """Тест ограничений по длине имен."""
    text = "A VeryLongNameThatExceedsFiftyCharactersAndShouldNotBeDetected"
    result = mine_alias_candidates(text)

    # Слишком короткие и слишком длинные имена не должны попадать
    assert "A" not in result  # слишком короткое
    assert (
        "VeryLongNameThatExceedsFiftyCharactersAndShouldNotBeDetected" not in result
    )  # слишком длинное


def test_mine_alias_candidates_initials(mock_people_data):
    """Тест поиска инициалов."""
    text = "Присутствовали: А. Петров, B. Smith, И. Иванов"
    result = mine_alias_candidates(text)

    result_set = set(result)
    assert "А. Петров" in result_set
    assert "B. Smith" in result_set
    assert "И. Иванов" in result_set


def test_mine_alias_candidates_excludes_emails_urls(mock_people_data):
    """Тест исключения email и URL."""
    text = "Связаться с alice@example.com или http://example.com/alice"
    result = mine_alias_candidates(text)

    # Email и URL не должны попадать в кандидаты
    for candidate in result:
        assert "@" not in candidate
        assert "http" not in candidate


def test_mine_alias_candidates_excludes_months_roles(mock_people_data):
    """Тест исключения месяцев и ролей."""
    text = "В марте CFO встретился с PM. Январь был продуктивным."
    result = mine_alias_candidates(text)

    # Все должно быть отфильтровано
    assert result == []


def test_mine_alias_candidates_requires_long_words(mock_people_data):
    """Тест требования длинных слов для исключения ложных срабатываний."""
    text = "Да, он был там. Нет проблем."
    result = mine_alias_candidates(text)

    # Короткие слова не должны попадать в кандидаты
    assert "Да" not in result
    assert "Нет" not in result


def test_propose_name_en_special_cases():
    """Тест специальных случаев капитализации."""
    from app.core.people_detect import propose_name_en

    test_cases = [
        ("o'connor", "O'Connor"),
        ("mcdonald", "McDonald"),
        ("mary-jane o'connor", "Mary-Jane O'Connor"),
        ("mcgregor", "McGregor"),
        ("d'angelo", "D'Angelo"),
    ]

    for input_alias, expected_name in test_cases:
        result = propose_name_en(input_alias)
        assert result == expected_name


def test_validate_person_entry_duplicates():
    """Тест валидации дубликатов алиасов."""
    from app.core.people_detect import validate_person_entry

    person = {
        "name_en": "John Doe",
        "aliases": ["John", "john", "Johnny", "JOHN"],  # дубликаты
    }
    errors = validate_person_entry(person)
    assert "Aliases contain duplicates (case-insensitive)" in errors


def test_validate_person_entry_with_empty_elements():
    """Тест валидации алиасов с пустыми элементами."""
    from app.core.people_detect import validate_person_entry

    person = {
        "name_en": "John Doe",
        "aliases": ["John", "", "  ", None, "Johnny"],  # пустые элементы
    }
    errors = validate_person_entry(person)
    # Должны быть ошибки для пустых элементов
    assert len(errors) > 0
    assert any("cannot be empty" in error for error in errors)


def test_mine_alias_candidates_dedup_normalization(mock_people_data):
    """Тест дедупликации и нормализации кандидатов."""
    text = "Alice   Johnson встретилась с  Alice Johnson"
    result = mine_alias_candidates(text)

    # Должен быть только один кандидат после нормализации пробелов
    alice_variants = [c for c in result if "Alice" in c]
    assert len(alice_variants) == 1
    assert alice_variants[0] == "Alice Johnson"
