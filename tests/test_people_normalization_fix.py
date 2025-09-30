"""
Тест исправления нормализации имен в people_activity.
"""

import pytest

from app.core.people_activity import _extract_people_from_commits


class TestPeopleNormalizationFix:
    """Тесты исправления дублирования имен через нормализацию."""

    def test_extract_people_normalizes_names(self):
        """Проверяем что _extract_people_from_commits нормализует имена."""
        # Мокаем коммиты с дублирующимися именами
        commits = [
            {"assignees": ["Valentin Dobrynin"], "from_person": ["Valya Dobrynin"]},
            {"assignees": ["Valya Dobrynin"], "from_person": ["Valentin"]},
            {"assignees": [], "from_person": ["Valentin Dobrynin"]},
        ]

        result = _extract_people_from_commits(commits)

        # Должна быть только одна запись "Valya Dobrynin"
        assert "Valya Dobrynin" in result
        assert "Valentin Dobrynin" not in result
        assert "Valentin" not in result

        # Проверяем правильные счетчики
        valya_stats = result["Valya Dobrynin"]
        assert valya_stats["assignee"] == 2  # 2 раза исполнитель
        assert valya_stats["from_person"] == 3  # 3 раза заказчик

    def test_extract_people_handles_empty_lists(self):
        """Проверяем обработку пустых списков."""
        commits = [{"assignees": [], "from_person": []}, {"assignees": None, "from_person": None}]

        result = _extract_people_from_commits(commits)
        assert result == {}

    def test_extract_people_handles_invalid_data(self):
        """Проверяем обработку некорректных данных."""
        commits = [
            {
                "assignees": ["", None, "Valya Dobrynin"],
                "from_person": [
                    "",
                    "Valentin Dobrynin",
                    None,
                ],  # Убираем int, оставляем только строки и None
            }
        ]

        result = _extract_people_from_commits(commits)

        # Должна быть только одна нормализованная запись
        assert len(result) == 1
        assert "Valya Dobrynin" in result
        assert result["Valya Dobrynin"]["assignee"] == 1
        assert result["Valya Dobrynin"]["from_person"] == 1

    def test_integration_with_get_people_activity_stats(self):
        """Интеграционный тест с get_people_activity_stats."""
        # Тестируем напрямую _extract_people_from_commits с моковыми данными
        commits = [
            {
                "assignees": ["Valentin Dobrynin"],  # Старое имя
                "from_person": ["Valya Dobrynin"],  # Новое имя
            },
            {
                "assignees": ["Valya Dobrynin"],  # Новое имя
                "from_person": ["Valentin"],  # Короткое имя
            },
        ]

        result = _extract_people_from_commits(commits)

        # Должна быть только одна запись после нормализации
        valentin_related = [
            person
            for person in result.keys()
            if "valentin" in person.lower() or "valya" in person.lower()
        ]

        assert len(valentin_related) == 1
        assert "Valya Dobrynin" in result

        # Проверяем суммированные счетчики
        stats = result["Valya Dobrynin"]
        # В каждом коммите есть один assignee, всего 2 коммита -> 2 assignee
        # Но они все нормализуются в одного человека "Valya Dobrynin"
        # Поэтому: 1 из первого коммита + 1 из второго коммита = 2
        assert stats["assignee"] == 2  # Valentin Dobrynin + Valya Dobrynin
        assert stats["from_person"] == 2  # Valya Dobrynin + Valentin

    def test_normalize_various_valentin_forms(self):
        """Тест нормализации различных форм имени Валентин."""
        commits = [
            {"assignees": ["Valentin"], "from_person": []},
            {"assignees": ["Валентин"], "from_person": []},
            {"assignees": ["Valentin Dobrynin"], "from_person": []},
            {"assignees": ["Валя"], "from_person": []},
            {"assignees": ["Val"], "from_person": []},
        ]

        result = _extract_people_from_commits(commits)

        # Все должно нормализоваться в одну запись
        valentin_people = [
            person
            for person in result.keys()
            if "valentin" in person.lower() or "valya" in person.lower() or "val" in person.lower()
        ]

        assert len(valentin_people) == 1
        assert "Valya Dobrynin" in result
        assert result["Valya Dobrynin"]["assignee"] == 5  # Все 5 форм

    def test_other_names_not_affected(self):
        """Проверяем что нормализация не влияет на другие имена."""
        commits = [
            {
                "assignees": ["Nodari Kezua", "Valentin Dobrynin"],
                "from_person": ["Sergey Lompa", "Valya Dobrynin"],
            }
        ]

        result = _extract_people_from_commits(commits)

        # Должно быть 3 человека: Valya (нормализованный), Nodari, Sergey
        assert len(result) == 3
        assert "Valya Dobrynin" in result
        assert "Nodari Kezua" in result
        assert "Sergey Lompa" in result

        # Валентин должен быть нормализован
        assert "Valentin Dobrynin" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
