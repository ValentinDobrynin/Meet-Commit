#!/usr/bin/env python3
"""
Утилита для диагностики Notion баз данных
"""

import os

import httpx
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()


def check_env_vars():
    """Проверяет наличие всех необходимых переменных окружения."""
    required_vars = ["NOTION_TOKEN", "NOTION_DB_MEETINGS_ID", "COMMITS_DB_ID", "REVIEW_DB_ID"]

    print("🔍 Проверка переменных окружения:")
    print("=" * 50)

    missing = []
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Показываем только первые и последние символы для безопасности
            masked = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            print(f"✅ {var}: {masked}")
        else:
            print(f"❌ {var}: НЕ НАЙДЕНА")
            missing.append(var)

    if missing:
        print(f"\n❌ Отсутствуют переменные: {', '.join(missing)}")
        return False

    print("\n✅ Все переменные найдены!")
    return True


def create_notion_client():
    """Создает HTTP клиент для Notion API."""
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN не найден")

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    return httpx.Client(timeout=30, headers=headers)


def check_database(client: httpx.Client, db_id: str, db_name: str):
    """Проверяет доступность и структуру базы данных."""
    print(f"\n🔍 Проверка базы '{db_name}' (ID: {db_id[:8]}...{db_id[-4:]}):")
    print("-" * 60)

    try:
        # Получаем информацию о базе данных
        response = client.get(f"https://api.notion.com/v1/databases/{db_id}")
        response.raise_for_status()

        data = response.json()
        title = data.get("title", [{}])[0].get("plain_text", "Без названия")

        print(f"✅ База доступна: '{title}'")
        print(f"📊 Тип объекта: {data.get('object', 'unknown')}")

        # Проверяем свойства (столбцы)
        properties = data.get("properties", {})
        print(f"📋 Количество столбцов: {len(properties)}")

        print("\n📝 Структура столбцов:")
        for prop_name, prop_data in properties.items():
            prop_type = prop_data.get("type", "unknown")
            print(f"  • {prop_name}: {prop_type}")

            # Для select полей показываем опции
            if prop_type == "select" and "select" in prop_data:
                options = prop_data["select"].get("options", [])
                if options:
                    option_names = [opt.get("name", "") for opt in options]
                    print(f"    Опции: {', '.join(option_names)}")

        # Проверяем доступность для записи
        print("\n🔒 Права доступа:")
        print(f"  • Можно редактировать: {data.get('is_inline', False)}")

        return True

    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP ошибка: {e.response.status_code} {e.response.reason_phrase}")
        if e.response.status_code == 404:
            print("   Возможные причины:")
            print("   - Неправильный ID базы данных")
            print("   - База данных удалена")
            print("   - Нет доступа к базе данных")
        elif e.response.status_code == 401:
            print("   Возможные причины:")
            print("   - Неправильный NOTION_TOKEN")
            print("   - Токен истек")
        return False

    except Exception as e:
        print(f"❌ Ошибка: {type(e).__name__}: {e}")
        return False


def test_database_write(client: httpx.Client, db_id: str, db_name: str):
    """Тестирует возможность записи в базу данных."""
    print(f"\n🧪 Тест записи в базу '{db_name}':")
    print("-" * 40)

    try:
        # Пробуем создать тестовую страницу
        test_props = {"Name": {"title": [{"text": {"content": "🧪 Test Entry - Safe to Delete"}}]}}

        response = client.post(
            "https://api.notion.com/v1/pages",
            json={"parent": {"database_id": db_id}, "properties": test_props},
        )

        if response.status_code == 200:
            page_data = response.json()
            page_id = page_data["id"]
            print(f"✅ Тестовая запись создана: {page_id}")

            # Сразу удаляем тестовую запись
            delete_response = client.patch(
                f"https://api.notion.com/v1/pages/{page_id}", json={"archived": True}
            )

            if delete_response.status_code == 200:
                print("✅ Тестовая запись удалена")
            else:
                print(f"⚠️  Тестовая запись создана, но не удалена (ID: {page_id})")

            return True
        else:
            print(f"❌ Ошибка создания: {response.status_code}")
            print(f"   Ответ: {response.text}")
            return False

    except Exception as e:
        print(f"❌ Ошибка тестирования записи: {e}")
        return False


def main():
    """Главная функция диагностики."""
    print("🔧 Notion Database Diagnostics")
    print("=" * 50)

    # Проверяем переменные окружения
    if not check_env_vars():
        print("\n❌ Исправьте переменные окружения и попробуйте снова.")
        return

    # Создаем клиент
    try:
        client = create_notion_client()
        print("\n✅ Notion клиент создан успешно")
    except Exception as e:
        print(f"\n❌ Ошибка создания клиента: {e}")
        return

    # Проверяем базы данных
    commits_id = os.getenv("COMMITS_DB_ID")
    review_id = os.getenv("REVIEW_DB_ID")

    databases = [
        (os.getenv("NOTION_DB_MEETINGS_ID"), "Meetings"),
        (commits_id, "Commits"),
        (review_id, "Review Queue"),
    ]

    results = []
    for db_id, db_name in databases:
        if db_id:
            success = check_database(client, db_id, db_name)
            results.append((db_name, success))

            # Тестируем запись только для Meetings (самая простая структура)
            if success and db_name == "Meetings":
                test_database_write(client, db_id, db_name)
        else:
            print(f"\n❌ ID базы '{db_name}' не найден в переменных окружения")
            results.append((db_name, False))

    # Итоговый отчет
    print("\n" + "=" * 50)
    print("📊 ИТОГОВЫЙ ОТЧЕТ:")
    print("=" * 50)

    for db_name, success in results:
        status = "✅ OK" if success else "❌ ПРОБЛЕМА"
        print(f"{status} {db_name}")

    if all(success for _, success in results):
        print("\n🎉 Все базы данных настроены корректно!")
        print("   Проблема может быть в структуре полей.")
        print("   Запустите: python debug_notion.py --fields")
    else:
        print("\n⚠️  Обнаружены проблемы с базами данных.")
        print("   Проверьте ID баз и права доступа в Notion.")

    client.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--fields":
        print("🔧 Для проверки полей используйте основную команду")

    main()
