"""Тесты для app.core.people_store"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.people_store import (
    bump_candidates,
    clear_candidates,
    get_candidate_stats,
    load_candidates,
    load_people,
    load_stopwords,
    remove_candidate,
    save_people,
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
        
        with patch("app.core.people_store.DICT_DIR", temp_path), \
             patch("app.core.people_store.PEOPLE", people_file), \
             patch("app.core.people_store.CAND", candidates_file), \
             patch("app.core.people_store.STOPS", stopwords_file):
            yield temp_path


def test_load_people_empty(temp_dict_dir):
    """Тест загрузки людей из несуществующего файла."""
    result = load_people()
    assert result == []


def test_load_people_existing(temp_dict_dir):
    """Тест загрузки людей из существующего файла."""
    people_data = {
        "people": [
            {"name_en": "John Doe", "aliases": ["John", "Johnny"]},
            {"name_en": "Jane Smith", "aliases": ["Jane"]},
        ]
    }
    
    people_file = temp_dict_dir / "people.json"
    with open(people_file, "w", encoding="utf-8") as f:
        json.dump(people_data, f)
    
    result = load_people()
    assert len(result) == 2
    assert result[0]["name_en"] == "John Doe"
    assert result[1]["name_en"] == "Jane Smith"


def test_save_people(temp_dict_dir):
    """Тест сохранения людей."""
    people = [
        {"name_en": "Test User", "aliases": ["Test", "User"]},
    ]
    
    save_people(people)
    
    people_file = temp_dict_dir / "people.json"
    assert people_file.exists()
    
    with open(people_file, encoding="utf-8") as f:
        data = json.load(f)
    
    assert "people" in data
    assert len(data["people"]) == 1
    assert data["people"][0]["name_en"] == "Test User"


def test_load_candidates_empty(temp_dict_dir):
    """Тест загрузки кандидатов из несуществующего файла."""
    result = load_candidates()
    assert result == {}


def test_load_candidates_existing(temp_dict_dir):
    """Тест загрузки кандидатов из существующего файла."""
    candidates_data = {
        "candidates": {"Alice": 3, "Bob": 1}
    }
    
    candidates_file = temp_dict_dir / "people_candidates.json"
    with open(candidates_file, "w", encoding="utf-8") as f:
        json.dump(candidates_data, f)
    
    result = load_candidates()
    assert result == {"Alice": 3, "Bob": 1}


def test_bump_candidates_new(temp_dict_dir):
    """Тест добавления новых кандидатов."""
    bump_candidates(["Alice", "Bob", "Alice"])
    
    result = load_candidates()
    assert result["Alice"] == 2
    assert result["Bob"] == 1


def test_bump_candidates_existing(temp_dict_dir):
    """Тест обновления существующих кандидатов."""
    # Создаем начальное состояние
    candidates_data = {"candidates": {"Alice": 1}}
    candidates_file = temp_dict_dir / "people_candidates.json"
    with open(candidates_file, "w", encoding="utf-8") as f:
        json.dump(candidates_data, f)
    
    # Добавляем еще кандидатов
    bump_candidates(["Alice", "Bob"])
    
    result = load_candidates()
    assert result["Alice"] == 2  # было 1, стало 2
    assert result["Bob"] == 1    # новый


def test_bump_candidates_empty_aliases(temp_dict_dir):
    """Тест обработки пустых алиасов."""
    bump_candidates(["", "  ", "Alice", None])
    
    result = load_candidates()
    assert "Alice" in result
    assert result["Alice"] == 1
    assert "" not in result
    assert "  " not in result


def test_load_stopwords_empty(temp_dict_dir):
    """Тест загрузки стоп-слов из несуществующего файла."""
    result = load_stopwords()
    assert result == set()


def test_load_stopwords_existing(temp_dict_dir):
    """Тест загрузки стоп-слов из существующего файла."""
    stopwords_data = {"stop": ["Проект", "Бюджет", "CEO"]}
    
    stopwords_file = temp_dict_dir / "people_stopwords.json"
    with open(stopwords_file, "w", encoding="utf-8") as f:
        json.dump(stopwords_data, f)
    
    result = load_stopwords()
    expected = {"проект", "бюджет", "ceo"}  # в нижнем регистре
    assert result == expected


def test_clear_candidates(temp_dict_dir):
    """Тест очистки кандидатов."""
    # Создаем кандидатов
    bump_candidates(["Alice", "Bob"])
    assert len(load_candidates()) == 2
    
    # Очищаем
    clear_candidates()
    assert load_candidates() == {}


def test_remove_candidate_existing(temp_dict_dir):
    """Тест удаления существующего кандидата."""
    bump_candidates(["Alice", "Bob"])
    
    result = remove_candidate("Alice")
    assert result is True
    
    candidates = load_candidates()
    assert "Alice" not in candidates
    assert "Bob" in candidates


def test_remove_candidate_nonexistent(temp_dict_dir):
    """Тест удаления несуществующего кандидата."""
    result = remove_candidate("NonExistent")
    assert result is False


def test_get_candidate_stats_empty(temp_dict_dir):
    """Тест статистики для пустого словаря кандидатов."""
    stats = get_candidate_stats()
    expected = {"total": 0, "max_count": 0, "min_count": 0}
    assert stats == expected


def test_get_candidate_stats_with_data(temp_dict_dir):
    """Тест статистики с данными."""
    bump_candidates(["Alice"] * 5 + ["Bob"] * 2 + ["Charlie"] * 1)
    
    stats = get_candidate_stats()
    assert stats["total"] == 3
    assert stats["max_count"] == 5
    assert stats["min_count"] == 1
    assert stats["avg_count"] == (5 + 2 + 1) / 3


def test_load_json_invalid_file(temp_dict_dir):
    """Тест обработки поврежденного JSON файла."""
    # Создаем файл с невалидным JSON
    invalid_file = temp_dict_dir / "invalid.json"
    with open(invalid_file, "w", encoding="utf-8") as f:
        f.write("invalid json content")
    
    # Патчим путь к файлу people.json
    with patch("app.core.people_store.PEOPLE", invalid_file):
        result = load_people()
        assert result == []  # fallback значение


def test_stopwords_case_insensitive(temp_dict_dir):
    """Тест что стоп-слова приводятся к нижнему регистру."""
    stopwords_data = {"stop": ["Проект", "БЮДЖЕТ", "CeO"]}
    
    stopwords_file = temp_dict_dir / "people_stopwords.json"
    with open(stopwords_file, "w", encoding="utf-8") as f:
        json.dump(stopwords_data, f)
    
    result = load_stopwords()
    assert "проект" in result
    assert "бюджет" in result
    assert "ceo" in result
    assert "Проект" not in result  # не должно быть в исходном регистре
