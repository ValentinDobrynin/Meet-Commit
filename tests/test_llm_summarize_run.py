"""Тесты для app.core.llm_summarize.run"""

from unittest.mock import AsyncMock, mock_open, patch

import pytest

from app.core.llm_summarize import run as llm_run


@pytest.mark.asyncio
async def test_llm_run_success():
    """Тест успешного выполнения LLM запроса."""
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = "Краткое саммари встречи"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.close = AsyncMock()

    with patch("app.core.llm_summarize._client", return_value=mock_client):
        with patch("builtins.open", mock_open(read_data="Сделай саммари: {EXTRA}")):
            result = await llm_run(
                text="Текст встречи", prompt_path="test_prompt.txt", extra="Дополнительные указания"
            )

    assert result == "Краткое саммари встречи"
    mock_client.chat.completions.create.assert_called_once()
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_llm_run_empty_response():
    """Тест обработки пустого ответа от LLM."""
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = ""

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.close = AsyncMock()

    with patch("app.core.llm_summarize._client", return_value=mock_client):
        with patch("builtins.open", mock_open(read_data="Сделай саммари")):
            with pytest.raises(RuntimeError, match="LLM вернул пустой ответ"):
                await llm_run(text="Текст встречи", prompt_path="test_prompt.txt", extra=None)

    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_llm_run_none_response():
    """Тест обработки None ответа от LLM."""
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = None

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.close = AsyncMock()

    with patch("app.core.llm_summarize._client", return_value=mock_client):
        with patch("builtins.open", mock_open(read_data="Сделай саммари")):
            with pytest.raises(RuntimeError, match="LLM вернул пустой ответ"):
                await llm_run(text="Текст встречи", prompt_path="test_prompt.txt", extra=None)

    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_llm_run_api_error():
    """Тест обработки ошибки API."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API Error"))
    mock_client.close = AsyncMock()

    with patch("app.core.llm_summarize._client", return_value=mock_client):
        with patch("builtins.open", mock_open(read_data="Сделай саммари")):
            with pytest.raises(Exception, match="API Error"):
                await llm_run(text="Текст встречи", prompt_path="test_prompt.txt", extra=None)

    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_llm_run_with_custom_model():
    """Тест с кастомной моделью и температурой."""
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = "Результат"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.close = AsyncMock()

    with patch("app.core.llm_summarize._client", return_value=mock_client):
        with patch("builtins.open", mock_open(read_data="Сделай саммари")):
            result = await llm_run(
                text="Текст встречи",
                prompt_path="test_prompt.txt",
                extra=None,
                model="gpt-4",
                temperature=0.5,
            )

    assert result == "Результат"
    call_args = mock_client.chat.completions.create.call_args
    assert call_args[1]["model"] == "gpt-4"
    assert call_args[1]["temperature"] == 0.5


@pytest.mark.asyncio
async def test_llm_run_prompt_merging():
    """Тест правильного объединения промпта."""
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = "Результат"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.close = AsyncMock()

    with patch("app.core.llm_summarize._client", return_value=mock_client):
        with patch("builtins.open", mock_open(read_data="Сделай саммари. {EXTRA}")):
            await llm_run(
                text="Текст встречи", prompt_path="test_prompt.txt", extra="Дополнительные указания"
            )

    # Проверяем, что промпт правильно объединен
    call_args = mock_client.chat.completions.create.call_args
    messages = call_args[1]["messages"]
    user_message = messages[1]["content"]

    assert "Сделай саммари. Дополнительные указания" in user_message
    assert "=== Текст встречи ===" in user_message
    assert "Текст встречи" in user_message
