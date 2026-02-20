"""
LLM система для генерации предложений алиасов для людей.
Использует OpenAI API для создания умных предложений на основе имени.
"""

import json
import logging

from app.core.clients import get_openai_parse_client
from app.core.metrics import MetricNames, track_llm_tokens

logger = logging.getLogger(__name__)


def generate_alias_suggestions(name: str, existing_aliases: list[str] | None = None) -> list[str]:
    """
    Генерирует предложения алиасов для имени через OpenAI API.

    Args:
        name: Каноническое имя человека (например "John Smith")
        existing_aliases: Уже существующие алиасы (для исключения дубликатов)

    Returns:
        Список предложенных алиасов
    """
    existing_aliases = existing_aliases or []

    prompt = _build_alias_prompt()
    user_content = _build_user_request(name, existing_aliases)

    client = get_openai_parse_client()

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,  # Немного больше креативности для алиасов
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )

        # Отслеживаем токены
        if resp.usage and hasattr(resp.usage, "prompt_tokens"):
            try:
                track_llm_tokens(
                    MetricNames.LLM_ALIAS_SUGGESTIONS,
                    int(resp.usage.prompt_tokens),
                    int(resp.usage.completion_tokens),
                    int(resp.usage.total_tokens),
                )
            except (TypeError, ValueError):
                pass  # Игнорируем ошибки в тестах

        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            logger.warning("LLM returned empty response for alias suggestions")
            return []

        try:
            data = json.loads(raw)
            suggestions = data.get("aliases", [])

            if not isinstance(suggestions, list):
                logger.warning(f"LLM returned invalid aliases format: {type(suggestions)}")
                return []

            # Фильтруем и валидируем
            valid_suggestions = []
            for alias in suggestions:
                if isinstance(alias, str) and alias.strip():
                    alias = alias.strip()
                    # Исключаем дубликаты (case-insensitive)
                    if alias.lower() not in [a.lower() for a in existing_aliases]:
                        valid_suggestions.append(alias)

            logger.info(f"Generated {len(valid_suggestions)} alias suggestions for '{name}'")
            return valid_suggestions[:15]  # Максимум 15 предложений

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from LLM for alias suggestions: {raw}")
            return []

    except Exception as e:
        logger.error(f"LLM API error in alias suggestions: {type(e).__name__}: {e}")
        return []

    finally:
        client.close()


def _build_alias_prompt() -> str:
    """Создает системный промпт для генерации алиасов."""
    return """Ты помогаешь создавать алиасы (варианты написания) для имен людей в корпоративной системе.

ЗАДАЧА: Для данного канонического имени предложи разумные алиасы, которые люди могут использовать в текстах встреч, чатах, документах.

ПРИНЦИПЫ:
1. ВСЕГДА включай фамилию отдельно на русском и английском
2. Включай полные имена на русском и английском  
3. Включай сокращения с инициалами (J.Smith, М.Гарсия)
4. СТРОГО НЕ включай только имена (John, Дима, Maria, Johnny, Джонни)
5. Все алиасы должны содержать фамилию или быть полными именами
6. НЕ включай оскорбительные или неуместные варианты

ПРАВИЛЬНЫЕ ПРИМЕРЫ:
- "John Smith" → ["Smith", "Смит", "Джон Смит", "J.Smith"]
- "Maria Garcia" → ["Garcia", "Гарсия", "Мария Гарсия", "M.Garcia"]  
- "Dmitriy Petrov" → ["Petrov", "Петров", "Дмитрий Петров", "D.Petrov", "Дима Петров"]

НЕПРАВИЛЬНО (НЕ делай так):
- "John Smith" → ["John", "Johnny", "Джон"] ❌
- "Maria Garcia" → ["Maria", "Mary", "Мария"] ❌

ФОРМАТ ОТВЕТА: JSON объект с полем "aliases" содержащим массив строк.

Пример:
{
  "aliases": ["John", "Smith", "Джон", "Джон Смит", "Johnny"]
}"""


def _build_user_request(name: str, existing_aliases: list[str]) -> str:
    """Создает пользовательский запрос для генерации алиасов."""
    request = f"Имя: {name}\n\n"

    if existing_aliases:
        request += "Уже существующие алиасы (НЕ включай их в ответ):\n"
        for alias in existing_aliases:
            request += f"- {alias}\n"
        request += "\n"

    request += "Предложи дополнительные алиасы для этого имени."

    return request
