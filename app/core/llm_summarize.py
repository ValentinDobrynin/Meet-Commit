from __future__ import annotations

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.metrics import MetricNames, async_timer, track_llm_tokens
from app.settings import settings


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def _client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY отсутствует")

    timeout = httpx.Timeout(
        connect=10.0,  # Таймаут подключения
        read=240.0,  # Таймаут чтения (4 минуты для больших ответов)
        write=10.0,  # Таймаут записи
        pool=5.0,  # Таймаут получения соединения из пула
    )

    http = httpx.AsyncClient(
        timeout=timeout, limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
    )
    return AsyncOpenAI(api_key=settings.openai_api_key, http_client=http)


def _merge_prompt(base: str | None, extra: str | None) -> str:
    base = base or ""
    extra = (extra or "").strip()
    if not extra:
        return base
    if "{EXTRA}" in base:
        return base.replace("{EXTRA}", extra)
    # fallback: аккуратно доклеиваем конец
    return f"{base.rstrip()}\n\nДоп. указания:\n{extra}"


async def run(
    text: str,
    prompt_path: str,
    extra: str | None,
    *,
    model: str | None = None,
    temperature: float | None = None,
) -> str:
    async with async_timer(MetricNames.LLM_SUMMARIZE):
        model = model or getattr(settings, "summarize_model", "gpt-4o-mini")
        if not isinstance(model, str):
            model = "gpt-4o-mini"
        temperature = (
            temperature
            if temperature is not None
            else getattr(settings, "summarize_temperature", 0.2)
        )

        with open(prompt_path, encoding="utf-8") as f:
            base = f.read()

        prompt = _merge_prompt(base, extra)
        client = await _client()

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Ты делаешь сжатые деловые саммари."},
                    {"role": "user", "content": f"{prompt}\n\n=== Текст встречи ===\n{text}"},
                ],
                temperature=temperature,
            )

            # Отслеживаем использование токенов
            if resp.usage and hasattr(resp.usage, "prompt_tokens"):
                try:
                    track_llm_tokens(
                        MetricNames.LLM_SUMMARIZE,
                        int(resp.usage.prompt_tokens),
                        int(resp.usage.completion_tokens),
                        int(resp.usage.total_tokens),
                    )
                except (TypeError, ValueError):
                    pass  # Игнорируем ошибки в тестах с Mock объектами

            msg = (resp.choices[0].message.content or "").strip()
            if not msg:
                raise RuntimeError("LLM вернул пустой ответ")
            return msg

        except Exception as e:
            # Логирование ошибки для отладки
            print(f"LLM API error: {type(e).__name__}: {e}")
            raise
        finally:
            await client.close()
