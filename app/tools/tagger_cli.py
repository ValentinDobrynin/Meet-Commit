#!/usr/bin/env python3
"""CLI утилита для тестирования scored тэггера."""

import argparse
import sys
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.tagger_v1_scored import get_rules_stats, reload_rules, tag_text, tag_text_scored
from app.settings import settings


def test_text(text: str, show_scores: bool = False) -> None:
    """Тестирует тегирование текста."""
    print(f"📝 Текст: {text}")
    print(f"⚙️ Режим: {settings.tags_mode}")
    print(f"🎯 Порог: {settings.tags_min_score}")
    print("-" * 60)

    if show_scores:
        print("📊 Scored результаты:")
        scored = tag_text_scored(text)
        if scored:
            for tag, score in scored:
                status = "✅" if score >= settings.tags_min_score else "❌"
                print(f"  {status} {tag}: {score:.2f}")
        else:
            print("  Теги не найдены")
        print()

    print("🏷️ Финальные теги:")
    tags = tag_text(text)
    if tags:
        for tag in tags:
            print(f"  • {tag}")
    else:
        print("  Теги не найдены")


def show_stats() -> None:
    """Показывает статистику тэггера."""
    stats = get_rules_stats()

    print("📊 Статистика Tagger v1 Scored:")
    print("=" * 50)
    print(f"📋 Всего правил: {stats.get('total_rules', 0)}")
    print(f"🔍 Всего паттернов: {stats.get('total_patterns', 0)}")
    print(f"🚫 Всего исключений: {stats.get('total_excludes', 0)}")
    print(f"⚖️ Средний вес: {stats.get('average_weight', 0):.2f}")

    if stats.get("last_reload_time"):
        import datetime

        reload_time = datetime.datetime.fromtimestamp(stats["last_reload_time"])
        print(f"🔄 Последняя перезагрузка: {reload_time.strftime('%Y-%m-%d %H:%M:%S')}")


def reload_rules_cli() -> None:
    """Перезагружает правила тегирования."""
    print("🔄 Перезагрузка правил...")
    count = reload_rules()
    print(f"✅ Загружено {count} правил")


def main() -> None:
    """Главная функция CLI."""
    parser = argparse.ArgumentParser(
        description="CLI утилита для тестирования scored тэггера",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:

  # Тестирование текста
  python -m app.tools.tagger_cli "Обсудили аудит IFRS для Lavka"
  
  # Тестирование с показом scores
  python -m app.tools.tagger_cli "Обсудили аудит IFRS для Lavka" --scores
  
  # Статистика
  python -m app.tools.tagger_cli --stats
  
  # Перезагрузка правил
  python -m app.tools.tagger_cli --reload
        """,
    )

    parser.add_argument("text", nargs="?", help="Текст для тегирования")

    parser.add_argument(
        "--scores", action="store_true", help="Показать scores для всех найденных тегов"
    )

    parser.add_argument("--stats", action="store_true", help="Показать статистику тэггера")

    parser.add_argument("--reload", action="store_true", help="Перезагрузить правила тегирования")

    parser.add_argument(
        "--threshold",
        type=float,
        help=f"Изменить порог score (по умолчанию: {settings.tags_min_score})",
    )

    args = parser.parse_args()

    # Изменяем порог если указан
    if args.threshold is not None:
        settings.tags_min_score = args.threshold
        print(f"🎯 Порог изменен на: {args.threshold}")

    try:
        if args.reload:
            reload_rules_cli()
            return

        if args.stats:
            show_stats()
            return

        if not args.text:
            print("❌ Необходимо указать текст для анализа или использовать --stats/--reload")
            parser.print_help()
            sys.exit(1)

        test_text(args.text, show_scores=args.scores)

    except KeyboardInterrupt:
        print("\n👋 Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
