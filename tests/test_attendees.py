import pytest
from app.core.normalize import _extract_attendees_en, _load_people
from app.core.tagger import run as tagger_run


def test_load_people():
    """Тест загрузки словаря людей."""
    people = _load_people()
    assert isinstance(people, list)
    assert len(people) > 0
    
    # Проверяем структуру
    for person in people:
        assert "name_en" in person
        assert "aliases" in person
        assert isinstance(person["aliases"], list)


def test_attendees_english_resolution():
    """Тест извлечения участников и их канонических английских имен."""
    sample = "Присутствовали: Валентин и Даня. Обсудили бюджет."
    names = _extract_attendees_en(sample)
    assert "Valentin" in names
    assert "Daniil" in names


def test_attendees_case_insensitive():
    """Тест нечувствительности к регистру."""
    sample = "Встреча с ВАЛЕНТИНОМ и даней"
    names = _extract_attendees_en(sample)
    assert "Valentin" in names
    assert "Daniil" in names


def test_attendees_no_duplicates():
    """Тест отсутствия дубликатов."""
    sample = "Валентин, Валя, Валентин - все один человек"
    names = _extract_attendees_en(sample)
    assert names.count("Valentin") == 1


def test_attendees_empty_text():
    """Тест с пустым текстом."""
    names = _extract_attendees_en("")
    assert names == []


def test_attendees_no_matches():
    """Тест когда никто не найден."""
    sample = "Встреча с неизвестными людьми"
    names = _extract_attendees_en(sample)
    assert names == []


def test_attendees_partial_matches():
    """Тест частичных совпадений."""
    sample = "Встреча с Валентином и Катей"
    names = _extract_attendees_en(sample)
    assert "Valentin" in names
    assert "Katya" in names


def test_attendees_max_scan_limit():
    """Тест ограничения сканирования."""
    # Создаем длинный текст где имена в конце
    long_text = "Обычный текст " * 1000 + "Валентин и Даня"
    names = _extract_attendees_en(long_text, max_scan=100)
    assert names == []  # Не должны найти, так как имена за пределами max_scan


def test_tagger_with_attendees():
    """Тест теггера с участниками."""
    summary = "Обсудили бюджет проекта"
    meta = {
        "title": "Встреча по проекту",
        "attendees": ["Valentin", "Daniil"]
    }
    tags = tagger_run(summary, meta)
    
    # Проверяем что добавились теги участников
    assert "person/valentin" in tags
    assert "person/daniil" in tags


def test_tagger_attendees_empty():
    """Тест теггера без участников."""
    summary = "Обсудили бюджет проекта"
    meta = {
        "title": "Встреча по проекту",
        "attendees": []
    }
    tags = tagger_run(summary, meta)
    
    # Не должно быть тегов person/*
    person_tags = [tag for tag in tags if tag.startswith("person/")]
    assert len(person_tags) == 0


def test_tagger_attendees_with_spaces():
    """Тест теггера с пробелами в именах."""
    summary = "Обсудили бюджет проекта"
    meta = {
        "title": "Встреча по проекту",
        "attendees": [" Valentin ", " Daniil "]
    }
    tags = tagger_run(summary, meta)
    
    # Пробелы должны быть убраны
    assert "person/valentin" in tags
    assert "person/daniil" in tags
