"""Интеграционные тесты для системы управления людьми"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.normalize import run as normalize_run
from app.core.people_store import load_candidates


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
            patch("app.core.normalize.DICT_DIR", temp_path),
        ):
            yield temp_path


@pytest.fixture
def setup_test_data(temp_dict_dir):
    """Настраивает тестовые данные для интеграционных тестов."""
    # Создаем основной словарь людей
    people_data = {
        "people": [
            {"name_en": "Valentin", "aliases": ["Валентин", "Валя", "Valentin", "Val"]},
            {"name_en": "Daniil", "aliases": ["Даня", "Даниил", "Danya", "Daniil", "даней"]},
        ]
    }
    people_file = temp_dict_dir / "people.json"
    with open(people_file, "w", encoding="utf-8") as f:
        json.dump(people_data, f)

    # Создаем пустой словарь кандидатов
    candidates_data = {"candidates": {}}
    candidates_file = temp_dict_dir / "people_candidates.json"
    with open(candidates_file, "w", encoding="utf-8") as f:
        json.dump(candidates_data, f)

    # Создаем стоп-слова
    stopwords_data = {"stop": ["Проект", "Бюджет", "IFRS", "Встреча"]}
    stopwords_file = temp_dict_dir / "people_stopwords.json"
    with open(stopwords_file, "w", encoding="utf-8") as f:
        json.dump(stopwords_data, f)


def test_normalize_with_known_people(setup_test_data):
    """Тест обработки текста с известными людьми."""
    text = "Встреча 25.03.2024 с Валентином и Даней. Обсудили бюджет проекта IFRS."

    result = normalize_run(raw_bytes=None, text=text, filename="test_meeting.txt")

    # Проверяем основные поля
    assert result["title"] == "test_meeting"
    assert result["date"] == "2024-03-25"
    assert result["text"] == text

    # Проверяем, что известные люди найдены
    assert "Valentin" in result["attendees"]
    assert "Daniil" in result["attendees"]

    # Проверяем, что кандидатов не добавилось (все люди известны)
    candidates = load_candidates()
    # Могут быть другие слова, но не должно быть известных имен
    known_names = {
        "валентин",
        "валя",
        "valentin",
        "val",
        "даня",
        "даниил",
        "danya",
        "daniil",
        "даней",
    }
    for candidate in candidates.keys():
        assert candidate.lower() not in known_names


def test_normalize_with_unknown_people(setup_test_data):
    """Тест обработки текста с неизвестными людьми."""
    text = "Встреча с Alice, Bob Johnson и Charlie Smith. Обсудили новый проект."

    result = normalize_run(raw_bytes=None, text=text, filename="meeting_with_new_people.txt")

    # Проверяем основные поля
    assert result["title"] == "meeting_with_new_people"
    assert result["attendees"] == []  # Неизвестные люди не попадают в attendees

    # Проверяем, что новые кандидаты добавились
    candidates = load_candidates()

    # Должны появиться новые кандидаты
    candidate_names = set(candidates.keys())
    assert len(candidate_names) > 0

    # Проверяем, что среди кандидатов есть новые имена
    found_names = set()
    for candidate in candidate_names:
        if any(name in candidate for name in ["Alice", "Bob", "Charlie"]):
            found_names.add(candidate)

    assert len(found_names) > 0, f"Expected to find new names in candidates: {candidate_names}"


def test_normalize_with_mixed_people(setup_test_data):
    """Тест обработки текста со смешанными людьми (известные + неизвестные)."""
    text = "Встреча Валентина с Alice и Bob. Даня тоже участвовал удаленно."

    result = normalize_run(raw_bytes=None, text=text, filename="mixed_meeting.txt")

    # Проверяем, что известные люди найдены
    assert "Valentin" in result["attendees"]
    assert "Daniil" in result["attendees"]

    # Проверяем, что новые кандидаты добавились
    candidates = load_candidates()
    candidate_names = set(candidates.keys())

    # Должны быть новые имена, но не известные
    known_names = {
        "валентин",
        "валя",
        "valentin",
        "val",
        "даня",
        "даниил",
        "danya",
        "daniil",
        "даней",
    }
    new_candidates = [c for c in candidate_names if c.lower() not in known_names]

    assert len(new_candidates) > 0, f"Expected new candidates, got: {candidate_names}"


def test_normalize_candidate_frequency_tracking(setup_test_data):
    """Тест отслеживания частоты кандидатов."""
    # Первая встреча с Alice
    text1 = "Alice обсуждала проект с командой."
    normalize_run(raw_bytes=None, text=text1, filename="meeting1.txt")

    candidates_after_first = load_candidates()
    alice_count_first = candidates_after_first.get("Alice", 0)

    # Вторая встреча с Alice
    text2 = "Alice представила результаты исследования."
    normalize_run(raw_bytes=None, text=text2, filename="meeting2.txt")

    candidates_after_second = load_candidates()
    alice_count_second = candidates_after_second.get("Alice", 0)

    # Проверяем, что счетчик увеличился
    assert alice_count_second > alice_count_first
    assert alice_count_second >= 2


def test_normalize_filters_stopwords(setup_test_data):
    """Тест фильтрации стоп-слов."""
    text = "Встреча по проекту IFRS. Обсудили бюджет и план."

    normalize_run(raw_bytes=None, text=text, filename="stopwords_meeting.txt")

    candidates = load_candidates()
    candidate_names_lower = {c.lower() for c in candidates.keys()}

    # Проверяем, что стоп-слова не попали в кандидаты
    stopwords = {"проект", "бюджет", "ifrs", "встреча", "план"}
    for stopword in stopwords:
        assert stopword not in candidate_names_lower, f"Stopword '{stopword}' found in candidates"


def test_normalize_handles_different_cases(setup_test_data):
    """Тест обработки имен в разных падежах."""
    # Текст с именами - некоторые в именительном падеже, некоторые в других
    text = "Валентин встретился с Алисой. Даня тоже был на встрече."

    result = normalize_run(raw_bytes=None, text=text, filename="cases_meeting.txt")

    # Известные люди должны быть найдены, если они в известных формах
    assert "Valentin" in result["attendees"]  # "Валентин" есть в алиасах
    assert "Daniil" in result["attendees"]  # "Даня" есть в алиасах

    # Новые кандидаты могут быть в разных падежах
    candidates = load_candidates()
    alice_variants = [c for c in candidates.keys() if "лис" in c.lower()]
    assert len(alice_variants) > 0, "Expected to find Alice variants in candidates"


def test_end_to_end_workflow(setup_test_data):
    """Полный end-to-end тест workflow."""
    # 1. Обрабатываем несколько встреч с новыми людьми
    meetings = [
        "Alice обсуждала проект с Bob Johnson.",
        "Charlie Smith присоединился к Alice на второй встрече.",
        "Bob Johnson и Alice завершили планирование.",
    ]

    for i, text in enumerate(meetings):
        normalize_run(raw_bytes=None, text=text, filename=f"meeting_{i}.txt")

    # 2. Проверяем накопленных кандидатов
    candidates = load_candidates()

    # Alice должна встречаться чаще всего (3 раза)
    assert candidates.get("Alice", 0) == 3

    # Bob Johnson должен встречаться 2 раза
    bob_count = sum(count for name, count in candidates.items() if "Bob" in name)
    assert bob_count >= 2

    # Charlie Smith должен встречаться 1 раз
    charlie_count = sum(count for name, count in candidates.items() if "Charlie" in name)
    assert charlie_count >= 1

    # 3. Проверяем, что можем получить топ кандидатов
    sorted_candidates = sorted(candidates.items(), key=lambda x: x[1], reverse=True)

    # Alice должна быть первой по частоте
    assert sorted_candidates[0][0] == "Alice"
    assert sorted_candidates[0][1] == 3


def test_normalize_preserves_original_functionality(setup_test_data):
    """Тест, что интеграция не сломала основную функциональность normalize."""
    text = "Встреча 15.06.2024. Обсудили квартальные результаты."

    result = normalize_run(raw_bytes=None, text=text, filename="quarterly_2024-06-15.txt")

    # Основная функциональность должна работать
    assert result["title"] == "quarterly_2024-06-15"
    assert result["date"] == "2024-06-15"  # Дата из имени файла
    assert result["text"] == text
    assert result["raw_hash"] is not None
    assert len(result["raw_hash"]) == 64  # SHA256 hash
    assert result["attendees"] == []  # Нет известных людей
