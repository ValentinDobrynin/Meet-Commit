#!/usr/bin/env python3
"""
CLI инструмент для ручной проверки и добавления кандидатов в словарь людей.

Использование:
    python -m app.tools.people_miner --top 20
    python -m app.tools.people_miner --stats
    python -m app.tools.people_miner --clear
"""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from app.core.people_detect import propose_name_en, validate_person_entry
from app.core.people_store import (
    clear_candidates,
    get_candidate_stats,
    load_candidates,
    load_people,
    remove_candidate,
    save_people,
)


def _already_known_aliases_lower(people: list[dict]) -> set[str]:
    """Возвращает множество уже известных алиасов в нижнем регистре."""
    aliases = set()
    for person in people:
        # Добавляем все алиасы
        for alias in person.get("aliases", []):
            if alias:
                aliases.add(alias.lower())
        
        # Добавляем каноническое английское имя
        name_en = (person.get("name_en") or "").strip()
        if name_en:
            aliases.add(name_en.lower())
    
    return aliases


def _print_stats() -> None:
    """Выводит статистику по кандидатам."""
    stats = get_candidate_stats()
    
    print("📊 Статистика кандидатов:")
    print(f"  Всего кандидатов: {stats['total']}")
    
    if stats['total'] > 0:
        print(f"  Максимальная частота: {stats['max_count']}")
        print(f"  Минимальная частота: {stats['min_count']}")
        print(f"  Средняя частота: {stats['avg_count']:.1f}")
    
    people_count = len(load_people())
    print(f"  Людей в основном словаре: {people_count}")


def _clear_candidates() -> None:
    """Очищает словарь кандидатов после подтверждения."""
    candidates = load_candidates()
    if not candidates:
        print("❌ Словарь кандидатов уже пуст.")
        return
    
    print(f"⚠️  Вы собираетесь удалить {len(candidates)} кандидатов.")
    confirm = input("Подтвердите действие (yes/no): ").strip().lower()
    
    if confirm in ("yes", "y", "да", "д"):
        clear_candidates()
        print("✅ Словарь кандидатов очищен.")
    else:
        print("❌ Операция отменена.")


def _review_candidates(top_k: int = 20) -> None:
    """Интерактивный процесс проверки кандидатов."""
    candidates = load_candidates()
    
    if not candidates:
        print("❌ Нет новых кандидатов для проверки.")
        return
    
    people = load_people()
    known_aliases = _already_known_aliases_lower(people)
    
    # Сортируем кандидатов по частоте (убывание) и берем топ-K
    sorted_candidates = sorted(
        candidates.items(), 
        key=lambda x: x[1], 
        reverse=True
    )[:top_k]
    
    print(f"🔍 Проверяем топ-{len(sorted_candidates)} кандидатов:")
    print("=" * 50)
    
    changes_made = False
    processed_count = 0
    
    for alias, frequency in sorted_candidates:
        # Пропускаем уже известных (на случай если словарь обновился)
        if alias.lower() in known_aliases:
            remove_candidate(alias)  # Убираем из кандидатов
            continue
        
        processed_count += 1
        name_en_suggestion = propose_name_en(alias)
        
        print(f"\n📝 Кандидат #{processed_count}: {alias}")
        print(f"   Встречался: {frequency} раз(а)")
        print(f"   Предлагаемое имя: {name_en_suggestion}")
        
        while True:
            print("\nВарианты действий:")
            print("  [Enter] - принять предложение")
            print("  [custom] - ввести свой вариант")
            print("  s - пропустить этого кандидата")
            print("  q - завершить работу")
            
            action = input("Ваш выбор: ").strip()
            
            if action.lower() == "q":
                print("👋 Завершение работы...")
                if changes_made:
                    save_people(people)
                    print("✅ Изменения сохранены.")
                return
            
            if action.lower() == "s":
                print(f"⏭️  Пропускаем {alias}")
                break
            
            # Определяем финальное имя
            if action == "":
                final_name_en = name_en_suggestion
            else:
                final_name_en = action.strip()
            
            if not final_name_en:
                print("❌ Имя не может быть пустым. Попробуйте еще раз.")
                continue
            
            # Создаем новую запись
            aliases_list = [alias]
            # Если имя отличается от алиаса, добавляем его тоже
            if final_name_en.lower() != alias.lower():
                aliases_list.append(final_name_en)
            
            new_person = {
                "name_en": final_name_en,
                "aliases": aliases_list
            }
            
            # Валидируем запись
            validation_errors = validate_person_entry(new_person)
            if validation_errors:
                print("❌ Ошибки валидации:")
                for error in validation_errors:
                    print(f"   - {error}")
                continue
            
            # Добавляем в список людей
            people.append(new_person)
            known_aliases.add(alias.lower())
            known_aliases.add(final_name_en.lower())
            
            # Удаляем из кандидатов
            remove_candidate(alias)
            
            changes_made = True
            print(f"✅ Добавлено: {final_name_en} ← {alias}")
            break
    
    # Сохраняем изменения
    if changes_made:
        save_people(people)
        print(f"\n✅ Словарь обновлен. Добавлено людей: {sum(1 for p in people if any(alias == a for a in p.get('aliases', []) for alias, _ in sorted_candidates))}")
        print("📁 Файл: app/dictionaries/people.json")
    else:
        print("\n📝 Изменений не было сделано.")


def _show_help() -> NoReturn:
    """Показывает справку по использованию."""
    help_text = """
🔧 People Miner - Инструмент управления словарем людей

ОПИСАНИЕ:
    Этот инструмент помогает управлять словарем людей, позволяя проверять
    и добавлять новых кандидатов, найденных в транскриптах встреч.

ИСПОЛЬЗОВАНИЕ:
    python -m app.tools.people_miner [опции]

ОПЦИИ:
    --top N         Проверить топ-N кандидатов по частоте (по умолчанию: 20)
    --stats         Показать статистику кандидатов
    --clear         Очистить словарь кандидатов
    --help, -h      Показать эту справку

ПРИМЕРЫ:
    # Проверить топ-10 кандидатов
    python -m app.tools.people_miner --top 10
    
    # Показать статистику
    python -m app.tools.people_miner --stats
    
    # Очистить кандидатов
    python -m app.tools.people_miner --clear

ФАЙЛЫ:
    app/dictionaries/people.json           - Основной словарь людей
    app/dictionaries/people_candidates.json - Кандидаты для проверки
    app/dictionaries/people_stopwords.json  - Стоп-слова
"""
    print(help_text)
    sys.exit(0)


def main() -> None:
    """Главная функция CLI."""
    parser = argparse.ArgumentParser(
        description="CLI инструмент для управления словарем людей",
        add_help=False  # Отключаем стандартную справку
    )
    
    parser.add_argument(
        "--top", 
        type=int, 
        default=20,
        help="Количество топ кандидатов для проверки (по умолчанию: 20)"
    )
    
    parser.add_argument(
        "--stats", 
        action="store_true",
        help="Показать статистику кандидатов"
    )
    
    parser.add_argument(
        "--clear", 
        action="store_true",
        help="Очистить словарь кандидатов"
    )
    
    parser.add_argument(
        "--help", "-h", 
        action="store_true",
        help="Показать справку"
    )
    
    args = parser.parse_args()
    
    # Обрабатываем аргументы
    if args.help:
        _show_help()
    
    if args.stats:
        _print_stats()
        return
    
    if args.clear:
        _clear_candidates()
        return
    
    # По умолчанию запускаем проверку кандидатов
    _review_candidates(top_k=args.top)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Работа прервана пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Произошла ошибка: {e}")
        sys.exit(1)
