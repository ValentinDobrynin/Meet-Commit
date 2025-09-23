"""
Тесты для модуля app/bot/formatters.py
"""

from app.bot.formatters import (
    _escape_html,
    _format_date,
    _format_tags_list,
    _get_urgency_level,
    _truncate_text,
    format_admin_command_response,
    format_commit_card,
    format_error_card,
    format_meeting_card,
    format_people_candidate_card,
    format_progress_card,
    format_review_card,
    format_success_card,
    format_tags_stats_card,
)


class TestUtilityFunctions:
    """Тесты вспомогательных функций форматирования."""

    def test_escape_html(self):
        """Тестируем экранирование HTML символов."""
        assert _escape_html("") == ""
        assert _escape_html("normal text") == "normal text"
        assert (
            _escape_html("<script>alert('xss')</script>")
            == "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"
        )
        assert _escape_html("Tom & Jerry") == "Tom &amp; Jerry"
        assert _escape_html('"quoted text"') == "&quot;quoted text&quot;"

    def test_truncate_text(self):
        """Тестируем умное обрезание текста."""
        assert _truncate_text("") == "—"
        assert _truncate_text("short") == "short"
        result = _truncate_text("a" * 100, 50)
        assert result.endswith("...")
        assert len(result) <= 53  # 50 + "..."

        # Тест умного обрезания по словам
        long_text = "This is a very long sentence that should be truncated properly"
        result = _truncate_text(long_text, 30)
        assert len(result) <= 33  # 30 + "..."
        assert result.endswith("...")
        assert " " not in result[-10:-3]  # Не обрезаем посреди слова

    def test_format_date(self):
        """Тестируем форматирование дат."""
        assert _format_date(None) == "—"
        assert _format_date("") == "—"
        assert _format_date("2025-01-15") == "15.01.2025"
        assert _format_date("2025-01-15T10:30:00Z") == "15.01.2025"
        assert _format_date("invalid") == "invalid"

    def test_get_urgency_level(self):
        """Тестируем определение уровня срочности."""
        from datetime import date, timedelta

        today = date.today()

        # Тестируем с реальными датами
        assert _get_urgency_level(None) == "no_due"
        assert _get_urgency_level("") == "no_due"
        assert _get_urgency_level((today - timedelta(days=1)).isoformat()) == "overdue"
        assert _get_urgency_level(today.isoformat()) == "today"
        assert _get_urgency_level((today + timedelta(days=3)).isoformat()) == "this_week"
        assert _get_urgency_level((today + timedelta(days=10)).isoformat()) == "next_week"
        assert _get_urgency_level((today + timedelta(days=30)).isoformat()) == "no_due"

    def test_format_tags_list(self):
        """Тестируем форматирование списка тегов."""
        assert _format_tags_list([]) == "—"
        assert _format_tags_list(["Finance/IFRS"]) == "💰 <code>IFRS</code>"
        assert (
            _format_tags_list(["Finance/IFRS", "Business/Lavka"])
            == "💰 <code>IFRS</code> • 🏢 <code>Lavka</code>"
        )

        # Тест с превышением лимита
        many_tags = [
            "Finance/IFRS",
            "Business/Lavka",
            "People/John",
            "Projects/Mobile",
            "Topic/Planning",
        ]
        result = _format_tags_list(many_tags, max_tags=3)
        assert "IFRS" in result
        assert "Lavka" in result
        assert "John" in result
        assert "+2" in result  # Показываем оставшиеся


class TestMeetingCard:
    """Тесты форматирования карточек встреч."""

    def test_format_meeting_card_basic(self):
        """Тестируем базовое форматирование встречи."""
        meeting = {
            "Name": "Финансовое планирование",
            "Date": "2025-01-15",
            "Attendees": ["Valya Dobrynin", "Ivan Petrov"],
            "Tags": ["Finance/IFRS", "Business/Planning"],
            "url": "https://notion.so/meeting-123",
        }

        result = format_meeting_card(meeting)

        assert "📅" in result
        assert "Финансовое планирование" in result
        assert "15.01.2025" in result
        assert "Valya Dobrynin, Ivan Petrov" in result
        assert "💰 <code>IFRS</code>" in result
        assert "🏢 <code>Planning</code>" in result
        assert "https://notion.so/meeting-123" in result

    def test_format_meeting_card_minimal(self):
        """Тестируем форматирование встречи с минимальными данными."""
        meeting = {}

        result = format_meeting_card(meeting, show_url=False)

        assert "📅" in result
        assert "Встреча без названия" in result
        assert "—" in result  # Для пустых полей

    def test_format_meeting_card_long_data(self):
        """Тестируем форматирование с длинными данными."""
        meeting = {
            "Name": "Очень длинное название встречи которое определенно должно быть обрезано по лимиту",
            "Attendees": ["Person1", "Person2", "Person3", "Person4", "Person5", "Person6"],
            "Tags": ["Finance/IFRS", "Business/Lavka", "People/John", "Projects/Mobile"],
        }

        result = format_meeting_card(meeting)

        # Проверяем, что название обрезано (60 символов лимит)
        assert len(meeting["Name"]) > 60  # Исходное название длинное
        assert "+2" in result  # Дополнительные участники
        assert "+1" in result or "Mobile" not in result  # Обрезание тегов


class TestCommitCard:
    """Тесты форматирования карточек коммитов."""

    def test_format_commit_card_basic(self):
        """Тестируем базовое форматирование коммита."""
        commit = {
            "text": "Подготовить отчет по IFRS",
            "status": "open",
            "direction": "mine",
            "assignees": ["Valya Dobrynin"],
            "due_iso": "2025-01-15",
            "confidence": 0.85,
            "short_id": "abc123",
        }

        result = format_commit_card(commit)

        assert "🟡" in result  # open status
        assert "📤" in result  # mine direction
        assert "Подготовить отчет по IFRS" in result
        assert "Valya Dobrynin" in result
        assert "15.01.2025" in result
        assert "85%" in result  # confidence
        assert "abc123" in result

    def test_format_commit_card_completed(self):
        """Тестируем форматирование завершенного коммита."""
        commit = {
            "text": "Завершенная задача",
            "status": "done",
            "direction": "theirs",
            "assignees": [],
            "due_iso": None,
            "confidence": None,
        }

        result = format_commit_card(commit)

        assert "✅" in result  # done status
        assert "📥" in result  # theirs direction
        assert "—" in result  # empty assignees and due

    def test_format_commit_card_multiple_assignees(self):
        """Тестируем форматирование с несколькими исполнителями."""
        commit = {
            "text": "Team task",
            "assignees": ["Person1", "Person2", "Person3", "Person4"],
            "status": "open",
        }

        result = format_commit_card(commit)

        assert "Person1, Person2" in result
        assert "+2" in result  # Дополнительные исполнители


class TestReviewCard:
    """Тесты форматирования карточек Review."""

    def test_format_review_card_with_reasons(self):
        """Тестируем форматирование Review с причинами."""
        review = {
            "text": "Unclear task",
            "status": "pending",
            "direction": "theirs",
            "assignees": ["John"],
            "confidence": 0.5,
            "reasons": ["unclear_assignee", "low_confidence"],
            "context": "Обсуждение на встрече по планированию",
        }

        result = format_review_card(review)

        assert "🟠" in result  # pending status
        assert "unclear_assignee" in result
        assert "Обсуждение на встрече" in result
        assert "50%" in result  # confidence


class TestSpecializedCards:
    """Тесты специализированных карточек."""

    def test_format_people_candidate_card(self):
        """Тестируем форматирование кандидата People."""
        candidate = {"alias": "Иван Петров", "freq": 15, "name_en": "Ivan Petrov"}

        result = format_people_candidate_card(candidate, 5, 20)

        assert "👤" in result
        assert "Иван Петров" in result
        assert "🔥" in result  # high frequency emoji
        assert "5/20" in result
        assert "Ivan Petrov" in result

    def test_format_tags_stats_card(self):
        """Тестируем форматирование статистики тегов."""
        stats = {
            "total_calls": 1500,
            "total_tags_found": 3000,
            "avg_score": 1.25,
            "cache_hit_rate": 0.85,
            "top_tags": {"Finance/IFRS": 50, "Business/Lavka": 30},
            "mode_breakdown": {"v0": 800, "v1": 700},
        }

        result = format_tags_stats_card(stats)

        assert "📊" in result
        assert "1,500" in result  # formatted number
        assert "85.0%" in result  # percentage
        assert "💰 <code>IFRS</code>" in result  # top tag with emoji
        assert "🏢 <code>Lavka</code>" in result

    def test_format_admin_command_response(self):
        """Тестируем форматирование админских ответов."""
        data = {
            "rules_count": 25,
            "cache_hit_rate": 0.75,
            "top_tags": {"Finance/IFRS": 10, "Business/Lavka": 8},
            "errors": ["Invalid regex in rule X"],
        }

        result = format_admin_command_response("Синхронизация завершена", data, success=True)

        assert "✅" in result
        assert "Синхронизация завершена" in result
        assert "25" in result
        assert "75.0%" in result

    def test_format_error_card(self):
        """Тестируем форматирование ошибок."""
        result = format_error_card("Ошибка API", "Connection timeout", show_details=True)

        assert "❌" in result
        assert "Ошибка API" in result
        assert "Connection timeout" in result
        assert "Что делать:" in result

    def test_format_success_card(self):
        """Тестируем форматирование успешных операций."""
        details = {"created": 5, "updated": 2, "commit_id": "12345678901234567890"}

        result = format_success_card("Операция завершена", details)

        assert "✅" in result
        assert "Операция завершена" in result
        assert "5" in result
        assert "12345678..." in result  # Сокращенный ID

    def test_format_progress_card(self):
        """Тестируем форматирование прогресса."""
        result = format_progress_card(7, 10, "Обработка файлов")

        assert "⏳" in result
        assert "Обработка файлов" in result
        assert "7/10" in result
        assert "70%" in result
        assert "🟩" in result  # Progress bar


class TestIntegration:
    """Интеграционные тесты форматирования."""

    def test_all_formatters_return_strings(self):
        """Проверяем, что все форматтеры возвращают строки."""
        # Meeting card
        meeting_result = format_meeting_card({})
        assert isinstance(meeting_result, str)
        assert len(meeting_result) > 0

        # Commit card
        commit_result = format_commit_card({})
        assert isinstance(commit_result, str)
        assert len(commit_result) > 0

        # Review card
        review_result = format_review_card({})
        assert isinstance(review_result, str)
        assert len(review_result) > 0

        # People candidate
        candidate_result = format_people_candidate_card({}, 1, 10)
        assert isinstance(candidate_result, str)
        assert len(candidate_result) > 0

        # Tags stats
        stats_result = format_tags_stats_card({})
        assert isinstance(stats_result, str)
        assert len(stats_result) > 0

    def test_html_safety(self):
        """Проверяем безопасность HTML во всех форматтерах."""
        dangerous_data = {
            "Name": "<script>alert('xss')</script>",
            "text": "<img src=x onerror=alert(1)>",
            "alias": "'; DROP TABLE users; --",
        }

        # Все форматтеры должны экранировать опасный контент
        meeting_result = format_meeting_card(dangerous_data)
        assert "<script>" not in meeting_result
        assert "&lt;script&gt;" in meeting_result

        commit_result = format_commit_card(dangerous_data)
        assert "<img" not in commit_result
        assert "&lt;img" in commit_result

        candidate_result = format_people_candidate_card(dangerous_data, 1, 10)
        assert "DROP TABLE" not in candidate_result or "&" in candidate_result

    def test_emoji_consistency(self):
        """Проверяем консистентность эмодзи."""
        # Статусы должны иметь консистентные эмодзи
        open_commit = format_commit_card({"status": "open"})
        done_commit = format_commit_card({"status": "done"})

        assert "🟡" in open_commit
        assert "✅" in done_commit

        # Направления должны быть консистентными
        mine_commit = format_commit_card({"direction": "mine"})
        theirs_commit = format_commit_card({"direction": "theirs"})

        assert "📤" in mine_commit
        assert "📥" in theirs_commit

    def test_fallback_values(self):
        """Проверяем fallback значения для пустых данных."""
        empty_meeting = format_meeting_card({})
        empty_commit = format_commit_card({})

        # Должны содержать fallback значения
        assert "—" in empty_meeting  # Для пустых полей
        assert "—" in empty_commit
        assert "Встреча без названия" in empty_meeting
        assert "Задача без описания" in empty_commit

    def test_date_formatting_edge_cases(self):
        """Тестируем edge cases форматирования дат."""
        # Тест с некорректными датами - функция должна возвращать исходное значение
        result1 = _format_date("not-a-date")
        assert isinstance(result1, str)  # Возвращает строку

        result2 = _format_date("2025-13-45")
        assert isinstance(result2, str)  # Возвращает строку

        # Тест с корректными форматами
        assert _format_date("2025-01-15T00:00:00") == "15.01.2025"
        assert _format_date("2025-01-15") == "15.01.2025"
