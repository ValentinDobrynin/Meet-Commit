import os

from openai import OpenAI


def run(text: str, prompt_path: str, extra: str | None) -> str:
    with open(prompt_path, encoding="utf-8") as f:
        base = f.read()
    prompt = base.replace("{EXTRA}", extra or "")
    
    # Проверяем наличие API ключа
    try:
        api_key = os.environ["OPENAI_API_KEY"]
    except KeyError:
        raise ValueError("OPENAI_API_KEY not found in environment variables") from None
    
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты делаешь сжатые деловые саммари."},
            {"role": "user", "content": f"{prompt}\n\n=== Текст встречи ===\n{text}"},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()
