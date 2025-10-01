"""
Тесты для модуля дедупликации тегов app/core/tags_dedup.py

Покрывает:
- Базовую дедупликацию с приоритетом v1
- Специальную обработку People/* тегов
- Детерминированную сортировку
- Метрики процесса дедупликации
- Валидацию форматов тегов
"""

from app.core.tags_dedup import (
    FAMILIES,
    DedupMetrics,
    _family_priority,
    dedup_fuse,
    get_tag_statistics,
    validate_tag_format,
)


class TestDedupFuse:
    """Тесты основной функции дедупликации."""

    def test_basic_deduplication(self):
        """Тест базовой дедупликации без конфликтов."""
        v0 = ["Finance/Budget", "Topic/Planning"]
        v1 = ["Business/Lavka", "Projects/Integration"]

        result, metrics = dedup_fuse(v0, v1)

        assert len(result) == 4
        assert "Finance/Budget" in result
        assert "Topic/Planning" in result
        assert "Business/Lavka" in result
        assert "Projects/Integration" in result

        assert metrics.total_v0 == 2
        assert metrics.total_v1 == 2
        assert metrics.unique_result == 4
        assert metrics.conflicts_resolved == 0

    def test_conflict_resolution_v1_priority(self):
        """Тест разрешения конфликтов с приоритетом v1."""
        v0 = ["Finance/Budget", "Topic/Planning"]
        v1 = ["Finance/Budget", "Business/Lavka"]  # Finance/Budget конфликтует

        result, metrics = dedup_fuse(v0, v1)

        assert len(result) == 3
        assert "Finance/Budget" in result  # v1 версия остается
        assert "Topic/Planning" in result  # уникальный v0
        assert "Business/Lavka" in result  # уникальный v1

        assert metrics.conflicts_resolved == 1
        assert metrics.v1_priority_wins == 1
        assert metrics.v0_unique_kept == 1

    def test_people_tags_preservation(self):
        """Тест сохранения всех People/* тегов."""
        v0 = ["People/Ivan Petrov", "Finance/Budget"]
        v1 = ["People/Ivan Petrov", "People/Maria Sidorova"]  # Дубликат People

        result, metrics = dedup_fuse(v0, v1)

        # Все People/* теги должны сохраниться
        assert "People/Ivan Petrov" in result
        assert "People/Maria Sidorova" in result
        assert "Finance/Budget" in result

        assert metrics.people_tags_preserved == 2
        assert len(result) == 3

    def test_deterministic_sorting(self):
        """Тест детерминированной сортировки по семействам."""
        v0 = ["Topic/Planning", "Finance/Budget"]
        v1 = ["Business/Lavka", "People/Ivan Petrov"]

        result1, _ = dedup_fuse(v0, v1)
        result2, _ = dedup_fuse(v0, v1)

        # Результаты должны быть идентичными
        assert result1 == result2

        # Проверяем порядок семейств: People, Business, Projects, Finance, Topic
        family_indices = {}
        for i, tag in enumerate(result1):
            for family in FAMILIES:
                if tag.startswith(family):
                    if family not in family_indices:
                        family_indices[family] = i
                    break

        # People должны быть первыми, Topic - последними
        if "People/" in family_indices and "Topic/" in family_indices:
            assert family_indices["People/"] < family_indices["Topic/"]
        if "Business/" in family_indices and "Finance/" in family_indices:
            assert family_indices["Business/"] < family_indices["Finance/"]

    def test_empty_input_handling(self):
        """Тест обработки пустых входных данных."""
        # Пустые списки
        result, metrics = dedup_fuse([], [])
        assert result == []
        assert metrics.total_v0 == 0
        assert metrics.total_v1 == 0

        # None входы
        result, metrics = dedup_fuse(None, None)
        assert result == []

        # Смешанные пустые/непустые
        result, metrics = dedup_fuse(["Finance/Budget"], [])
        assert result == ["Finance/Budget"]
        assert metrics.total_v0 == 1
        assert metrics.total_v1 == 0

    def test_invalid_tags_filtering(self):
        """Тест фильтрации невалидных тегов."""
        v0 = ["Finance/Budget", "", "  ", None, "InvalidTag"]
        v1 = ["Business/Lavka", "", "AnotherInvalid"]

        result, metrics = dedup_fuse(v0, v1)

        # Только валидные теги должны остаться
        valid_tags = [tag for tag in result if validate_tag_format(tag)]
        assert len(valid_tags) == len([tag for tag in result if "/" in tag])

        # Метрики должны отражать только валидные теги
        assert metrics.total_v0 <= 5  # Максимум входных v0
        assert metrics.total_v1 <= 3  # Максимум входных v1

    def test_complex_scenario(self):
        """Тест сложного сценария с множественными конфликтами и People/*."""
        v0 = [
            "Finance/Budget",
            "Topic/Planning",
            "People/Ivan Petrov",
            "Business/Lavka",
            "People/John Smith",
        ]
        v1 = [
            "Finance/Budget",
            "Finance/IFRS",
            "People/Ivan Petrov",
            "People/Maria Sidorova",
            "Projects/Integration",
        ]

        result, metrics = dedup_fuse(v0, v1)

        # Проверяем наличие всех ожидаемых тегов
        expected_tags = {
            "Finance/Budget",  # v1 приоритет
            "Finance/IFRS",  # уникальный v1
            "Topic/Planning",  # уникальный v0
            "Business/Lavka",  # уникальный v0
            "Projects/Integration",  # уникальный v1
            "People/Ivan Petrov",  # People/* сохранен
            "People/John Smith",  # People/* сохранен
            "People/Maria Sidorova",  # People/* сохранен
        }

        assert set(result) == expected_tags
        assert metrics.conflicts_resolved >= 1  # Finance/Budget конфликт
        assert metrics.people_tags_preserved == 3  # Все People/* теги

    def test_metrics_accuracy(self):
        """Тест точности метрик."""
        v0 = ["Finance/Budget", "Topic/Planning", "People/Ivan"]
        v1 = ["Finance/Budget", "Business/Lavka"]  # 1 конфликт

        result, metrics = dedup_fuse(v0, v1)

        assert metrics.total_v0 == 3
        assert metrics.total_v1 == 2
        assert metrics.unique_result == len(result)
        assert metrics.conflicts_resolved == 1
        assert metrics.v1_priority_wins == 1
        assert metrics.v0_unique_kept == 1  # Topic/Planning (People/Ivan не считается)
        assert metrics.people_tags_preserved == 1
        assert metrics.processing_time_ms > 0


class TestDedupMetrics:
    """Тесты класса метрик."""

    def test_metrics_initialization(self):
        """Тест инициализации метрик."""
        metrics = DedupMetrics()

        assert metrics.total_v0 == 0
        assert metrics.total_v1 == 0
        assert metrics.unique_result == 0
        assert metrics.conflicts_resolved == 0
        assert metrics.processing_time_ms == 0.0

    def test_metrics_as_dict(self):
        """Тест преобразования метрик в словарь."""
        metrics = DedupMetrics()
        metrics.total_v0 = 5
        metrics.total_v1 = 3
        metrics.conflicts_resolved = 2

        result = metrics.as_dict()

        assert isinstance(result, dict)
        assert result["input"]["v0_tags"] == 5
        assert result["input"]["v1_tags"] == 3
        assert result["conflicts"]["resolved"] == 2
        assert "performance" in result
        assert "preserved" in result


class TestTagValidation:
    """Тесты валидации тегов."""

    def test_valid_tag_formats(self):
        """Тест валидных форматов тегов."""
        valid_tags = [
            "Finance/Budget",
            "Business/Lavka",
            "People/Ivan Petrov",
            "Projects/Integration",
            "Topic/Planning",
        ]

        for tag in valid_tags:
            assert validate_tag_format(tag), f"Tag should be valid: {tag}"

    def test_invalid_tag_formats(self):
        """Тест невалидных форматов тегов."""
        invalid_tags = [
            "",  # Пустая строка
            "Finance",  # Нет подкатегории
            "/Budget",  # Нет категории
            "Finance/",  # Пустая подкатегория
            "/",  # Только слеш
            "Finance/Budget/Extra",  # Слишком много уровней
            "InvalidCategory/Test",  # Неизвестная категория
            None,  # None
            123,  # Не строка
        ]

        for tag in invalid_tags:
            assert not validate_tag_format(tag), f"Tag should be invalid: {tag}"

    def test_known_categories(self):
        """Тест проверки известных категорий."""
        # Все категории из FAMILIES должны быть валидными
        for family in FAMILIES:
            category = family.rstrip("/")
            tag = f"{category}/Test"
            assert validate_tag_format(tag), f"Category should be valid: {category}"


class TestTagStatistics:
    """Тесты статистики тегов."""

    def test_empty_tags_statistics(self):
        """Тест статистики для пустого списка."""
        stats = get_tag_statistics([])

        assert stats["total"] == 0
        assert stats["valid"] == 0
        assert stats["invalid"] == 0
        assert stats["by_family"] == {}

    def test_mixed_tags_statistics(self):
        """Тест статистики для смешанного списка тегов."""
        tags = [
            "Finance/Budget",  # Валидный
            "Business/Lavka",  # Валидный
            "InvalidTag",  # Невалидный
            "People/Ivan Petrov",  # Валидный
            "",  # Невалидный
            "Topic/Planning",  # Валидный
        ]

        stats = get_tag_statistics(tags)

        assert stats["total"] == 6
        assert stats["valid"] == 4
        assert stats["invalid"] == 2

        expected_families = {"Finance": 1, "Business": 1, "People": 1, "Topic": 1}
        assert stats["by_family"] == expected_families

    def test_family_counting(self):
        """Тест подсчета по семействам."""
        tags = [
            "Finance/Budget",
            "Finance/IFRS",
            "Business/Lavka",
            "People/Ivan",
            "People/Maria",
            "People/John",
        ]

        stats = get_tag_statistics(tags)

        assert stats["by_family"]["Finance"] == 2
        assert stats["by_family"]["Business"] == 1
        assert stats["by_family"]["People"] == 3


class TestFamilyPriority:
    """Тесты приоритизации семейств."""

    def test_known_families_priority(self):
        """Тест приоритетов известных семейств."""
        # Проверяем правильный порядок приоритетов
        priorities = [
            _family_priority("People/Test"),
            _family_priority("Business/Test"),
            _family_priority("Projects/Test"),
            _family_priority("Finance/Test"),
            _family_priority("Topic/Test"),
        ]

        # Должны быть в возрастающем порядке
        assert priorities == sorted(priorities)

        # People должны иметь наивысший приоритет (0)
        assert _family_priority("People/Test") == 0

        # Topic должны иметь самый низкий приоритет среди известных
        assert _family_priority("Topic/Test") == len(FAMILIES) - 1

    def test_unknown_family_priority(self):
        """Тест приоритета неизвестных семейств."""
        unknown_priority = _family_priority("Unknown/Test")
        known_priority = _family_priority("Finance/Test")

        # Неизвестные семейства должны быть в конце
        assert unknown_priority > known_priority
        assert unknown_priority == len(FAMILIES)


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_whitespace_handling(self):
        """Тест обработки пробелов."""
        v0 = ["  Finance/Budget  ", "\t\nTopic/Planning\t\n"]
        v1 = ["Business/Lavka", "  "]

        result, metrics = dedup_fuse(v0, v1)

        # Пробелы должны быть обрезаны, пустые строки отфильтрованы
        assert "Finance/Budget" in result
        assert "Topic/Planning" in result
        assert "Business/Lavka" in result
        assert "" not in result
        assert "  " not in result

    def test_case_sensitivity(self):
        """Тест чувствительности к регистру."""
        v0 = ["finance/budget"]  # Неправильный регистр
        v1 = ["Finance/Budget"]  # Правильный регистр

        result, metrics = dedup_fuse(v0, v1)

        # Существующая система нормализации может привести к конфликту
        # В этом случае v1 имеет приоритет
        assert "Finance/Budget" in result
        assert len(result) >= 1  # Минимум v1 тег должен остаться

    def test_large_input_performance(self):
        """Тест производительности на больших входных данных."""
        # Создаем большие списки тегов
        v0 = [f"Finance/Budget{i}" for i in range(100)]
        v1 = [f"Business/Lavka{i}" for i in range(100)]

        result, metrics = dedup_fuse(v0, v1)

        assert len(result) == 200  # Нет конфликтов
        assert metrics.processing_time_ms < 100  # Должно быть быстро
        assert metrics.total_v0 == 100
        assert metrics.total_v1 == 100

    def test_duplicate_people_tags(self):
        """Тест дубликатов в People/* тегах."""
        v0 = ["People/Ivan Petrov", "People/Ivan Petrov"]  # Дубликат в v0
        v1 = ["People/Ivan Petrov", "People/Maria Sidorova"]  # Дубликат между v0/v1

        result, metrics = dedup_fuse(v0, v1)

        # Дубликаты People/* должны быть удалены
        people_tags = [tag for tag in result if tag.startswith("People/")]
        assert len(people_tags) == 2  # Ivan и Maria
        assert "People/Ivan Petrov" in people_tags
        assert "People/Maria Sidorova" in people_tags

    def test_mixed_valid_invalid_tags(self):
        """Тест смешанных валидных и невалидных тегов."""
        v0 = ["Finance/Budget", "InvalidTag", "", "People/Ivan"]
        v1 = ["Business/Lavka", None, "AnotherInvalid", "Topic/Planning"]

        result, metrics = dedup_fuse(v0, v1)

        # Только валидные теги должны остаться
        for tag in result:
            assert isinstance(tag, str)
            assert tag.strip()

        # Метрики должны отражать только обработанные теги
        assert metrics.total_v0 <= 4
        assert metrics.total_v1 <= 4


class TestIntegrationWithExistingSystem:
    """Тесты интеграции с существующей системой."""

    def test_compatibility_with_normalize_for_comparison(self):
        """Тест совместимости с существующей функцией нормализации."""
        # Тест что функция нормализации импортируется и работает
        from app.core.tags_dedup import dedup_fuse

        # Теги которые должны конфликтовать по существующей логике
        v0 = ["Finance/Budget"]
        v1 = ["Finance/Budget"]  # Точный дубликат

        result, metrics = dedup_fuse(v0, v1)

        # Должен быть конфликт и приоритет v1
        assert len(result) == 1
        assert result[0] == "Finance/Budget"
        assert metrics.conflicts_resolved == 1

    def test_performance_metrics_format(self):
        """Тест формата метрик производительности."""
        v0 = ["Finance/Budget"]
        v1 = ["Business/Lavka"]

        result, metrics = dedup_fuse(v0, v1)

        # Проверяем структуру метрик
        metrics_dict = metrics.as_dict()

        assert "input" in metrics_dict
        assert "output" in metrics_dict
        assert "conflicts" in metrics_dict
        assert "preserved" in metrics_dict
        assert "performance" in metrics_dict

        # Проверяем типы значений
        assert isinstance(metrics_dict["performance"]["processing_time_ms"], int | float)
        assert metrics_dict["performance"]["processing_time_ms"] >= 0


class TestRealWorldScenarios:
    """Тесты реальных сценариев использования."""

    def test_meeting_processing_scenario(self):
        """Тест сценария обработки встречи."""
        # Типичные теги от v0 (token-based)
        v0 = ["Topic/Planning", "Finance/Budget", "People/Team Lead"]

        # Типичные теги от v1 (regex-based)
        v1 = ["Finance/IFRS", "Business/Lavka", "People/Ivan Petrov"]

        result, metrics = dedup_fuse(v0, v1)

        # Все теги должны сохраниться (нет конфликтов)
        assert len(result) == 6

        # People/* теги должны быть первыми в сортировке
        people_tags = [tag for tag in result if tag.startswith("People/")]
        last_people_index = result.index(people_tags[-1]) if people_tags else -1

        # Все остальные теги должны быть после People/*
        non_people_tags = [tag for tag in result if not tag.startswith("People/")]
        if non_people_tags and people_tags:
            first_non_people_index = result.index(non_people_tags[0])
            assert last_people_index < first_non_people_index

    def test_commit_processing_scenario(self):
        """Тест сценария обработки коммита."""
        # Коммит может наследовать теги от встречи
        meeting_tags = ["Finance/Budget", "Business/Lavka", "People/Manager"]
        commit_tags = ["Topic/Task", "People/Ivan Petrov"]

        # Симулируем что коммит получает свои теги + наследует от встречи
        result, metrics = dedup_fuse(meeting_tags, commit_tags)

        # Проверяем что все People/* теги сохранились
        people_in_result = [tag for tag in result if tag.startswith("People/")]
        assert "People/Manager" in people_in_result
        assert "People/Ivan Petrov" in people_in_result

        # Проверяем наследование других тегов
        assert "Finance/Budget" in result
        assert "Business/Lavka" in result
        assert "Topic/Task" in result
