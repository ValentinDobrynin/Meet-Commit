"""Тесты для People Miner v2."""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.people_miner2 import (
    _best_snippet,
    _calculate_score,
    _is_known_person,
    approve_batch,
    approve_candidate,
    clear_candidates,
    get_candidate_stats,
    ingest_text,
    list_candidates,
    reject_batch,
    reject_candidate,
)


@pytest.fixture
def temp_candidates_file():
    """Создает временный файл для кандидатов."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = Path(f.name)

    # Патчим путь к файлу кандидатов
    with patch("app.core.people_miner2.CANDIDATES_PATH", temp_path):
        yield temp_path

    # Очищаем после теста
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def sample_candidates_data():
    """Образец данных кандидатов для тестов."""
    return {
        "Саша": {
            "first_seen": "2025-09-15",
            "last_seen": "2025-09-18",
            "freq": 7,
            "meetings": 3,
            "samples": [
                {"meeting_id": "meet1", "date": "2025-09-18", "snippet": "…Саша берёт бюджет…"},
                {"meeting_id": "meet2", "date": "2025-09-16", "snippet": "…попросим Сашу…"},
            ],
            "_meeting_ids": ["meet1", "meet2", "meet3"],
        },
        "Даня": {
            "first_seen": "2025-09-10",
            "last_seen": "2025-09-12",
            "freq": 2,
            "meetings": 1,
            "samples": [
                {"meeting_id": "meet4", "date": "2025-09-12", "snippet": "…Даня сделает отчет…"}
            ],
            "_meeting_ids": ["meet4"],
        },
    }


class TestBestSnippet:
    """Тесты для извлечения контекстных сниппетов."""

    def test_basic_snippet_extraction(self):
        """Тест базового извлечения сниппета."""
        text = "Вчера на встрече Саша сказал, что возьмет на себя подготовку отчета по бюджету."
        result = _best_snippet(text, "Саша", context_length=20)

        assert "Саша" in result
        assert "встрече" in result or "отчета" in result

    def test_snippet_with_ellipsis(self):
        """Тест добавления многоточий при обрезке."""
        text = "A" * 100 + " Саша " + "B" * 100
        result = _best_snippet(text, "Саша", context_length=10)

        assert result.startswith("…")
        assert result.endswith("…")
        assert "Саша" in result

    def test_no_match_returns_empty(self):
        """Тест возврата пустой строки при отсутствии совпадений."""
        text = "Никого нет в этом тексте"
        result = _best_snippet(text, "Саша")

        assert result == ""

    def test_case_insensitive_matching(self):
        """Тест нечувствительности к регистру."""
        text = "САША работает над проектом"
        result = _best_snippet(text, "саша")

        assert "САША" in result
        assert "проектом" in result


class TestCalculateScore:
    """Тесты для вычисления score кандидатов."""

    def test_basic_score_calculation(self):
        """Тест базового вычисления score."""
        candidate = {"freq": 5, "meetings": 2, "last_seen": "2025-09-01"}

        score = _calculate_score(candidate)
        expected = 5 + 0.5 * 2  # freq + 0.5 * meetings

        assert score == expected

    def test_recent_bonus(self):
        """Тест бонуса за свежесть."""
        today = date.today().isoformat()

        candidate = {"freq": 5, "meetings": 2, "last_seen": today}

        score = _calculate_score(candidate)
        expected = 5 + 0.5 * 2 + 2.0  # с бонусом за свежесть

        assert score == expected

    def test_invalid_date_no_bonus(self):
        """Тест отсутствия бонуса при некорректной дате."""
        candidate = {"freq": 5, "meetings": 2, "last_seen": "invalid-date"}

        score = _calculate_score(candidate)
        expected = 5 + 0.5 * 2  # без бонуса

        assert score == expected


class TestIsKnownPerson:
    """Тесты для проверки известности персоны."""

    @patch("app.core.people_miner2.load_people_raw")
    def test_known_by_name_en(self, mock_load):
        """Тест распознавания по каноническому имени."""
        mock_load.return_value = [{"name_en": "Sasha Katanov", "aliases": ["Саша", "Саша Катанов"]}]

        assert _is_known_person("Sasha Katanov") is True
        assert _is_known_person("sasha katanov") is True  # case insensitive

    @patch("app.core.people_miner2.load_people_raw")
    def test_known_by_alias(self, mock_load):
        """Тест распознавания по алиасу."""
        mock_load.return_value = [{"name_en": "Sasha Katanov", "aliases": ["Саша", "Саша Катанов"]}]

        assert _is_known_person("Саша") is True
        assert _is_known_person("саша") is True  # case insensitive

    @patch("app.core.people_miner2.load_people_raw")
    def test_unknown_person(self, mock_load):
        """Тест неизвестной персоны."""
        mock_load.return_value = [{"name_en": "Sasha Katanov", "aliases": ["Саша", "Саша Катанов"]}]

        assert _is_known_person("Неизвестный") is False


class TestIngestText:
    """Тесты для обработки текста и обновления кандидатов."""

    @patch("app.core.people_miner2.mine_alias_candidates")
    def test_ingest_new_candidates(self, mock_mine, temp_candidates_file):
        """Тест добавления новых кандидатов."""
        mock_mine.return_value = ["Новый Кандидат"]

        with patch("app.core.people_miner2._is_known_person", return_value=False):
            ingest_text(
                text="Тестовый текст с Новый Кандидат",
                meeting_id="meeting123",
                meeting_date="2025-09-20",
            )

        # Проверяем, что кандидат добавлен
        with open(temp_candidates_file, encoding="utf-8") as f:
            data = json.load(f)

        assert "Новый Кандидат" in data
        candidate = data["Новый Кандидат"]
        assert candidate["freq"] == 1
        assert candidate["meetings"] == 1
        assert "meeting123" in candidate["_meeting_ids"]

    @patch("app.core.people_miner2.mine_alias_candidates")
    def test_update_existing_candidate(
        self, mock_mine, temp_candidates_file, sample_candidates_data
    ):
        """Тест обновления существующего кандидата."""
        # Записываем исходные данные
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        mock_mine.return_value = ["Саша"]

        with patch("app.core.people_miner2._is_known_person", return_value=False):
            ingest_text(
                text="Саша работает над новым проектом",
                meeting_id="new_meeting",
                meeting_date="2025-09-21",
            )

        # Проверяем обновление
        with open(temp_candidates_file, encoding="utf-8") as f:
            data = json.load(f)

        candidate = data["Саша"]
        assert candidate["freq"] == 8  # было 7, стало 8
        assert candidate["meetings"] == 4  # было 3, стало 4
        assert "new_meeting" in candidate["_meeting_ids"]

    @patch("app.core.people_miner2.mine_alias_candidates")
    def test_skip_known_persons(self, mock_mine, temp_candidates_file):
        """Тест пропуска известных персон."""
        mock_mine.return_value = ["Известная Персона"]

        with patch("app.core.people_miner2._is_known_person", return_value=True):
            ingest_text(
                text="Текст с Известная Персона", meeting_id="meeting123", meeting_date="2025-09-20"
            )

        # Проверяем, что файл пуст или кандидат не добавлен
        if temp_candidates_file.exists():
            with open(temp_candidates_file, encoding="utf-8") as f:
                data = json.load(f)
            assert "Известная Персона" not in data
        else:
            # Файл может не создаться, если нет новых кандидатов
            assert True


class TestListCandidates:
    """Тесты для получения списка кандидатов."""

    def test_list_with_freq_sort(self, temp_candidates_file, sample_candidates_data):
        """Тест сортировки по частоте."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        items, total = list_candidates(sort="freq", page=1, per_page=10)

        assert total == 2
        assert len(items) == 2
        # Саша должен быть первым (больше freq)
        assert items[0]["alias"] == "Саша"
        assert items[1]["alias"] == "Даня"

    def test_list_with_date_sort(self, temp_candidates_file, sample_candidates_data):
        """Тест сортировки по дате."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        items, total = list_candidates(sort="date", page=1, per_page=10)

        assert total == 2
        assert len(items) == 2
        # Саша должен быть первым (более свежая дата)
        assert items[0]["alias"] == "Саша"
        assert items[1]["alias"] == "Даня"

    def test_pagination(self, temp_candidates_file, sample_candidates_data):
        """Тест пагинации."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        # Первая страница
        items, total = list_candidates(sort="freq", page=1, per_page=1)
        assert len(items) == 1
        assert total == 2
        assert items[0]["alias"] == "Саша"

        # Вторая страница
        items, total = list_candidates(sort="freq", page=2, per_page=1)
        assert len(items) == 1
        assert total == 2
        assert items[0]["alias"] == "Даня"

    def test_empty_candidates(self, temp_candidates_file):
        """Тест пустого списка кандидатов."""
        items, total = list_candidates()

        assert items == []
        assert total == 0


class TestApproveCandidate:
    """Тесты для одобрения кандидатов."""

    @patch("app.core.people_miner2.load_people_raw")
    @patch("app.core.people_miner2.save_people_raw")
    def test_approve_new_candidate(
        self, mock_save, mock_load, temp_candidates_file, sample_candidates_data
    ):
        """Тест одобрения нового кандидата."""
        # Настраиваем мок
        mock_load.return_value = []

        # Записываем кандидатов
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        # Одобряем кандидата
        result = approve_candidate("Саша", name_en="Sasha Katanov")

        assert result is True
        mock_save.assert_called_once()

        # Проверяем, что кандидат удален из списка
        with open(temp_candidates_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "Саша" not in data

    @patch("app.core.people_miner2.load_people_raw")
    @patch("app.core.people_miner2.save_people_raw")
    def test_approve_extends_existing_person(
        self, mock_save, mock_load, temp_candidates_file, sample_candidates_data
    ):
        """Тест расширения алиасов существующей персоны."""
        # Настраиваем мок - есть существующая персона
        existing_person = {"name_en": "Sasha Katanov", "aliases": ["Александр"]}
        mock_load.return_value = [existing_person]

        # Записываем кандидатов
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        # Одобряем кандидата
        result = approve_candidate("Саша", name_en="Sasha Katanov")

        assert result is True
        mock_save.assert_called_once()

        # Проверяем, что алиас добавлен
        saved_people = mock_save.call_args[0][0]
        person = saved_people[0]
        assert "Саша" in person["aliases"]
        assert "Александр" in person["aliases"]  # Старый алиас сохранен


class TestRejectCandidate:
    """Тесты для отклонения кандидатов."""

    def test_reject_existing_candidate(self, temp_candidates_file, sample_candidates_data):
        """Тест отклонения существующего кандидата."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        result = reject_candidate("Саша")

        assert result is True

        # Проверяем, что кандидат удален
        with open(temp_candidates_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "Саша" not in data
        assert "Даня" in data  # Другой кандидат остался

    def test_reject_nonexistent_candidate(self, temp_candidates_file, sample_candidates_data):
        """Тест отклонения несуществующего кандидата."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        result = reject_candidate("Несуществующий")

        assert result is False


class TestBatchOperations:
    """Тесты для батчевых операций."""

    @patch("app.core.people_miner2.approve_candidate")
    def test_approve_batch(self, mock_approve, temp_candidates_file, sample_candidates_data):
        """Тест батчевого одобрения."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        mock_approve.return_value = True

        result = approve_batch(top_n=2, sort="freq")

        assert result["selected"] == 2
        assert result["added"] == 2
        assert result["total"] == 2
        assert mock_approve.call_count == 2

    @patch("app.core.people_miner2.reject_candidate")
    def test_reject_batch(self, mock_reject, temp_candidates_file, sample_candidates_data):
        """Тест батчевого отклонения."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        mock_reject.return_value = True

        result = reject_batch(top_n=1, sort="freq")

        assert result["selected"] == 1
        assert result["removed"] == 1
        assert result["total"] == 2
        mock_reject.assert_called_once_with("Саша")  # Первый по частоте


class TestGetCandidateStats:
    """Тесты для получения статистики."""

    def test_stats_with_data(self, temp_candidates_file, sample_candidates_data):
        """Тест статистики с данными."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        stats = get_candidate_stats()

        assert stats["total"] == 2
        assert stats["avg_freq"] == 4.5  # (7 + 2) / 2
        assert stats["avg_meetings"] == 2.0  # (3 + 1) / 2
        assert stats["freq_distribution"]["high"] == 1  # Саша >= 5
        assert stats["freq_distribution"]["medium"] == 1  # Даня 2-4
        assert stats["freq_distribution"]["low"] == 0

    def test_stats_empty(self, temp_candidates_file):
        """Тест статистики с пустыми данными."""
        stats = get_candidate_stats()

        assert stats["total"] == 0
        assert stats["avg_freq"] == 0.0
        assert stats["avg_meetings"] == 0.0
        assert stats["freq_distribution"]["high"] == 0
        assert stats["freq_distribution"]["medium"] == 0
        assert stats["freq_distribution"]["low"] == 0


class TestClearCandidates:
    """Тесты для очистки кандидатов."""

    def test_clear_candidates(self, temp_candidates_file, sample_candidates_data):
        """Тест очистки всех кандидатов."""
        with open(temp_candidates_file, "w", encoding="utf-8") as f:
            json.dump(sample_candidates_data, f)

        clear_candidates()

        with open(temp_candidates_file, encoding="utf-8") as f:
            data = json.load(f)

        assert data == {}


class TestIntegration:
    """Интеграционные тесты."""

    @patch("app.core.people_miner2.mine_alias_candidates")
    @patch("app.core.people_miner2._is_known_person")
    def test_full_workflow(self, mock_is_known, mock_mine, temp_candidates_file):
        """Тест полного рабочего процесса."""
        # Настройка
        mock_mine.return_value = ["Тестовый Кандидат"]
        mock_is_known.return_value = False

        # 1. Обрабатываем текст
        ingest_text(
            text="Тестовый Кандидат работает над проектом",
            meeting_id="test_meeting",
            meeting_date="2025-09-20",
        )

        # 2. Проверяем, что кандидат добавился
        items, total = list_candidates()
        assert total == 1
        assert items[0]["alias"] == "Тестовый Кандидат"

        # 3. Получаем статистику
        stats = get_candidate_stats()
        assert stats["total"] == 1

        # 4. Одобряем кандидата
        with patch("app.core.people_miner2.load_people_raw", return_value=[]):
            with patch("app.core.people_miner2.save_people_raw") as mock_save:
                result = approve_candidate("Тестовый Кандидат")
                assert result is True
                mock_save.assert_called_once()

        # 5. Проверяем, что кандидат удален
        items, total = list_candidates()
        assert total == 0
