"""Тесты для улучшенного парсинга дат с названиями месяцев"""

from datetime import date

from app.core.normalize import _infer_date_from_words, _infer_meeting_date, _map_month


def test_map_month_russian():
    """Тест маппинга русских месяцев."""
    assert _map_month("март") == "03"
    assert _map_month("марта") == "03"
    assert _map_month("мар") == "03"
    assert _map_month("марте") == "03"
    assert _map_month("МАР") == "03"  # case-insensitive
    assert _map_month("мар.") == "03"  # с точкой


def test_map_month_english():
    """Тест маппинга английских месяцев."""
    assert _map_month("March") == "03"
    assert _map_month("mar") == "03"
    assert _map_month("MAR") == "03"
    assert _map_month("mar.") == "03"
    assert _map_month("sept") == "09"  # сокращение September


def test_map_month_invalid():
    """Тест маппинга невалидных месяцев."""
    assert _map_month("invalid") is None
    assert _map_month("") is None
    assert _map_month("13") is None


def test_infer_date_from_words_russian_full():
    """Тест извлечения русских дат с годом."""
    dt = _infer_date_from_words("Встреча 25 марта 2025, обсуждение бюджета")
    assert dt == date(2025, 3, 25)
    
    dt = _infer_date_from_words("Планерка 7 октября 2024")
    assert dt == date(2024, 10, 7)


def test_infer_date_from_words_russian_no_year():
    """Тест извлечения русских дат без года."""
    dt = _infer_date_from_words("Синк 7 окт")
    assert dt is not None
    assert dt.month == 10
    assert dt.day == 7
    # Год должен быть текущий или прошлый (эвристика)


def test_infer_date_from_words_english_dmy():
    """Тест извлечения английских дат в формате DMY."""
    dt = _infer_date_from_words("Meeting on 12 September 2024")
    assert dt == date(2024, 9, 12)
    
    dt = _infer_date_from_words("Review 5 Dec 2025")
    assert dt == date(2025, 12, 5)


def test_infer_date_from_words_english_mdy():
    """Тест извлечения английских дат в формате MDY."""
    dt = _infer_date_from_words("Kickoff on Mar 5, 2024")
    assert dt == date(2024, 3, 5)
    
    dt = _infer_date_from_words("Planning session Sept 15, 2025")
    assert dt == date(2025, 9, 15)


def test_infer_date_from_words_no_match():
    """Тест когда дата не найдена."""
    dt = _infer_date_from_words("Встреча без даты")
    assert dt is None
    
    dt = _infer_date_from_words("Meeting with no date info")
    assert dt is None


def test_infer_date_from_words_invalid_date():
    """Тест обработки невалидных дат."""
    dt = _infer_date_from_words("32 марта 2025")  # несуществующая дата
    assert dt is None
    
    dt = _infer_date_from_words("31 февраля 2025")  # несуществующая дата
    assert dt is None


def test_infer_meeting_date_word_priority():
    """Тест приоритета word-based парсинга над числовым."""
    # Текст содержит и словесную, и числовую дату
    text = "Встреча 15.01.2025 запланирована на 25 марта 2025"
    iso = _infer_meeting_date("meeting.txt", text)
    # Должна быть выбрана словесная дата (приоритет)
    assert iso == "2025-03-25"


def test_infer_meeting_date_filename_priority():
    """Тест приоритета даты из имени файла."""
    text = "Встреча 25 марта 2025"
    iso = _infer_meeting_date("meeting_2024-12-15.txt", text)
    # Дата из имени файла имеет приоритет
    assert iso == "2024-12-15"


def test_infer_meeting_date_fallback_chain():
    """Тест цепочки fallback для извлечения даты."""
    # Только числовая дата в тексте
    text = "Встреча 15.01.2025"
    iso = _infer_meeting_date("meeting.txt", text)
    assert iso == "2025-01-15"
    
    # Никаких дат - fallback к сегодня
    text = "Встреча без даты"
    iso = _infer_meeting_date("meeting.txt", text)
    assert iso == date.today().isoformat()


# === Интеграционные тесты ===

def test_ru_words_full():
    """Тест полных русских дат."""
    iso = _infer_meeting_date("meeting.txt", "Встреча 25 марта 2025, обсуждение бюджета")
    assert iso == "2025-03-25"


def test_ru_words_no_year():
    """Тест русских дат без года."""
    iso = _infer_meeting_date("meeting.txt", "Синк 7 окт")
    assert iso.endswith("-10-07")


def test_en_words_mdy():
    """Тест английских дат в формате MDY."""
    iso = _infer_meeting_date("meeting.txt", "Kickoff on Mar 5, 2024")
    assert iso == "2024-03-05"


def test_en_words_dmy():
    """Тест английских дат в формате DMY."""
    iso = _infer_meeting_date("meeting.txt", "Next review 12 Sep")
    assert iso.endswith("-09-12")


def test_mixed_language_dates():
    """Тест смешанных дат в разных языках."""
    # Русская дата должна быть найдена
    iso = _infer_meeting_date("meeting.txt", "Meeting 15 марта 2025 with team")
    assert iso == "2025-03-15"
    
    # Английская дата должна быть найдена
    iso = _infer_meeting_date("meeting.txt", "Встреча Apr 20, 2025 с командой")
    assert iso == "2025-04-20"


def test_complex_text_parsing():
    """Тест парсинга дат в сложном тексте."""
    complex_text = """
    Привет! Это транскрипт встречи.
    Мы планируем релиз 15 апреля 2025 года.
    Также обсудили встречу на следующей неделе.
    Контакты: alice@example.com, bob@company.org
    """
    
    iso = _infer_meeting_date("complex_meeting.txt", complex_text)
    assert iso == "2025-04-15"


def test_date_with_time_context():
    """Тест дат с контекстом времени."""
    iso = _infer_meeting_date("meeting.txt", "Встреча 25 декабря 2024 в 14:00")
    assert iso == "2024-12-25"
    
    iso = _infer_meeting_date("meeting.txt", "Planning session Dec 31, 2024 at 3pm")
    assert iso == "2024-12-31"


def test_multiple_dates_first_wins():
    """Тест когда в тексте несколько дат - выбирается первая."""
    text = "Встреча 10 января 2025, перенесена с 5 декабря 2024"
    iso = _infer_meeting_date("meeting.txt", text)
    assert iso == "2025-01-10"  # первая дата


def test_relative_date_handling():
    """Тест обработки относительных дат."""
    # Пока не поддерживается, но проверим что не ломается
    iso = _infer_meeting_date("meeting.txt", "Встреча вчера была продуктивной")
    assert iso == date.today().isoformat()  # fallback к сегодня


def test_edge_cases():
    """Тест граничных случаев."""
    # Очень короткий текст
    iso = _infer_meeting_date("meeting.txt", "25 мар")
    assert iso.endswith("-03-25")
    
    # Дата в конце текста
    long_text = "Очень длинный текст " * 100 + " встреча 15 июня 2025"
    iso = _infer_meeting_date("meeting.txt", long_text)
    assert iso == "2025-06-15"
    
    # Пустой текст
    iso = _infer_meeting_date("meeting.txt", "")
    assert iso == date.today().isoformat()


def test_case_insensitive_parsing():
    """Тест нечувствительности к регистру."""
    iso = _infer_meeting_date("meeting.txt", "ВСТРЕЧА 25 МАРТА 2025")
    assert iso == "2025-03-25"
    
    iso = _infer_meeting_date("meeting.txt", "meeting on MARCH 15, 2025")
    assert iso == "2025-03-15"
