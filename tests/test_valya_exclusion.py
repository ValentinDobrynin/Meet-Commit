"""
Тест исключения Valya Dobrynin из agenda кнопок.
"""

from unittest.mock import patch

import pytest

from app.core.people_activity import (
    get_fallback_top_people,
    get_other_people,
    get_top_people_by_activity,
)


class TestValyaExclusionFromAgenda:
    """Тесты исключения Valya Dobrynin из системы agenda."""

    @patch("app.gateways.notion_commits.query_commits_all")
    def test_valya_excluded_from_top_people(self, mock_query):
        """Valya Dobrynin исключается из топ людей."""
        # Мокаем данные где Valya Dobrynin самый активный
        mock_query.return_value = [
            {"assignees": ["Valya Dobrynin"], "from_person": ["Valya Dobrynin"]},
            {"assignees": ["Nodari Kezua"], "from_person": ["Sergey Lompa"]},
        ]

        from app.core.people_activity import clear_people_activity_cache

        clear_people_activity_cache()

        result = get_top_people_by_activity(min_count=1, max_count=5)

        # Valya Dobrynin не должен быть в результате
        assert "Valya Dobrynin" not in result
        assert "Valentin Dobrynin" not in result
        assert "Valentin" not in result
        assert "Валентин" not in result
        assert "Валя" not in result
        assert "Val" not in result

        # Должны быть другие люди
        assert "Nodari Kezua" in result
        assert "Sergey Lompa" in result

    @patch("app.gateways.notion_commits.query_commits_all")
    def test_valya_excluded_from_other_people(self, mock_query):
        """Valya Dobrynin исключается из other people."""
        mock_query.return_value = [
            {"assignees": ["Valya Dobrynin"], "from_person": ["Daniil"]},
            {"assignees": ["Alice"], "from_person": ["Bob"]},
        ]

        from app.core.people_activity import clear_people_activity_cache

        clear_people_activity_cache()

        # Получаем топ (без Valya Dobrynin)
        top_people = get_top_people_by_activity(min_count=1, max_count=5)

        # Получаем остальных людей
        other_people = get_other_people(exclude_top=top_people)

        # Valya Dobrynin не должен быть ни в топе, ни в остальных
        assert "Valya Dobrynin" not in top_people
        assert "Valya Dobrynin" not in other_people
        assert "Valentin Dobrynin" not in other_people
        assert "Valentin" not in other_people

    def test_fallback_excludes_valya(self):
        """Fallback список не содержит Valya Dobrynin."""
        fallback_people = get_fallback_top_people()

        # Valya Dobrynin не должен быть в fallback
        assert "Valya Dobrynin" not in fallback_people
        assert "Valentin Dobrynin" not in fallback_people
        assert "Valentin" not in fallback_people

        # Должны быть другие люди
        assert "Nodari Kezua" in fallback_people
        assert "Sergey Lompa" in fallback_people
        assert len(fallback_people) >= 3  # Должно быть достаточно людей

    def test_all_valya_aliases_excluded(self):
        """Все алиасы Valya Dobrynin исключаются."""
        from app.core.people_activity import _extract_people_from_commits

        # Создаем коммиты со всеми алиасами Valya
        commits = [
            {"assignees": ["Valya Dobrynin"], "from_person": []},
            {"assignees": ["Valentin Dobrynin"], "from_person": []},
            {"assignees": ["Valentin"], "from_person": []},
            {"assignees": ["Валентин"], "from_person": []},
            {"assignees": ["Валя"], "from_person": []},
            {"assignees": ["Val"], "from_person": []},
            {"assignees": ["Nodari Kezua"], "from_person": []},  # Контрольный
        ]

        # Извлекаем статистику (с нормализацией)
        _extract_people_from_commits(commits)

        # Получаем топ людей
        from app.core.people_activity import clear_people_activity_cache

        clear_people_activity_cache()

        # Мокаем query_commits_all чтобы использовать наши тестовые данные
        with patch("app.gateways.notion_commits.query_commits_all", return_value=commits):
            top_people = get_top_people_by_activity(min_count=1, max_count=10)

        # Все алиасы Valya должны быть исключены
        valya_aliases = {
            "Valya Dobrynin",
            "Valentin Dobrynin",
            "Valentin",
            "Валентин",
            "Валя",
            "Val",
        }
        for alias in valya_aliases:
            assert alias not in top_people, f"Alias '{alias}' should be excluded from agenda"

        # Nodari должен присутствовать
        assert "Nodari Kezua" in top_people

    def test_agenda_ui_integration(self):
        """Интеграционный тест: agenda UI не содержит Valya Dobrynin."""
        # Тестируем что keyboard builder не включает Valya Dobrynin
        from app.bot.handlers_agenda import _build_people_keyboard

        # Мокаем get_top_people_by_activity
        with patch("app.core.people_activity.get_top_people_by_activity") as mock_top:
            with patch("app.core.people_activity.get_other_people") as mock_other:
                # Возвращаем список без Valya Dobrynin
                mock_top.return_value = ["Nodari Kezua", "Sergey Lompa"]
                mock_other.return_value = ["Alice", "Bob"]

                keyboard = _build_people_keyboard()

                # Проверяем что в клавиатуре нет кнопок с Valya Dobrynin
                button_texts = []
                for row in keyboard.inline_keyboard:
                    for button in row:
                        button_texts.append(button.text)

                # Не должно быть кнопок с Valya Dobrynin
                valya_aliases = [
                    "Valya Dobrynin",
                    "Valentin Dobrynin",
                    "Valentin",
                    "Валентин",
                    "Валя",
                    "Val",
                ]
                for alias in valya_aliases:
                    assert not any(
                        alias in text for text in button_texts
                    ), f"Found '{alias}' in agenda buttons"

                # Должны быть другие люди
                assert any("Nodari Kezua" in text for text in button_texts)
                assert any("Sergey Lompa" in text for text in button_texts)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
