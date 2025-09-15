import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DICT_DIR = BASE_DIR / "dictionaries"


def _load_dicts():
    with open(DICT_DIR / "tags.json", encoding="utf-8") as f:
        tags = json.load(f)
    with open(DICT_DIR / "tag_synonyms.json", encoding="utf-8") as f:
        synonyms = json.load(f)
    return tags, synonyms


TAGS, SYNONYMS = _load_dicts()


def run(summary_md: str, meta: dict) -> list[str]:
    """v0 tagger: ищет ключевые слова в summary и meta и возвращает список тегов"""
    tags = set()
    low = summary_md.lower()
    for key, mapped_tag in SYNONYMS.items():
        if key in low or key in meta.get("title", "").lower():
            tags.add(mapped_tag)
    return sorted(tags)


# CLI
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.core.tagger 'текст'")
        sys.exit(1)
    text = sys.argv[1]
    tags = run(summary_md=text, meta={"title": "cli-test"})
    print("Теги:", tags)
