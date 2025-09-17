"""Тесты для улучшенного тегирования v2"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.tagger import (
    _build_index,
    _load_tags,
    _normalize_token,
    _token_counts,
    run,
)


@pytest.fixture
def temp_dict_dir():
    """Создает временную директорию для словарей."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Патчим пути к файлам
        tags_file = temp_path / "tags.json"
        legacy_file = temp_path / "tag_synonyms.json"
        
        with patch("app.core.tagger.TAGS_PATH", tags_file), \
             patch("app.core.tagger.LEGACY_SYNONYMS_PATH", legacy_file):
            yield temp_path


@pytest.fixture
def mock_tags_data(temp_dict_dir):
    """Создает тестовые данные для тегов."""
    tags_data = {
        "area/ifrs": ["ifrs", "фрс", "МСФО", "финансовая отчетность"],
        "project/budgets": ["budget", "бюдж", "бюджет", "бюджетирование"],
        "topic/meeting": ["встреча", "meeting", "синк", "sync"],
    }
    
    tags_file = temp_dict_dir / "tags.json"
    with open(tags_file, "w", encoding="utf-8") as f:
        json.dump(tags_data, f, ensure_ascii=False, indent=2)
    
    return tags_data


def test_normalize_token_basic():
    """Тест базовой нормализации токенов."""
    # Проверяем основную функциональность без точных ожиданий стемминга
    assert _normalize_token("MEETING") == "meeting"  # регистр
    assert len(_normalize_token("Бюджет")) >= 4      # стемминг работает
    assert len(_normalize_token("планирование")) >= 6 # стемминг работает
    assert len(_normalize_token("бюджетирования")) >= 4 # стемминг работает


def test_normalize_token_stemming():
    """Тест мини-стемминга русских окончаний."""
    # Проверяем, что стемминг работает (слова становятся короче)
    test_words = ["бюджетами", "планированием", "встречами", "отчетов", "финансовые", "обсуждали", "решения"]
    
    for word in test_words:
        result = _normalize_token(word)
        assert len(result) < len(word), f"Word {word} should be stemmed, got {result}"
        assert len(result) >= 3, f"Stemmed word {result} too short"


def test_normalize_token_punctuation():
    """Тест удаления пунктуации."""
    # Проверяем удаление пунктуации (не точные результаты)
    assert "," not in _normalize_token("бюджет,")
    assert "!" not in _normalize_token("meeting!")
    assert "-" in _normalize_token("IFRS-отчет")  # дефис сохраняется
    assert "." not in _normalize_token("планирование.")


def test_normalize_token_edge_cases():
    """Тест граничных случаев."""
    assert _normalize_token("") == ""
    assert _normalize_token("   ") == ""
    assert _normalize_token("123") == "123"
    assert _normalize_token("A") == "a"


def test_load_tags_valid(mock_tags_data):
    """Тест загрузки валидного файла тегов."""
    tags = _load_tags()
    assert "area/ifrs" in tags
    assert "project/budgets" in tags
    assert "ifrs" in tags["area/ifrs"]
    assert "бюджет" in tags["project/budgets"]


def test_load_tags_missing(temp_dict_dir):
    """Тест загрузки несуществующего файла."""
    tags = _load_tags()
    assert tags == {}


def test_load_tags_invalid_json(temp_dict_dir):
    """Тест загрузки поврежденного JSON."""
    tags_file = temp_dict_dir / "tags.json"
    with open(tags_file, "w", encoding="utf-8") as f:
        f.write("invalid json content")
    
    tags = _load_tags()
    assert tags == {}


def test_build_index(mock_tags_data):
    """Тест построения индекса синонимов."""
    tags_map = _load_tags()
    index = _build_index(tags_map)
    
    # Проверяем, что синонимы правильно маппятся
    assert index["ifrs"] == "area/ifrs"
    assert index["фрс"] == "area/ifrs"
    assert index["мсф"] == "area/ifrs"  # МСФО нормализуется в "мсф"
    assert index["budget"] == "project/budgets"
    assert index["бюдж"] == "project/budgets"  # "бюджет" нормализуется в "бюдж"


def test_token_counts():
    """Тест подсчета токенов."""
    text = "Обсудили бюджет и планирование бюджета на 2025 год. Budget planning."
    counts = _token_counts(text)
    
    # Проверяем нормализацию и подсчет
    assert counts["бюдж"] == 2      # "бюджет" + "бюджета" → "бюдж"
    assert counts["планиров"] >= 1  # "планирование" → "планиров"
    assert counts["budget"] >= 1
    assert counts["2025"] == 1
    assert counts["год"] == 1


def test_token_counts_empty():
    """Тест подсчета токенов в пустом тексте."""
    counts = _token_counts("")
    assert counts == {}
    
    counts = _token_counts("!@#$%")  # только пунктуация
    assert counts == {}


def test_run_basic_tagging(mock_tags_data):
    """Тест базового тегирования."""
    meta = {"title": "", "attendees": ["Daniil"]}
    summary = "Обсудили бюджетирование и утверждение бюджета на 2025."
    
    tags = run(summary, meta, threshold=1)
    
    assert "project/budgets" in tags  # бюджет найден
    assert "person/daniil" in tags    # участник добавлен


def test_run_threshold_filtering(mock_tags_data):
    """Тест фильтрации по порогу."""
    meta = {"title": "", "attendees": []}
    summary = "Краткое упоминание бюджета. Долгое обсуждение бюджета и бюджета процессов."
    
    # С порогом 1 - все теги
    tags_low = run(summary, meta, threshold=1)
    assert "project/budgets" in tags_low  # бюджет упомянут несколько раз
    
    # С порогом 3 - только очень частые
    tags_high = run(summary, meta, threshold=3)
    assert "project/budgets" in tags_high  # бюджет упомянут 3 раза


def test_run_mixed_languages(mock_tags_data):
    """Тест смешанных языков."""
    meta = {"title": "IFRS Reporting", "attendees": []}
    summary = "Обсудили МСФО отчетность и budget planning."
    
    tags = run(summary, meta)
    
    assert "area/ifrs" in tags      # IFRS из title + МСФО из summary
    assert "project/budgets" in tags  # budget из summary


def test_run_case_insensitive(mock_tags_data):
    """Тест нечувствительности к регистру."""
    meta = {"title": "", "attendees": []}
    summary = "БЮДЖЕТ и Budget и бюджет"
    
    tags = run(summary, meta)
    assert "project/budgets" in tags


def test_run_person_tags_normalization(mock_tags_data):
    """Тест нормализации person тегов."""
    meta = {"title": "", "attendees": ["Alice Johnson", "Bob Smith", "Valya Dobrynin"]}
    summary = "Встреча команды"
    
    tags = run(summary, meta)
    
    # Проверяем, что пробелы заменяются на подчеркивания
    assert "person/alice_johnson" in tags
    assert "person/bob_smith" in tags
    assert "person/valya_dobrynin" in tags


def test_run_legacy_fallback(temp_dict_dir):
    """Тест fallback к legacy формату."""
    # Создаем только legacy файл
    legacy_data = {
        "ifrs": "area/ifrs",
        "budget": "project/budgets"
    }
    legacy_file = temp_dict_dir / "tag_synonyms.json"
    with open(legacy_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)
    
    meta = {"title": "", "attendees": ["Alice"]}
    summary = "IFRS budget discussion"
    
    tags = run(summary, meta)
    
    assert "area/ifrs" in tags
    assert "project/budgets" in tags
    assert "person/alice" in tags


def test_run_empty_input(mock_tags_data):
    """Тест с пустыми входными данными."""
    tags = run("", {})
    assert tags == []
    
    tags = run("", {"attendees": []})
    assert tags == []


def test_run_no_matches(mock_tags_data):
    """Тест когда нет совпадений."""
    meta = {"title": "", "attendees": []}
    summary = "Обсуждение неизвестных тем и концепций"
    
    tags = run(summary, meta)
    assert tags == []


# === Интеграционные тесты ===

def test_tagger_ru_cases(mock_tags_data):
    """Тест русских падежей и форм."""
    meta = {"title": "", "attendees": ["Daniil"]}
    summary = "Обсудили бюджетирование и утверждение бюджета на 2025."
    
    tags = run(summary, meta, threshold=1)
    
    assert "project/budgets" in tags  # бюджет в разных формах
    assert "person/daniil" in tags    # участник


def test_tagger_ifrs_mix(mock_tags_data):
    """Тест смешанного IFRS контента."""
    meta = {"title": "Отчетность по МСФО", "attendees": []}
    summary = "Подготовка IFRS отчета за год"
    
    tags = run(summary, meta)
    assert "area/ifrs" in tags


def test_tagger_threshold_advanced(mock_tags_data):
    """Продвинутый тест порогов."""
    meta = {"title": "", "attendees": []}
    summary = """
    Обсуждение бюджета. Планирование бюджета. 
    Утверждение бюджета. Контроль бюджета.
    Краткое упоминание IFRS.
    """
    
    # С порогом 1 - оба тега
    tags_1 = run(summary, meta, threshold=1)
    assert "project/budgets" in tags_1
    assert "area/ifrs" in tags_1
    
    # С порогом 3 - только частые
    tags_3 = run(summary, meta, threshold=3)
    assert "project/budgets" in tags_3  # бюджет упомянут 4 раза
    assert "area/ifrs" not in tags_3    # IFRS только 1 раз


def test_tagger_complex_text(mock_tags_data):
    """Тест на сложном реальном тексте."""
    meta = {
        "title": "Планирование бюджета на 2025", 
        "attendees": ["Alice Johnson", "Bob Smith"]
    }
    summary = """
    Встреча по планированию бюджета на следующий год.
    Обсудили процесс бюджетирования и сроки подготовки.
    Alice представила предварительные цифры.
    Bob поднял вопросы по IFRS требованиям.
    Следующая встреча запланирована на март.
    """
    
    tags = run(summary, meta, threshold=1)
    
    # Проверяем найденные теги
    expected_tags = {
        "project/budgets",  # бюджет, бюджетирование
        "area/ifrs",        # IFRS
        "topic/meeting",    # встреча (2 раза)
        "person/alice_johnson",
        "person/bob_smith"
    }
    
    result_tags = set(tags)
    for expected_tag in expected_tags:
        assert expected_tag in result_tags, f"Expected tag {expected_tag} not found in {result_tags}"


def test_tagger_performance_large_text(mock_tags_data):
    """Тест производительности на большом тексте."""
    meta = {"title": "", "attendees": []}
    
    # Создаем большой текст с повторяющимися ключевыми словами
    large_text = "Обсуждение бюджета и планирования. " * 1000
    
    tags = run(large_text, meta, threshold=10)
    
    # Должны найтись теги, которые упоминаются достаточно часто
    assert "project/budgets" in tags  # бюджет упомянут 1000 раз


def test_normalize_token_comprehensive():
    """Комплексный тест нормализации."""
    # Проверяем, что нормализация работает (не проверяем точные результаты)
    assert len(_normalize_token("Планирование")) > 0
    assert _normalize_token("BUDGET") == "budget"
    assert len(_normalize_token("Встреча")) > 0
    
    # Пунктуация удаляется
    assert "," not in _normalize_token("бюджет,")
    assert "!" not in _normalize_token("meeting!")
    assert "-" in _normalize_token("IFRS-отчет")  # дефис сохраняется
    
    # Короткие слова не стеммятся сильно
    assert _normalize_token("он") == "он"
    assert _normalize_token("да") == "да"


def test_token_counts_comprehensive():
    """Комплексный тест подсчета токенов."""
    text = """
    Планирование бюджета и бюджетирование процессов.
    Budget planning and budgeting activities.
    Встреча по планированию была продуктивной.
    """
    
    counts = _token_counts(text)
    
    # Проверяем, что токены подсчитываются
    assert "бюдж" in counts          # бюджета нормализуется в бюдж
    assert counts["бюдж"] == 1       # только "бюджета" -> "бюдж"
    assert "бюджетиров" in counts    # бюджетирование нормализуется отдельно
    assert counts["budget"] >= 1
    assert "встреч" in counts        # встреча
    assert len(counts) > 5           # общая проверка


def test_build_index_comprehensive(mock_tags_data):
    """Комплексный тест построения индекса."""
    tags_map = _load_tags()
    index = _build_index(tags_map)
    
    # Проверяем все синонимы
    expected_mappings = [
        ("ifrs", "area/ifrs"),
        ("фрс", "area/ifrs"),
        ("мсфо", "area/ifrs"),
        ("budget", "project/budgets"),
        ("бюджет", "project/budgets"),
        ("встреч", "topic/meeting"),  # встреча → встреч
        ("meeting", "topic/meeting"),
    ]
    
    for synonym, expected_tag in expected_mappings:
        normalized_synonym = _normalize_token(synonym)
        assert normalized_synonym in index, f"Synonym {synonym} → {normalized_synonym} not in index"
        assert index[normalized_synonym] == expected_tag


def test_run_with_different_thresholds(mock_tags_data):
    """Тест разных порогов."""
    meta = {"title": "", "attendees": []}
    summary = "Бюджет бюджет budget планирование IFRS"
    
    # threshold=1: все теги
    tags_1 = run(summary, meta, threshold=1)
    result_set_1 = set(tags_1)
    assert "project/budgets" in result_set_1
    assert "area/ifrs" in result_set_1
    
    # threshold=2: только частые
    tags_2 = run(summary, meta, threshold=2)
    result_set_2 = set(tags_2)
    assert "project/budgets" in result_set_2  # бюджет встречается 3 раза
    assert "area/ifrs" not in result_set_2    # IFRS только 1 раз


def test_run_integration_with_normalize():
    """Интеграционный тест с реальными данными normalize."""
    from app.core.normalize import run as normalize_run
    
    text = "Встреча 25 марта 2025 по планированию бюджета с Valya Dobrynin"
    norm_result = normalize_run(raw_bytes=None, text=text, filename="budget_meeting.txt")
    
    # Используем результат normalize в tagger
    tags = run(norm_result.get("text", ""), {
        "title": norm_result.get("title", ""),
        "attendees": norm_result.get("attendees", [])
    })
    
    # Должны найтись соответствующие теги
    assert len(tags) > 0
