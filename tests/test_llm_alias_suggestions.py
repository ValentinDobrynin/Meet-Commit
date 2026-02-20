"""Тесты для LLM генерации предложений алиасов."""

from unittest.mock import MagicMock, patch

from app.core.llm_alias_suggestions import generate_alias_suggestions


class TestLLMAliasGeneration:
    """Тесты для генерации алиасов через LLM."""

    @patch("app.core.llm_alias_suggestions.get_openai_parse_client")
    @patch("app.core.llm_alias_suggestions.track_llm_tokens")
    def test_generate_alias_suggestions_success(self, mock_track_tokens, mock_get_client):
        """Тест успешной генерации алиасов."""
        # Настройка мока клиента
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Мок ответа от OpenAI
        mock_response = MagicMock()
        mock_response.choices[
            0
        ].message.content = '{"aliases": ["John", "Smith", "Джон", "Johnny"]}'
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        mock_client.chat.completions.create.return_value = mock_response

        # Тестируем функцию
        result = generate_alias_suggestions("John Smith", ["John Smith"])

        # Проверки
        assert isinstance(result, list)
        assert len(result) == 4
        assert "John" in result
        assert "Smith" in result
        assert "Джон" in result
        assert "Johnny" in result

        # Проверяем что клиент был вызван правильно
        mock_client.chat.completions.create.assert_called_once()
        call_args = mock_client.chat.completions.create.call_args
        assert call_args[1]["model"] == "gpt-4o-mini"
        assert call_args[1]["temperature"] == 0.3
        assert call_args[1]["response_format"] == {"type": "json_object"}

        # Проверяем отслеживание токенов
        mock_track_tokens.assert_called_once()

        # Проверяем что клиент был закрыт
        mock_client.close.assert_called_once()

    @patch("app.core.llm_alias_suggestions.get_openai_parse_client")
    def test_generate_alias_suggestions_empty_response(self, mock_get_client):
        """Тест обработки пустого ответа от LLM."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Пустой ответ
        mock_response = MagicMock()
        mock_response.choices[0].message.content = ""
        mock_response.usage = None

        mock_client.chat.completions.create.return_value = mock_response

        result = generate_alias_suggestions("John Smith")

        assert result == []
        mock_client.close.assert_called_once()

    @patch("app.core.llm_alias_suggestions.get_openai_parse_client")
    def test_generate_alias_suggestions_invalid_json(self, mock_get_client):
        """Тест обработки некорректного JSON от LLM."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Некорректный JSON
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "invalid json"
        mock_response.usage = None

        mock_client.chat.completions.create.return_value = mock_response

        result = generate_alias_suggestions("John Smith")

        assert result == []
        mock_client.close.assert_called_once()

    @patch("app.core.llm_alias_suggestions.get_openai_parse_client")
    def test_generate_alias_suggestions_api_error(self, mock_get_client):
        """Тест обработки ошибки API."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # API ошибка
        mock_client.chat.completions.create.side_effect = Exception("API Error")

        result = generate_alias_suggestions("John Smith")

        assert result == []
        mock_client.close.assert_called_once()

    @patch("app.core.llm_alias_suggestions.get_openai_parse_client")
    def test_generate_alias_suggestions_excludes_existing(self, mock_get_client):
        """Тест исключения уже существующих алиасов."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # LLM возвращает алиасы включая уже существующие
        mock_response = MagicMock()
        mock_response.choices[
            0
        ].message.content = '{"aliases": ["John", "Smith", "Джон", "Johnny"]}'
        mock_response.usage = None

        mock_client.chat.completions.create.return_value = mock_response

        # Передаем уже существующие алиасы
        existing = ["John Smith", "John", "Джон"]
        result = generate_alias_suggestions("John Smith", existing)

        # Должны быть исключены дубликаты
        assert "John" not in result
        assert "Джон" not in result
        assert "Smith" in result
        assert "Johnny" in result

    @patch("app.core.llm_alias_suggestions.get_openai_parse_client")
    def test_generate_alias_suggestions_invalid_format(self, mock_get_client):
        """Тест обработки неправильного формата ответа."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Неправильный формат (aliases не список)
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"aliases": "not a list"}'
        mock_response.usage = None

        mock_client.chat.completions.create.return_value = mock_response

        result = generate_alias_suggestions("John Smith")

        assert result == []

    @patch("app.core.llm_alias_suggestions.get_openai_parse_client")
    def test_generate_alias_suggestions_filters_invalid_aliases(self, mock_get_client):
        """Тест фильтрации некорректных алиасов."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Ответ с некорректными элементами
        mock_response = MagicMock()
        mock_response.choices[
            0
        ].message.content = '{"aliases": ["John", "", "   ", 123, "Smith", null]}'
        mock_response.usage = None

        mock_client.chat.completions.create.return_value = mock_response

        result = generate_alias_suggestions("John Smith", ["John Smith"])

        # Должны остаться только валидные строки
        assert result == ["John", "Smith"]

    @patch("app.core.llm_alias_suggestions.get_openai_parse_client")
    def test_generate_alias_suggestions_limits_results(self, mock_get_client):
        """Тест ограничения количества результатов."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Много предложений
        many_aliases = [f"Alias{i}" for i in range(20)]
        mock_response = MagicMock()
        mock_response.choices[0].message.content = f'{{"aliases": {many_aliases}}}'
        mock_response.usage = None

        mock_client.chat.completions.create.return_value = mock_response

        result = generate_alias_suggestions("John Smith")

        # Должно быть не больше 15
        assert len(result) <= 15
