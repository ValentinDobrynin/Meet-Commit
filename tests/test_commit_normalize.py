"""
Тесты для модуля нормализации коммитов app.core.commit_normalize
"""

import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.commit_normalize import (
    NormalizedCommit,
    _build_alias_index,
    _infer_year_for_partial,
    _map_month,
    _safe_date,
    as_dict_list,
    build_key,
    build_title,
    normalize_assignees,
    normalize_commits,
    parse_due_iso,
    validate_date_iso,
)
from app.core.llm_extract_commits import ExtractedCommit


@pytest.fixture
def temp_dict_dir():
    """Создает временную директорию для словарей."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Патчим путь к директории словарей
        with patch("app.core.commit_normalize.load_people") as mock_load_people:
            # Настраиваем тестовые данные людей
            mock_load_people.return_value = [
                {
                    "name_en": "Valentin Dobrynin",
                    "aliases": ["Валентин", "Валя", "Valentin", "Val"],
                },
                {"name_en": "Daniil", "aliases": ["Даня", "Даниил", "Danya", "Daniil"]},
                {
                    "name_en": "Sasha Katanov",
                    "aliases": ["Саша", "Саша Катанов", "Sasha", "Katanov"],
                },
            ]
            yield temp_path


class TestDateParsing:
    """Тесты парсинга дат."""

    def test_map_month_russian(self):
        """Тест маппинга русских месяцев."""
        assert _map_month("январь") == "01"
        assert _map_month("янв") == "01"
        assert _map_month("января") == "01"
        assert _map_month("декабря") == "12"
        assert _map_month("неизвестный") is None

    def test_map_month_english(self):
        """Тест маппинга английских месяцев."""
        assert _map_month("january") == "01"
        assert _map_month("jan") == "01"
        assert _map_month("december") == "12"
        assert _map_month("dec") == "12"
        assert _map_month("unknown") is None

    def test_safe_date_valid(self):
        """Тест создания валидной даты."""
        assert _safe_date(2024, 12, 31) == "2024-12-31"
        assert _safe_date(2024, 1, 1) == "2024-01-01"

    def test_safe_date_invalid(self):
        """Тест обработки невалидной даты."""
        assert _safe_date(2024, 2, 30) is None  # 30 февраля
        assert _safe_date(2024, 13, 1) is None  # 13 месяц
        assert _safe_date(2024, 1, 32) is None  # 32 день

    def test_infer_year_for_partial_same_year(self):
        """Тест определения года для частичной даты в том же году."""
        meeting_date = date(2024, 6, 15)  # 15 июня 2024

        # Дата в будущем, но не сильно - берем тот же год
        year = _infer_year_for_partial(7, 15, meeting_date)  # 15 июля
        assert year == 2024

    def test_infer_year_for_partial_previous_year(self):
        """Тест определения года для частичной даты в прошлом году."""
        meeting_date = date(2024, 2, 15)  # 15 февраля 2024

        # Дата сильно в будущем (декабрь) - берем прошлый год
        year = _infer_year_for_partial(12, 15, meeting_date)  # 15 декабря
        assert year == 2023

    def test_parse_due_iso_formats(self):
        """Тест различных форматов дат."""
        meeting_date = "2024-06-15"

        # ISO формат
        assert parse_due_iso("до 2024-12-31", meeting_date) == "2024-12-31"

        # DMY с точками
        assert parse_due_iso("к 31.12.2024", meeting_date) == "2024-12-31"

        # DMY со слэшами
        assert parse_due_iso("до 31/12/2024", meeting_date) == "2024-12-31"

        # Частичная дата (декабрь далеко в будущем от июня - берется прошлый год)
        assert parse_due_iso("до 31.12", meeting_date) == "2023-12-31"

    def test_parse_due_russian_months(self):
        """Тест парсинга русских названий месяцев."""
        meeting_date = "2024-06-15"

        assert parse_due_iso("до 31 декабря 2024", meeting_date) == "2024-12-31"
        assert parse_due_iso("к 15 марта 2024", meeting_date) == "2024-03-15"
        assert parse_due_iso("до 1 янв 2025", meeting_date) == "2025-01-01"

    def test_parse_due_english_months(self):
        """Тест парсинга английских названий месяцев."""
        meeting_date = "2024-06-15"

        assert parse_due_iso("by December 31, 2024", meeting_date) == "2024-12-31"
        assert parse_due_iso("until Mar 15 2024", meeting_date) == "2024-03-15"
        assert parse_due_iso("by Jan 1", meeting_date) == "2024-01-01"  # без года

    def test_parse_due_no_date(self):
        """Тест отсутствия даты в тексте."""
        meeting_date = "2024-06-15"

        assert parse_due_iso("сделать задачу", meeting_date) is None
        assert parse_due_iso("", meeting_date) is None
        assert parse_due_iso("как можно скорее", meeting_date) is None

    def test_parse_due_invalid_date(self):
        """Тест невалидных дат."""
        meeting_date = "2024-06-15"

        # 30 февраля
        assert parse_due_iso("до 30.02.2024", meeting_date) is None

        # 32 день
        assert parse_due_iso("до 32.12.2024", meeting_date) is None


class TestAssigneeNormalization:
    """Тесты нормализации исполнителей."""

    def test_build_alias_index(self, temp_dict_dir):
        """Тест построения индекса алиасов."""
        index = _build_alias_index()

        assert "валентин" in index
        assert index["валентин"] == "Valentin Dobrynin"
        assert "valentin" in index
        assert index["valentin"] == "Valentin Dobrynin"
        assert "даня" in index
        assert index["даня"] == "Daniil"

    def test_normalize_assignees_canonical_names(self, temp_dict_dir):
        """Тест нормализации канонических имен."""
        assignees = ["Valentin", "Daniil"]
        attendees = ["Valentin Dobrynin", "Daniil", "Sasha Katanov"]

        result = normalize_assignees(assignees, attendees)
        assert result == ["Valentin Dobrynin", "Daniil"]

    def test_normalize_assignees_aliases(self, temp_dict_dir):
        """Тест нормализации алиасов."""
        assignees = ["Валентин", "Даня", "Саша"]
        attendees = ["Valentin Dobrynin", "Daniil", "Sasha Katanov"]

        result = normalize_assignees(assignees, attendees)
        assert result == ["Valentin Dobrynin", "Daniil", "Sasha Katanov"]

    def test_normalize_assignees_filter_non_attendees(self, temp_dict_dir):
        """Тест фильтрации неучастников встречи."""
        assignees = ["Valentin", "Unknown Person"]
        attendees = ["Daniil"]  # Valentin не участвовал

        result = normalize_assignees(assignees, attendees)
        assert result == []  # Valentin отфильтрован, Unknown не найден

    def test_normalize_assignees_deduplication(self, temp_dict_dir):
        """Тест дедупликации исполнителей."""
        assignees = ["Валентин", "Valentin", "Val"]  # все ссылаются на одного человека
        attendees = ["Valentin Dobrynin", "Daniil"]

        result = normalize_assignees(assignees, attendees)
        assert result == ["Valentin Dobrynin"]  # только один раз

    def test_normalize_assignees_empty_input(self, temp_dict_dir):
        """Тест пустого входа."""
        result = normalize_assignees([], ["Valentin Dobrynin"])
        assert result == []

        result = normalize_assignees(["", "  ", None], ["Valentin Dobrynin"])
        assert result == []


class TestTitleAndKey:
    """Тесты генерации заголовков и ключей."""

    def test_build_title_with_assignee(self):
        """Тест создания заголовка с исполнителем."""
        title = build_title("theirs", "Подготовить отчет", ["Daniil"], "2024-12-31")
        assert title == "Daniil: Подготовить отчет [due 2024-12-31]"

    def test_build_title_mine_without_assignee(self):
        """Тест создания заголовка для 'mine' без исполнителя."""
        title = build_title("mine", "Сделать задачу", [], None)
        assert title == "Valentin: Сделать задачу"

    def test_build_title_theirs_without_assignee(self):
        """Тест создания заголовка для 'theirs' без исполнителя."""
        title = build_title("theirs", "Проверить данные", [], None)
        assert title == "Unassigned: Проверить данные"

    def test_build_title_long_text(self):
        """Тест обрезания длинного текста."""
        long_text = "Очень длинный текст задачи " * 10  # > 80 символов
        title = build_title("mine", long_text, [], None)
        assert len(title.split(": ", 1)[1]) <= 80  # после "Valentin: "

    def test_build_title_multiline_text(self):
        """Тест обработки многострочного текста."""
        text = "Первая строка\nВторая строка\nТретья строка"
        title = build_title("mine", text, [], None)
        assert "\n" not in title
        assert "Первая строка Вторая строка Третья строка" in title

    def test_build_key_deterministic(self):
        """Тест детерминированности ключей."""
        key1 = build_key("Задача", ["Valentin"], "2024-12-31")
        key2 = build_key("Задача", ["Valentin"], "2024-12-31")
        assert key1 == key2

    def test_build_key_different_inputs(self):
        """Тест различных ключей для разных входов."""
        key1 = build_key("Задача 1", ["Valentin"], None)
        key2 = build_key("Задача 2", ["Valentin"], None)
        key3 = build_key("Задача 1", ["Daniil"], None)
        key4 = build_key("Задача 1", ["Valentin"], "2024-12-31")

        assert key1 != key2  # разный текст
        assert key1 != key3  # разные исполнители
        assert key1 != key4  # разные дедлайны

    def test_build_key_normalized_text(self):
        """Тест нормализации текста в ключе."""
        key1 = build_key("  Задача  с  пробелами  ", ["Valentin"], None)
        key2 = build_key("Задача с пробелами", ["Valentin"], None)
        assert key1 == key2

    def test_build_key_sorted_assignees(self):
        """Тест сортировки исполнителей в ключе."""
        key1 = build_key("Задача", ["Valentin", "Daniil"], None)
        key2 = build_key("Задача", ["Daniil", "Valentin"], None)
        assert key1 == key2  # порядок не важен


class TestNormalizeCommits:
    """Тесты основной функции нормализации."""

    def test_normalize_commits_basic(self, temp_dict_dir):
        """Базовый тест нормализации коммитов."""
        commits = [
            ExtractedCommit(
                text="Подготовить отчет",
                direction="theirs",
                assignees=["Даня"],
                confidence=0.8,
                flags=["explicit_assignee"],
            )
        ]
        attendees = ["Valentin Dobrynin", "Daniil"]
        meeting_date = "2024-06-15"

        result = normalize_commits(commits, attendees, meeting_date)

        assert len(result) == 1
        assert result[0].text == "Подготовить отчет"
        assert result[0].direction == "theirs"
        assert result[0].assignees == ["Daniil"]
        assert result[0].confidence == 0.8
        assert result[0].title == "Daniil: Подготовить отчет"
        assert result[0].key is not None

    def test_normalize_commits_with_due_in_text(self, temp_dict_dir):
        """Тест извлечения дедлайна из текста."""
        commits = [ExtractedCommit(text="Сделать до 31.12.2024", direction="mine", confidence=0.7)]
        attendees = ["Valentin Dobrynin"]
        meeting_date = "2024-06-15"

        result = normalize_commits(commits, attendees, meeting_date)

        assert result[0].due_iso == "2024-12-31"
        assert "[due 2024-12-31]" in result[0].title

    def test_normalize_commits_mine_fill_owner(self, temp_dict_dir):
        """Тест подстановки владельца для 'mine' коммитов."""
        commits = [ExtractedCommit(text="Я сделаю это", direction="mine", confidence=0.9)]
        attendees = ["Valentin Dobrynin", "Daniil"]
        meeting_date = "2024-06-15"

        result = normalize_commits(
            commits, attendees, meeting_date, fill_mine_owner="Valentin Dobrynin"
        )

        assert result[0].assignees == ["Valentin Dobrynin"]
        assert result[0].title.startswith("Valentin Dobrynin:")

    def test_normalize_commits_with_context_due(self, temp_dict_dir):
        """Тест извлечения дедлайна из контекста."""
        commits = [
            ExtractedCommit(
                text="Подготовить презентацию",
                direction="mine",
                context="Нужно подготовить презентацию до 15 марта",
                confidence=0.8,
            )
        ]
        attendees = ["Valentin Dobrynin"]
        meeting_date = "2024-02-15"

        result = normalize_commits(commits, attendees, meeting_date)

        assert result[0].due_iso == "2024-03-15"

    def test_normalize_commits_existing_due_priority(self, temp_dict_dir):
        """Тест приоритета существующего due_iso над парсингом."""
        commits = [
            ExtractedCommit(
                text="Сделать до 31.12.2024",  # дата в тексте
                direction="mine",
                due_iso="2024-11-30",  # уже установленная дата
                confidence=0.8,
            )
        ]
        attendees = ["Valentin Dobrynin"]
        meeting_date = "2024-06-15"

        result = normalize_commits(commits, attendees, meeting_date)

        # Должна остаться оригинальная дата
        assert result[0].due_iso == "2024-11-30"

    def test_normalize_commits_empty_list(self, temp_dict_dir):
        """Тест пустого списка коммитов."""
        result = normalize_commits([], ["Valentin Dobrynin"], "2024-06-15")
        assert result == []

    def test_normalize_commits_preserve_fields(self, temp_dict_dir):
        """Тест сохранения всех полей из оригинального коммита."""
        commits = [
            ExtractedCommit(
                text="Тестовая задача",
                direction="theirs",
                assignees=["Daniil"],
                confidence=0.75,
                flags=["test_flag"],
                context="Контекст задачи",
                reasoning="Причина классификации",
            )
        ]
        attendees = ["Daniil"]
        meeting_date = "2024-06-15"

        result = normalize_commits(commits, attendees, meeting_date)

        assert result[0].confidence == 0.75
        assert result[0].flags == ["test_flag"]
        assert result[0].context == "Контекст задачи"
        assert result[0].reasoning == "Причина классификации"
        assert result[0].tags == []  # пустой по умолчанию
        assert result[0].status == "open"  # статус по умолчанию


class TestUtilityFunctions:
    """Тесты вспомогательных функций."""

    def test_as_dict_list(self):
        """Тест конвертации в список словарей."""
        commits = [
            NormalizedCommit(
                text="Тест",
                direction="mine",
                assignees=["Test"],
                due_iso=None,
                confidence=0.8,
                flags=[],
                context=None,
                reasoning=None,
                title="Test: Тест",
                key="test_key",
                tags=[],
            )
        ]

        result = as_dict_list(commits)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0]["text"] == "Тест"
        assert result[0]["title"] == "Test: Тест"
        assert result[0]["key"] == "test_key"

    def test_as_dict_list_empty(self):
        """Тест конвертации пустого списка."""
        result = as_dict_list([])
        assert result == []


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_normalize_commits_no_attendees(self, temp_dict_dir):
        """Тест обработки коммитов без участников встречи."""
        commits = [
            ExtractedCommit(
                text="Выполнить задачу",  # минимум 8 символов
                direction="theirs",
                assignees=["Unknown"],
                confidence=0.5,
            )
        ]
        attendees = []  # пустой список участников
        meeting_date = "2024-06-15"

        result = normalize_commits(commits, attendees, meeting_date)

        # Когда список участников пустой, исполнители не фильтруются
        # (это может быть полезно для случаев когда участники неизвестны)
        assert result[0].assignees == ["Unknown"]
        assert result[0].title == "Unknown: Выполнить задачу"

    def test_parse_due_malformed_dates(self):
        """Тест обработки некорректных дат."""
        meeting_date = "2024-06-15"

        # Несуществующие даты
        assert parse_due_iso("до 32.13.2024", meeting_date) is None
        assert parse_due_iso("до 29.02.2023", meeting_date) is None  # не високосный год

        # Некорректные форматы
        assert parse_due_iso("до 2024/13/45", meeting_date) is None
        assert parse_due_iso("до abc.def.2024", meeting_date) is None

    def test_build_title_special_characters(self):
        """Тест обработки специальных символов в заголовке."""
        text = "Задача с символами: @#$%^&*()"
        title = build_title("mine", text, [], None)
        assert "Задача с символами: @#$%^&*()" in title

    def test_build_key_unicode(self):
        """Тест генерации ключа с Unicode символами."""
        key1 = build_key("Задача с эмодзи 🚀", ["Тест"], None)
        key2 = build_key("Задача с эмодзи 🚀", ["Тест"], None)
        assert key1 == key2
        assert len(key1) == 64  # SHA256 hex length


# ====== Тесты для validate_date_iso ======


def test_validate_date_iso_valid():
    """Тест валидации корректных ISO дат"""
    assert validate_date_iso("2024-12-31") == "2024-12-31"
    assert validate_date_iso("2025-01-01") == "2025-01-01"
    assert validate_date_iso("2024-02-29") == "2024-02-29"  # Високосный год


def test_validate_date_iso_invalid():
    """Тест валидации некорректных дат"""
    assert validate_date_iso("2023-02-29") is None  # Не високосный год
    assert validate_date_iso("2024-13-01") is None  # Несуществующий месяц
    assert validate_date_iso("2024-12-32") is None  # Несуществующий день
    assert validate_date_iso("31/12/2024") is None  # Неправильный формат
    assert validate_date_iso("2024/12/31") is None  # Неправильный формат
    assert validate_date_iso("Dec 31, 2024") is None  # Неправильный формат


def test_validate_date_iso_empty():
    """Тест валидации пустых значений"""
    assert validate_date_iso("") is None
    assert validate_date_iso("   ") is None
    assert validate_date_iso(None) is None


def test_validate_date_iso_whitespace():
    """Тест валидации с пробелами"""
    assert validate_date_iso("  2024-12-31  ") == "2024-12-31"
    assert validate_date_iso("\t2025-01-01\n") == "2025-01-01"
