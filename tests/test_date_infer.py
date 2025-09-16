from datetime import date

from app.core.normalize import _infer_date_from_text, _infer_meeting_date


def test_infer_date_from_filename_full():
    """Тест извлечения полной даты из имени файла."""
    iso = _infer_meeting_date("09_04_2025_Встреча.txt", "")
    assert iso == "2025-04-09"


def test_infer_date_from_filename_no_year():
    """Тест извлечения даты без года из имени файла."""
    iso = _infer_meeting_date("09_04_Встреча.txt", "Шапка")
    # проверим только окончание: -04-09
    assert iso.endswith("-04-09")


def test_infer_date_from_text():
    """Тест извлечения даты из текста."""
    iso = _infer_meeting_date("meeting.txt", "Дата встречи: 25.03.2025")
    assert iso == "2025-03-25"


def test_infer_date_russian_month():
    """Тест извлечения даты с русскими названиями месяцев."""
    iso = _infer_meeting_date("meeting.txt", "Встреча состоялась 15 марта 2024 года")
    assert iso == "2024-03-15"


def test_infer_date_russian_month_short():
    """Тест извлечения даты с сокращенными русскими месяцами."""
    iso = _infer_meeting_date("meeting.txt", "Дата: 20 дек 2023")
    assert iso == "2023-12-20"


def test_infer_date_different_formats():
    """Тест различных форматов дат."""
    test_cases = [
        ("2024-12-25_meeting.txt", "", "2024-12-25"),
        ("meeting_25.12.2024.txt", "", "2024-12-25"),
        ("meeting.txt", "Встреча 25-12-2024", "2024-12-25"),
        ("meeting.txt", "Дата: 25 декабря 2024", "2024-12-25"),
    ]

    for filename, text, expected in test_cases:
        iso = _infer_meeting_date(filename, text)
        assert iso == expected, f"Failed for {filename}, {text}"


def test_infer_date_fallback_to_today():
    """Тест fallback на текущую дату."""
    iso = _infer_meeting_date("meeting.txt", "Обычный текст без дат")
    today = date.today().isoformat()
    assert iso == today


def test_infer_date_future_date_handling():
    """Тест обработки будущих дат без года."""
    # Если сегодня 15 января 2024, то 20 декабря без года должно быть 2023
    iso = _infer_meeting_date("20_12_meeting.txt", "")
    # Проверяем, что дата в прошлом году
    assert iso.endswith("-12-20")
    year = int(iso.split("-")[0])
    current_year = date.today().year
    assert year <= current_year


def test_infer_date_invalid_date():
    """Тест обработки невалидных дат."""
    # 32 день не существует
    iso = _infer_meeting_date("32_01_2024_meeting.txt", "")
    # Должен fallback на сегодня
    today = date.today().isoformat()
    assert iso == today


def test_infer_date_from_text_function():
    """Тест функции _infer_date_from_text напрямую."""
    assert _infer_date_from_text("25.03.2024") == date(2024, 3, 25)
    assert _infer_date_from_text("2024-03-25") == date(2024, 3, 25)
    assert _infer_date_from_text("25 марта 2024") == date(2024, 3, 25)
    assert _infer_date_from_text("25 мар 2024") == date(2024, 3, 25)
    assert _infer_date_from_text("25.03") is not None  # без года
    assert _infer_date_from_text("no date here") is None
