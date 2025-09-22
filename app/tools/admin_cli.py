#!/usr/bin/env python3
"""CLI утилита для административных функций."""

import argparse
import sys
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.tagger_v1_scored import validate_rules
from app.core.tags import get_tagging_stats
from app.gateways.notion_meetings import fetch_meeting_page, validate_meeting_access


def show_detailed_stats() -> None:
    """Показывает детальную статистику системы тегирования."""
    stats = get_tagging_stats()

    print("📊 Детальная статистика системы тегирования")
    print("=" * 60)

    # Основная информация
    print(f"🎯 Режим: {stats['current_mode']}")
    print(f"🔧 Scored тэггер: {'✅' if stats.get('v1_scored_enabled') else '❌'}")
    print(f"🎚️ Порог score: {stats.get('tags_min_score', 0.5)}")
    print()

    # Статистика вызовов
    calls_stats = stats["stats"]
    print("📈 Статистика вызовов:")
    print(f"   Всего: {calls_stats['total_calls']}")
    for mode, count in calls_stats["calls_by_mode"].items():
        print(f"   {mode}: {count}")
    print()

    # Производительность
    if "performance" in stats:
        perf = stats["performance"]
        print("⚡ Производительность:")
        print(f"   Uptime: {perf['uptime_hours']:.1f} часов")
        print(f"   Вызовов/час: {perf['calls_per_hour']:.1f}")
        print(f"   Среднее время: {perf['avg_response_time_ms']:.2f}мс")
        print()

    # Кэш
    cache = stats["cache_info"]
    print("💾 Кэш:")
    print(f"   Hit rate: {cache['hit_rate_percent']:.1f}%")
    print(f"   Hits/Misses: {cache['hits']}/{cache['misses']}")
    print(f"   Размер: {cache['currsize']}/{cache['maxsize']}")
    print()

    # Топ теги
    if stats.get("top_tags"):
        print("🔥 Топ теги:")
        for tag, count in stats["top_tags"][:10]:
            print(f"   {tag}: {count}")
        print()

    # V1 статистика
    if "v1_stats" in stats:
        v1 = stats["v1_stats"]
        print("🏷️ Tagger v1 Scored:")
        print(f"   Правил: {v1.get('total_rules', 0)}")
        print(f"   Паттернов: {v1.get('total_patterns', 0)}")
        print(f"   Исключений: {v1.get('total_excludes', 0)}")
        print(f"   Средний вес: {v1.get('average_weight', 0):.2f}")


def validate_yaml() -> None:
    """Валидирует YAML файл правил."""
    print("✅ Валидация YAML правил тегирования")
    print("=" * 50)

    errors = validate_rules()

    if not errors:
        print("🎉 Все правила корректны!")
        print("• Regex паттерны валидны")
        print("• Нет дубликатов тегов")
        print("• Веса в допустимых пределах")
        print("• Структура файла корректна")
    else:
        print(f"❌ Найдено {len(errors)} ошибок:")
        print()
        for i, error in enumerate(errors, 1):
            print(f"{i:2d}. {error}")


def test_meeting_access(meeting_id: str) -> None:
    """Тестирует доступ к странице встречи."""
    print(f"🔍 Проверка доступа к встрече: {meeting_id}")
    print("-" * 50)

    try:
        # Проверяем доступ
        if validate_meeting_access(meeting_id):
            print("✅ Страница доступна")

            # Получаем данные
            page_data = fetch_meeting_page(meeting_id)
            print(f"📄 Название: {page_data['title']}")
            print(f"🏷️ Текущие теги ({len(page_data['current_tags'])}):")
            for tag in page_data["current_tags"]:
                print(f"   • {tag}")
            print(f"📝 Summary: {len(page_data['summary_md'])} символов")

        else:
            print("❌ Страница недоступна")

    except Exception as e:
        print(f"❌ Ошибка: {e}")


def dry_run_retag(meeting_id: str) -> None:
    """Выполняет dry-run retag для встречи."""
    print(f"🔍 Dry-run retag для встречи: {meeting_id}")
    print("-" * 50)

    try:
        from app.core.tags import tag_text

        # Получаем данные страницы
        page_data = fetch_meeting_page(meeting_id)

        # Пересчитываем теги
        summary_md = page_data.get("summary_md", "")
        if not summary_md:
            print("❌ Нет summary для пересчета тегов")
            return

        new_tags = set(tag_text(summary_md))
        old_tags = set(page_data.get("current_tags", []))

        # Вычисляем diff
        tags_to_add = sorted(new_tags - old_tags)
        tags_to_remove = sorted(old_tags - new_tags)

        print(f"📄 Встреча: {page_data['title']}")
        print(f"📊 Старых тегов: {len(old_tags)}")
        print(f"📊 Новых тегов: {len(new_tags)}")
        print()

        if tags_to_add:
            print(f"➕ Добавить ({len(tags_to_add)}):")
            for tag in tags_to_add:
                print(f"   • {tag}")
            print()

        if tags_to_remove:
            print(f"➖ Удалить ({len(tags_to_remove)}):")
            for tag in tags_to_remove:
                print(f"   • {tag}")
            print()

        if not tags_to_add and not tags_to_remove:
            print("✅ Изменений нет - теги актуальны")

    except Exception as e:
        print(f"❌ Ошибка: {e}")


def main() -> None:
    """Главная функция CLI."""
    parser = argparse.ArgumentParser(
        description="CLI утилита для административных функций",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:

  # Детальная статистика
  python -m app.tools.admin_cli --stats
  
  # Валидация YAML
  python -m app.tools.admin_cli --validate
  
  # Проверка доступа к встрече
  python -m app.tools.admin_cli --test-access 12345678901234567890123456789012
  
  # Dry-run retag
  python -m app.tools.admin_cli --dry-retag 12345678901234567890123456789012
        """,
    )

    parser.add_argument(
        "--stats", action="store_true", help="Показать детальную статистику системы тегирования"
    )

    parser.add_argument(
        "--validate", action="store_true", help="Валидировать YAML файл правил тегирования"
    )

    parser.add_argument(
        "--test-access", metavar="MEETING_ID", help="Проверить доступ к странице встречи"
    )

    parser.add_argument(
        "--dry-retag", metavar="MEETING_ID", help="Выполнить dry-run retag для встречи"
    )

    args = parser.parse_args()

    try:
        if args.stats:
            show_detailed_stats()
        elif args.validate:
            validate_yaml()
        elif args.test_access:
            test_meeting_access(args.test_access)
        elif args.dry_retag:
            dry_run_retag(args.dry_retag)
        else:
            print("❌ Необходимо указать одну из опций")
            parser.print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n👋 Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
