from __future__ import annotations
import httpx
from openai import OpenAI
from app.settings import settings

def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY отсутствует")
    http = httpx.Client(timeout=30, limits=httpx.Limits(max_keepalive_connections=10, max_connections=20))
    return OpenAI(api_key=settings.openai_api_key, http_client=http)

def _merge_prompt(base: str, extra: str | None) -> str:
    extra = (extra or "").strip()
    if not extra:
        return base
    if "{EXTRA}" in base:
        return base.replace("{EXTRA}", extra)
    # fallback: аккуратно доклеиваем конец
    return f"{base.rstrip()}\n\nДоп. указания:\n{extra}"

def run(text: str, prompt_path: str, extra: str | None,
        *, model: str | None = None, temperature: float | None = None) -> str:
    model = model or getattr(settings, "summarize_model", "gpt-4o-mini")
    temperature = temperature if temperature is not None else getattr(settings, "summarize_temperature", 0.2)

    with open(prompt_path, encoding="utf-8") as f:
        base = f.read()

    prompt = _merge_prompt(base, extra)
    client = _client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Ты делаешь сжатые деловые саммари."},
            {"role": "user", "content": f"{prompt}\n\n=== Текст встречи ===\n{text}"},
        ],
        temperature=temperature,
    )
    msg = (resp.choices[0].message.content or "").strip()
    if not msg:
        raise RuntimeError("LLM вернул пустой ответ")
    return msg
