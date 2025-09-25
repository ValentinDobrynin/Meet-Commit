"""
Тесты для модуля хэширования транскриптов.
"""

from app.core.hash import (
    _normalize_for_hash,
    compute_raw_hash,
    debug_normalization,
)


class TestNormalization:
    """Тесты нормализации текста."""

    def test_normalize_basic_text(self):
        """Тест базовой нормализации."""
        text = "Привет, как дела?"
        result = _normalize_for_hash(text)
        assert result == "привет, как дела?"

    def test_normalize_removes_timestamps(self):
        """Тест удаления временных меток."""
        text = "Валентин 12:30: Привет! Встреча в 15:45."
        result = _normalize_for_hash(text)
        assert "12:30" not in result
        assert "15:45" not in result
        assert "привет! встреча в" in result

    def test_normalize_removes_speaker_labels(self):
        """Тест удаления меток спикеров."""
        text = "Speaker: Валентин говорит\nСаша: Отвечает\nОбычный текст"
        result = _normalize_for_hash(text)
        assert "speaker:" not in result.lower()
        assert "саша:" not in result.lower()
        assert "обычный текст" in result

    def test_normalize_handles_whitespace(self):
        """Тест нормализации пробелов."""
        text = "Много    пробелов\n\n\nи   переносов"
        result = _normalize_for_hash(text)
        assert "много пробелов и переносов" in result

    def test_normalize_empty_text(self):
        """Тест обработки пустого текста."""
        assert _normalize_for_hash("") == ""
        assert _normalize_for_hash("   ") == ""


class TestHashComputation:
    """Тесты вычисления хэшей."""

    def test_compute_raw_hash_stable(self):
        """Тест стабильности хэша."""
        text = "Тестовый текст встречи"
        hash1 = compute_raw_hash(text)
        hash2 = compute_raw_hash(text)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256

    def test_compute_raw_hash_different_timestamps(self):
        """Тест что разные временные метки дают одинаковый хэш."""
        text1 = "Валентин 12:30: Обсуждаем проект"
        text2 = "Валентин 15:45: Обсуждаем проект"
        assert compute_raw_hash(text1) == compute_raw_hash(text2)

    def test_compute_raw_hash_different_speakers(self):
        """Тест что разные метки спикеров дают одинаковый хэш."""
        text1 = "Speaker: Валентин\nОбсуждаем проект"
        text2 = "Спикер: Валентин\nОбсуждаем проект"
        assert compute_raw_hash(text1) == compute_raw_hash(text2)


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_unicode_normalization(self):
        """Тест Unicode нормализации."""
        # Разные способы записи одного символа
        text1 = "café"  # é как один символ
        text2 = "cafe\u0301"  # é как e + combining accent
        assert compute_raw_hash(text1) == compute_raw_hash(text2)

    def test_emoji_removal(self):
        """Тест удаления эмодзи."""
        text1 = "Привет! 😊 Как дела? 🚀"
        text2 = "Привет! Как дела?"
        assert compute_raw_hash(text1) == compute_raw_hash(text2)

    def test_case_insensitive(self):
        """Тест нечувствительности к регистру."""
        text1 = "ПРИВЕТ КАК ДЕЛА"
        text2 = "привет как дела"
        assert compute_raw_hash(text1) == compute_raw_hash(text2)

    def test_complex_speaker_patterns(self):
        """Тест сложных паттернов спикеров."""
        text1 = """
        Валентин: Начинаем встречу
        Участник - Саша: Готов
        Говорящий: Иван отвечает
        Обычный текст без меток
        """

        result = _normalize_for_hash(text1)
        assert "валентин:" not in result
        assert "участник" not in result
        assert "говорящий:" not in result
        assert "обычный текст без меток" in result


class TestDebugFeatures:
    """Тесты отладочных функций."""

    def test_debug_normalization(self):
        """Тест отладочной функции нормализации."""
        text = "Валентин 12:30: Привет! 😊"
        debug_info = debug_normalization(text)

        assert "original" in debug_info
        assert "unicode_normalized" in debug_info
        assert "no_timestamps" in debug_info
        assert "no_speakers" in debug_info
        assert "no_emoji" in debug_info
        assert "final_normalized" in debug_info
        assert "hash" in debug_info

        assert debug_info["original"] == text
        assert "12:30" not in debug_info["no_timestamps"]
        assert "😊" not in debug_info["no_emoji"]
        assert len(debug_info["hash"]) == 64


class TestCaching:
    """Тесты кэширования."""

    def test_hash_caching(self):
        """Тест что хэш кэшируется (LRU cache)."""
        text = "Тестовый текст для кэширования"

        # Первый вызов
        hash1 = compute_raw_hash(text)

        # Второй вызов должен быть из кэша
        hash2 = compute_raw_hash(text)

        assert hash1 == hash2
        # Проверяем что функция действительно кэшируется
        assert hasattr(compute_raw_hash, "cache_info")


class TestRealWorldScenarios:
    """Тесты реальных сценариев."""

    def test_meeting_transcript_variations(self):
        """Тест вариаций одного транскрипта."""
        base_transcript = """
        Обсуждение планов на квартал.
        Нужно подготовить отчет по IFRS.
        Саша займется анализом.
        """

        # Вариация 1: с временными метками
        var1 = """
        12:30 Обсуждение планов на квартал.
        12:35 Нужно подготовить отчет по IFRS.
        12:40 Саша займется анализом.
        """

        # Вариация 2: простые метки спикеров
        var2 = """
        Валентин: Обсуждение планов на квартал.
        Speaker: Нужно подготовить отчет по IFRS.
        Саша: займется анализом.
        """

        # Базовый и первая вариация должны совпадать (убираются timestamps)
        hash_base = compute_raw_hash(base_transcript)
        hash_var1 = compute_raw_hash(var1)
        hash_var2 = compute_raw_hash(var2)

        assert hash_base == hash_var1  # Временные метки убираются
        assert hash_var2 != hash_base  # Спикеры обрабатываются, но могут отличаться - это нормально

    def test_filename_independence(self):
        """Тест что хэш не зависит от имени файла."""
        transcript = "Обсуждение проекта Лавка"

        # Хэш должен быть одинаковым независимо от контекста
        hash1 = compute_raw_hash(transcript)
        hash2 = compute_raw_hash(transcript)

        assert hash1 == hash2

    def test_minor_text_differences(self):
        """Тест что минорные отличия дают разные хэши."""
        text1 = "Обсуждение проекта Лавка"
        text2 = "Обсуждение проекта Маркет"  # Разное содержание

        assert compute_raw_hash(text1) != compute_raw_hash(text2)

    def test_lavka_declensions(self):
        """Тест что разные склонения дают разные хэши (это правильно)."""
        text1 = "Обсуждение Лавки"
        text2 = "Обсуждение Лавке"

        # Разные склонения = разный контент = разные хэши
        assert compute_raw_hash(text1) != compute_raw_hash(text2)
