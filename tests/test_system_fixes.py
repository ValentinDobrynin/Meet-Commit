"""
Тесты для исправлений System заказчика и слипания исполнителей.
"""

from unittest.mock import patch

import pytest

from app.core.commit_normalize import normalize_commits
from app.core.llm_commit_parse import _apply_role_fallbacks, _split_names, parse_commit_text
from app.core.llm_extract_commits import ExtractedCommit
from app.core.people_activity import get_top_people_by_activity


class TestSystemFallbackFix:
    """Тесты исправления System заказчика на Valya Dobrynin."""

    def test_system_replaced_in_mine_commits(self):
        """System заменяется на Valya Dobrynin в mine коммитах без владельца."""
        commits = [
            ExtractedCommit(
                text="Подготовить отчет",
                direction="mine",
                assignees=["Sergey"],
                due_iso=None,
                context=None,
            )
        ]

        result = normalize_commits(
            commits,
            attendees_en=["Sergey"],
            meeting_date_iso="2025-09-29",
            fill_mine_owner="",  # Пустой владелец -> должен стать Valya Dobrynin
        )

        assert len(result) == 1
        assert result[0].from_person == ["Valya Dobrynin"]
        assert "System" not in result[0].from_person

    def test_system_replaced_in_theirs_commits(self):
        """System заменяется на Valya Dobrynin в theirs коммитах."""
        commits = [
            ExtractedCommit(
                text="Сделать презентацию",
                direction="theirs",
                assignees=["Nodari"],
                due_iso=None,
                context=None,
            )
        ]

        result = normalize_commits(commits, attendees_en=["Nodari"], meeting_date_iso="2025-09-29")

        assert len(result) == 1
        assert result[0].from_person == ["Valya Dobrynin"]
        assert "System" not in result[0].from_person

    def test_system_excluded_from_people_activity(self):
        """System исключается из рейтинга активности людей."""
        with patch("app.gateways.notion_commits.query_commits_all") as mock_query:
            # Мокаем коммиты с System
            mock_query.return_value = [
                {"assignee": ["System"], "from_person": ["System"], "text": "Системная задача"},
                {
                    "assignee": ["Valya Dobrynin"],
                    "from_person": ["Valya Dobrynin"],
                    "text": "Обычная задача",
                },
            ]

            result = get_top_people_by_activity(min_count=1, max_count=5)

            # System не должен попасть в результат
            assert "System" not in result
            # Проверяем что есть хотя бы один реальный человек
            assert len(result) > 0
            assert any(person != "System" for person in result)


class TestAssigneeSplittingFix:
    """Тесты исправления слипания исполнителей."""

    def test_split_names_comma_separated(self):
        """Разбивка имен через запятую."""
        result = _split_names("Vlad Sklyanov, Sergey Lompa")
        assert result == ["Vlad Sklyanov", "Sergey Lompa"]

    def test_split_names_russian_conjunction(self):
        """Разбивка имен через русский союз 'и'."""
        result = _split_names("Nodari Kezua и Sergey Lompa")
        assert result == ["Nodari Kezua", "Sergey Lompa"]

    def test_split_names_english_conjunction(self):
        """Разбивка имен через английские союзы."""
        test_cases = [
            ("John and Jane", ["John", "Jane"]),
            ("Alice with Bob", ["Alice", "Bob"]),
            ("Tom & Jerry", ["Tom", "Jerry"]),
            ("One + Two", ["One", "Two"]),
        ]

        for input_str, expected in test_cases:
            result = _split_names(input_str)
            assert result == expected, f"Failed for input: {input_str}"

    def test_split_names_mixed_separators(self):
        """Разбивка имен со смешанными разделителями."""
        result = _split_names("Alice, Bob и Charlie and Dave")
        assert result == ["Alice", "Bob", "Charlie", "Dave"]

    def test_split_names_empty_and_whitespace(self):
        """Обработка пустых строк и пробелов."""
        assert _split_names("") == []
        assert _split_names("   ") == []
        assert _split_names("Alice,  , Bob") == ["Alice", "Bob"]

    def test_apply_role_fallbacks_multiple_assignees(self):
        """Fallback логика корректно обрабатывает множественных исполнителей."""
        llm_result = {"assignee": "Vlad Sklyanov, Sergey Lompa", "from_person": "Valentin Dobrynin"}

        assignees, from_person, direction = _apply_role_fallbacks(llm_result, "Valentin Dobrynin")

        assert assignees == ["Vlad Sklyanov", "Sergey Lompa"]
        assert from_person == "Valentin Dobrynin"
        assert direction == "theirs"  # Пользователь не среди исполнителей

    def test_apply_role_fallbacks_user_in_assignees(self):
        """Direction = mine когда пользователь среди исполнителей."""
        llm_result = {"assignee": "Valentin Dobrynin и Sergey Lompa", "from_person": "Boss"}

        assignees, from_person, direction = _apply_role_fallbacks(llm_result, "Valentin Dobrynin")

        assert assignees == ["Valentin Dobrynin", "Sergey Lompa"]
        assert from_person == "Boss"
        assert direction == "mine"  # Пользователь среди исполнителей

    @patch("app.core.llm_commit_parse._call_llm_parse")
    def test_parse_commit_text_multiple_assignees(self, mock_llm):
        """Полный тест парсинга с множественными исполнителями."""
        mock_llm.return_value = {
            "text": "сделать презентацию",
            "assignee": "Nodari Kezua и Sergey Lompa",
            "from_person": "Valentin Dobrynin",
            "due": "2025-10-01",
            "confidence": 0.9,
        }

        result = parse_commit_text("Нодари и Ломпа сделают презентацию", "Valentin Dobrynin")

        # Проверяем что исполнители разделены
        assignees = result["assignees"]
        assert len(assignees) >= 2, f"Expected multiple assignees, got: {assignees}"

        # Проверяем что нет слипания (нет запятых внутри имен)
        for assignee in assignees:
            assert "," not in assignee, f"Found comma in assignee: {assignee}"
            assert " и " not in assignee, f"Found 'и' in assignee: {assignee}"

    def test_edge_cases(self):
        """Граничные случаи."""
        # Одно имя не должно разбиваться
        assert _split_names("Single Name") == ["Single Name"]

        # Пустые части фильтруются
        assert _split_names("Alice,,,Bob") == ["Alice", "Bob"]

        # Множественные пробелы
        assert _split_names("Alice   и   Bob") == ["Alice", "Bob"]


class TestIntegrationFixes:
    """Интеграционные тесты исправлений."""

    @patch("app.core.llm_commit_parse._call_llm_parse")
    def test_no_system_in_llm_commits(self, mock_llm):
        """LLM коммиты не создают System заказчиков."""
        mock_llm.return_value = {
            "text": "системная задача",
            "assignee": None,  # Пустой исполнитель
            "from_person": None,  # Пустой заказчик
            "due": None,
            "confidence": 0.5,
        }

        result = parse_commit_text("системная задача", "Valya Dobrynin")

        # Fallback должен использовать пользователя, а не System
        assert "System" not in result["from_person"]
        assert "Valya Dobrynin" in result["from_person"]

    def test_realistic_scenario(self):
        """Реалистичный сценарий с извлеченными коммитами."""
        commits = [
            ExtractedCommit(
                text="Финализировать цифры по деликатуре",
                direction="theirs",
                assignees=["Nodari Kezua", "Sergey Lompa"],
                due_iso=None,
                context="встреча по планированию",
            )
        ]

        result = normalize_commits(
            commits, attendees_en=["Nodari Kezua", "Sergey Lompa"], meeting_date_iso="2025-09-29"
        )

        assert len(result) == 1
        commit = result[0]

        # Заказчик должен быть Valya Dobrynin, а не System
        assert commit.from_person == ["Valya Dobrynin"]
        assert "System" not in commit.from_person

        # Исполнители должны быть корректными
        assert len(commit.assignees) == 2
        assert "Nodari Kezua" in commit.assignees
        assert "Sergey Lompa" in commit.assignees


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
