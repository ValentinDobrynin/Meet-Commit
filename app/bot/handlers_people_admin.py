"""
Административные команды для управления people.json через бота.
Позволяет добавлять новых людей, управлять алиасами, просматривать кандидатов.
"""

import json
import logging
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.commit_normalize import normalize_assignees
from app.core.llm_alias_suggestions import generate_alias_suggestions
from app.settings import settings

logger = logging.getLogger(__name__)

people_admin_router = Router()

# Пути к файлам
PEOPLE_JSON_PATH = Path("app/dictionaries/people.json")
CANDIDATES_JSON_PATH = Path("app/dictionaries/people_candidates.json")


class PeopleAdminStates(StatesGroup):
    """FSM состояния для управления людьми."""

    # Основное меню
    main_menu = State()

    # Добавление нового человека
    add_person_name = State()
    add_person_aliases = State()

    # Управление существующим человеком
    manage_person_select = State()
    manage_person_menu = State()
    manage_person_add_alias = State()

    # Работа с кандидатами
    candidates_review = State()
    candidates_select_person = State()
    candidates_add_aliases = State()

    # Работа с LLM предложениями
    llm_suggestions_review = State()
    llm_suggestions_select = State()

    # Ввод дополнительной информации
    add_role_input = State()
    add_company_input = State()
    final_confirmation = State()


def load_people_json() -> list[dict[str, Any]]:
    """Загружает people.json."""
    try:
        with open(PEOPLE_JSON_PATH, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except Exception as e:
        logger.error(f"Error loading people.json: {e}")
        return []


def save_people_json(data: list[dict[str, Any]]) -> bool:
    """Сохраняет people.json."""
    try:
        with open(PEOPLE_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved people.json with {len(data)} entries")
        return True
    except Exception as e:
        logger.error(f"Error saving people.json: {e}")
        return False


def load_candidates_json() -> dict[str, Any]:
    """Загружает people_candidates.json."""
    try:
        with open(CANDIDATES_JSON_PATH, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except Exception as e:
        logger.error(f"Error loading candidates.json: {e}")
        return {}


def get_person_by_name(people: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Находит человека по имени или алиасу."""
    # Используем normalize_assignees для нормализации имени
    normalized_names = normalize_assignees([name], [])
    if not normalized_names:
        return None

    normalized_name = normalized_names[0]

    for person in people:
        if person["name_en"].lower() == normalized_name.lower():
            return person
        for alias in person.get("aliases", []):
            if alias.lower() == normalized_name.lower():
                return person
    return None


def get_suggested_aliases(name: str, candidates: dict[str, Any]) -> list[str]:
    """Получает предложенные алиасы для имени из кандидатов."""
    suggestions = []
    name_parts = name.split()

    # Ищем в candidates по частям имени
    candidates_dict = candidates.get("candidates", {})

    for candidate, freq in candidates_dict.items():
        if freq < 2:  # Игнорируем редкие кандидаты
            continue

        candidate_lower = candidate.lower()

        # Проверяем различные типы совпадений
        match_found = False

        # 1. Точное совпадение с частью имени
        for part in name_parts:
            if part.lower() == candidate_lower:
                match_found = True
                break

        # 2. Кандидат содержит часть имени
        if not match_found:
            for part in name_parts:
                if len(part) >= 3 and part.lower() in candidate_lower:
                    match_found = True
                    break

        # 3. Часть имени содержит кандидата
        if not match_found:
            for part in name_parts:
                if len(candidate) >= 3 and candidate_lower in part.lower():
                    match_found = True
                    break

        # 4. Общие символы (для кириллицы/латиницы)
        if not match_found:
            for part in name_parts:
                if len(part) >= 3 and len(candidate) >= 3:
                    # Проверяем пересечение символов
                    part_chars = set(part.lower())
                    candidate_chars = set(candidate_lower)
                    common_chars = part_chars & candidate_chars
                    if len(common_chars) >= min(3, len(part) // 2, len(candidate) // 2):
                        match_found = True
                        break

        if match_found:
            suggestions.append(candidate)

    # Сортируем по частоте
    suggestions.sort(key=lambda x: candidates_dict.get(x, 0), reverse=True)
    return suggestions[:10]  # Максимум 10 предложений


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру главного меню управления людьми."""
    buttons = [
        [InlineKeyboardButton(text="👤 Добавить нового человека", callback_data="people_add_new")],
        [
            InlineKeyboardButton(
                text="✏️ Управлять существующим", callback_data="people_manage_existing"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔍 Просмотреть кандидатов", callback_data="people_review_candidates"
            )
        ],
        [
            InlineKeyboardButton(
                text="🧩 Перенести из кандидатов", callback_data="people_miner_start"
            )
        ],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="people_stats")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="people_close")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_person_list_keyboard(
    people: list[dict[str, Any]], page: int = 0, per_page: int = 8
) -> InlineKeyboardMarkup:
    """Создает клавиатуру со списком людей."""
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_people = people[start_idx:end_idx]

    buttons = []
    for person in page_people:
        name = person["name_en"]
        alias_count = len(person.get("aliases", []))
        text = f"{name} ({alias_count} алиасов)"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"people_select_{name}")])

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"people_list_page_{page-1}")
        )
    if end_idx < len(people):
        nav_buttons.append(
            InlineKeyboardButton(text="➡️ Далее", callback_data=f"people_list_page_{page+1}")
        )

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append(
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="people_main_menu")]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_person_menu_keyboard(person_name: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для управления конкретным человеком."""
    buttons = [
        [
            InlineKeyboardButton(
                text="➕ Добавить алиас", callback_data=f"people_add_alias_{person_name}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🗑️ Удалить алиас", callback_data=f"people_remove_alias_{person_name}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔍 Предложить алиасы", callback_data=f"people_suggest_aliases_{person_name}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🏢 Изменить роль", callback_data=f"people_edit_role_{person_name}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🏢 Изменить компанию", callback_data=f"people_edit_company_{person_name}"
            )
        ],
        [InlineKeyboardButton(text="🔙 К списку людей", callback_data="people_manage_existing")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_aliases_keyboard(
    aliases: list[str], person_name: str, action: str
) -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора алиасов."""
    buttons = []
    for alias in aliases[:10]:  # Максимум 10 на страницу
        emoji = "✅" if action == "add" else "❌"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{emoji} {alias}",
                    callback_data=f"people_{action}_alias_confirm_{person_name}_{alias}",
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"people_select_{person_name}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_suggestions_keyboard(
    suggestions: list[str], selected: list[str]
) -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора предложенных алиасов."""
    buttons = []

    # Алиасы (максимум 12 на страницу для удобства)
    for alias in suggestions[:12]:
        emoji = "✅" if alias in selected else "☐"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{emoji} {alias}", callback_data=f"people_toggle_alias_{alias}"
                )
            ]
        )

    # Кнопки управления
    control_buttons = []
    if selected:
        control_buttons.append(
            InlineKeyboardButton(
                text=f"➡️ Далее с выбранными ({len(selected)})",
                callback_data="people_proceed_with_selected",
            )
        )

    if control_buttons:
        buttons.append(control_buttons)

    buttons.append(
        [
            InlineKeyboardButton(text="⏭️ Только основное имя", callback_data="people_skip_aliases"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@people_admin_router.message(Command("people_admin"))
async def cmd_people_admin(message: Message, state: FSMContext) -> None:
    """Главная команда для управления people.json."""
    user_id = message.from_user.id if message.from_user else 0

    # Проверка прав администратора
    if not settings.is_admin(user_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return

    await state.set_state(PeopleAdminStates.main_menu)

    people = load_people_json()
    text = (
        "🧑‍💼 **Управление базой людей**\n\n"
        f"📊 Всего людей в базе: **{len(people)}**\n"
        f"📝 Всего алиасов: **{sum(len(p.get('aliases', [])) for p in people)}**\n\n"
        "Выберите действие:"
    )

    await message.answer(text, reply_markup=build_main_menu_keyboard(), parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню."""
    await state.set_state(PeopleAdminStates.main_menu)

    people = load_people_json()
    text = (
        "🧑‍💼 **Управление базой людей**\n\n"
        f"📊 Всего людей в базе: **{len(people)}**\n"
        f"📝 Всего алиасов: **{sum(len(p.get('aliases', [])) for p in people)}**\n\n"
        "Выберите действие:"
    )

    await callback.message.edit_text(
        text, reply_markup=build_main_menu_keyboard(), parse_mode="Markdown"
    )


@people_admin_router.callback_query(F.data == "people_add_new")
async def callback_add_new_person(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления нового человека."""
    await state.set_state(PeopleAdminStates.add_person_name)

    text = (
        "👤 **Добавление нового человека**\n\n"
        "Введите **каноническое имя** на английском языке\n"
        "(например: `John Smith`, `Maria Garcia`):"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")]]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.message(PeopleAdminStates.add_person_name)
async def process_add_person_name(message: Message, state: FSMContext) -> None:
    """Обработка ввода имени нового человека."""
    name = message.text.strip()

    if not name:
        await message.answer("❌ Имя не может быть пустым. Попробуйте еще раз:")
        return

    # Проверяем, что человек не существует
    people = load_people_json()
    if get_person_by_name(people, name):
        await message.answer(f"❌ Человек с именем '{name}' уже существует. Попробуйте другое имя:")
        return

    await state.update_data(new_person_name=name)
    await state.set_state(PeopleAdminStates.llm_suggestions_review)

    # Генерируем умные предложения через LLM
    await message.answer("🤖 Генерирую умные предложения алиасов через ИИ...")

    llm_suggestions = generate_alias_suggestions(name, [name])

    # Также получаем предложения из кандидатов
    candidates = load_candidates_json()
    candidates_suggestions = get_suggested_aliases(name, candidates)

    # Объединяем предложения (LLM приоритетнее)
    all_suggestions = []
    seen_lower = set()

    # Сначала LLM предложения
    for alias in llm_suggestions:
        if alias.lower() not in seen_lower:
            all_suggestions.append(alias)
            seen_lower.add(alias.lower())

    # Затем из кандидатов (если не дублируются)
    for alias in candidates_suggestions:
        if alias.lower() not in seen_lower:
            all_suggestions.append(alias)
            seen_lower.add(alias.lower())

    await state.update_data(suggested_aliases=all_suggestions)

    text = f"✅ **Имя принято:** `{name}`\n\n" "🤖 **Умные предложения алиасов**\n\n"

    if all_suggestions:
        text += f"Найдено **{len(all_suggestions)}** предложений:\n"
        for i, alias in enumerate(all_suggestions[:10], 1):
            text += f"{i}. `{alias}`\n"

        if len(all_suggestions) > 10:
            text += f"... и еще {len(all_suggestions) - 10}\n"

        text += "\n**Выберите действие:**"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Выбрать алиасы", callback_data="people_select_aliases"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="➕ Добавить вручную", callback_data="people_manual_aliases"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⏭️ Только основное имя", callback_data="people_skip_aliases"
                    )
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
            ]
        )
    else:
        text += "❌ Предложений не найдено.\n\n"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="➕ Добавить вручную", callback_data="people_manual_aliases"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⏭️ Только основное имя", callback_data="people_skip_aliases"
                    )
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
            ]
        )

    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.message(PeopleAdminStates.add_person_aliases)
async def process_add_person_aliases(message: Message, state: FSMContext) -> None:
    """Обработка ввода алиасов для нового человека."""
    data = await state.get_data()
    name = data.get("new_person_name")

    if not name:
        await message.answer("❌ Ошибка: имя не найдено. Начните заново.")
        await state.set_state(PeopleAdminStates.main_menu)
        return

    # Парсим алиасы
    aliases_text = (message.text or "").strip()
    if aliases_text.lower() == "/skip":
        manual_aliases = []  # Только основное имя
    else:
        # Разделяем по запятым или новым строкам
        manual_aliases: list[str] = []
        for line in aliases_text.split("\n"):
            for alias in line.split(","):
                alias = alias.strip()
                if alias and alias != name:  # Исключаем основное имя
                    manual_aliases.append(alias)

    # Объединяем с уже выбранными алиасами
    selected_aliases = data.get("selected_aliases", [])
    all_aliases = selected_aliases + manual_aliases

    # Убираем дубликаты
    unique_aliases = []
    seen_lower = set()
    for alias in all_aliases:
        if alias.lower() not in seen_lower:
            unique_aliases.append(alias)
            seen_lower.add(alias.lower())

    await state.update_data(selected_aliases=unique_aliases)
    await state.set_state(PeopleAdminStates.add_role_input)

    text = (
        f"✅ **Алиасы сохранены**\n\n"
        f"👤 **Имя:** `{name}`\n"
        f"📝 **Алиасы ({len(unique_aliases) + 1}):**\n"
        f"• `{name}` (основное)\n"
    )

    for alias in unique_aliases:
        text += f"• `{alias}`\n"

    text += (
        "\n🏢 **Введите роль/должность человека**\n"
        "(например: `Senior Developer`, `Product Manager`, `CEO`):\n\n"
        "Или отправьте `/skip` чтобы пропустить."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить роль", callback_data="people_skip_role")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
        ]
    )

    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_select_aliases")
async def callback_select_aliases(callback: CallbackQuery, state: FSMContext) -> None:
    """Показ предложенных алиасов для выбора."""
    data = await state.get_data()
    name = data.get("new_person_name")
    suggestions = data.get("suggested_aliases", [])

    if not name or not suggestions:
        await callback.message.edit_text("❌ Ошибка: данные не найдены.")
        return

    await state.set_state(PeopleAdminStates.llm_suggestions_select)
    await state.update_data(selected_aliases=[])

    text = (
        f"✅ **Выбор алиасов для {name}**\n\n"
        "Нажмите на алиасы которые хотите **ОСТАВИТЬ**.\n"
        "Выбранные алиасы будут отмечены ✅\n\n"
        "**Предложенные алиасы:**"
    )

    keyboard = _build_suggestions_keyboard(suggestions, [])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data.startswith("people_toggle_alias_"))
async def callback_toggle_alias(callback: CallbackQuery, state: FSMContext) -> None:
    """Переключение выбора алиаса."""
    alias = callback.data.replace("people_toggle_alias_", "")

    data = await state.get_data()
    selected_aliases = data.get("selected_aliases", [])
    suggestions = data.get("suggested_aliases", [])
    name = data.get("new_person_name")

    # Переключаем выбор
    if alias in selected_aliases:
        selected_aliases.remove(alias)
    else:
        selected_aliases.append(alias)

    await state.update_data(selected_aliases=selected_aliases)

    text = (
        f"✅ **Выбор алиасов для {name}**\n\n"
        "Нажмите на алиасы которые хотите **ОСТАВИТЬ**.\n"
        "Выбранные алиасы будут отмечены ✅\n\n"
        "**Предложенные алиасы:**"
    )

    keyboard = _build_suggestions_keyboard(suggestions, selected_aliases)

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_proceed_with_selected")
async def callback_proceed_with_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Переход к дополнительному вводу алиасов с сохранением выбранных."""
    data = await state.get_data()
    name = data.get("new_person_name")
    selected_aliases = data.get("selected_aliases", [])

    if not name:
        await callback.message.edit_text("❌ Ошибка: имя не найдено.")
        return

    # Переходим к вводу роли
    await state.set_state(PeopleAdminStates.add_role_input)

    text = (
        f"✅ **Выбранные алиасы сохранены**\n\n"
        f"👤 **Имя:** `{name}`\n"
        f"📝 **Алиасы ({len(selected_aliases) + 1}):**\n"
        f"• `{name}` (основное)\n"
    )

    for alias in selected_aliases:
        text += f"• `{alias}`\n"

    text += "\n**Выберите действие:**"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить еще алиасы", callback_data="people_add_more_aliases"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➡️ Продолжить к роли", callback_data="people_proceed_to_role"
                )
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_manual_aliases")
async def callback_manual_aliases(callback: CallbackQuery, state: FSMContext) -> None:
    """Переход к ручному вводу алиасов."""
    await state.set_state(PeopleAdminStates.add_person_aliases)

    data = await state.get_data()
    name = data.get("new_person_name")

    text = (
        f"✏️ **Ручной ввод алиасов для {name}**\n\n"
        "Введите алиасы через запятую или каждый с новой строки.\n"
        "Можете также отправить `/skip` чтобы добавить только основное имя.\n\n"
        "**Пример:**\n"
        "`John, Джон, Johnny, Иван Иванович`"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить алиасы", callback_data="people_skip_aliases")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.message(PeopleAdminStates.add_role_input)
async def process_role_input(message: Message, state: FSMContext) -> None:
    """Обработка ввода роли."""
    role = (message.text or "").strip()

    if role.lower() == "/skip":
        role = ""

    data = await state.get_data()

    # Проверяем режим: создание нового или редактирование существующего
    if data.get("edit_person"):
        # Режим редактирования существующего человека
        await _update_person_field_direct(message, state, "role", role, is_callback=False)
    else:
        # Режим создания нового человека
        await state.update_data(person_role=role)
        await state.set_state(PeopleAdminStates.add_company_input)

        text = (
            f"✅ **Роль сохранена:** `{role or 'не указана'}`\n\n"
            f"🏢 **Введите компанию человека**\n"
            "(например: `Yandex`, `Google`, `Freelancer`):\n\n"
            "Или отправьте `/skip` чтобы пропустить."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⏭️ Пропустить компанию", callback_data="people_skip_company"
                    )
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
            ]
        )

        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_add_more_aliases")
async def callback_add_more_aliases(callback: CallbackQuery, state: FSMContext) -> None:
    """Добавление дополнительных алиасов вручную."""
    await state.set_state(PeopleAdminStates.add_person_aliases)

    data = await state.get_data()
    name = data.get("new_person_name")
    selected_aliases = data.get("selected_aliases", [])

    text = (
        f"➕ **Добавление дополнительных алиасов для {name}**\n\n"
        f"📝 **Уже выбрано ({len(selected_aliases) + 1}):**\n"
        f"• `{name}` (основное)\n"
    )

    for alias in selected_aliases:
        text += f"• `{alias}`\n"

    text += (
        "\n✏️ **Введите дополнительные алиасы**\n"
        "через запятую или каждый с новой строки:\n\n"
        "**Пример:** `Johnny, Джонни, J.Smith`"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="people_proceed_to_role")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_proceed_to_role")
async def callback_proceed_to_role(callback: CallbackQuery, state: FSMContext) -> None:
    """Переход к вводу роли."""
    await state.set_state(PeopleAdminStates.add_role_input)

    data = await state.get_data()
    name = data.get("new_person_name")
    selected_aliases = data.get("selected_aliases", [])

    text = (
        f"🏢 **Ввод роли для {name}**\n\n"
        f"📝 **Алиасы ({len(selected_aliases) + 1}):** готовы\n\n"
        "🏢 **Введите роль/должность человека**\n"
        "(например: `Senior Developer`, `Product Manager`, `CEO`):\n\n"
        "Или отправьте `/skip` чтобы пропустить."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить роль", callback_data="people_skip_role")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_skip_role")
async def callback_skip_role(callback: CallbackQuery, state: FSMContext) -> None:
    """Пропуск ввода роли."""
    await state.update_data(person_role="")
    await state.set_state(PeopleAdminStates.add_company_input)

    text = (
        "⏭️ **Роль пропущена**\n\n"
        "🏢 **Введите компанию человека**\n"
        "(например: `Yandex`, `Google`, `Freelancer`):\n\n"
        "Или отправьте `/skip` чтобы пропустить."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏭️ Пропустить компанию", callback_data="people_skip_company"
                )
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.message(PeopleAdminStates.add_company_input)
async def process_company_input(message: Message, state: FSMContext) -> None:
    """Обработка ввода компании."""
    company = (message.text or "").strip()

    if company.lower() == "/skip":
        company = ""

    data = await state.get_data()

    # Проверяем режим: создание нового или редактирование существующего
    if data.get("edit_person"):
        # Режим редактирования существующего человека
        await _update_person_field_direct(message, state, "company", company, is_callback=False)
    else:
        # Режим создания нового человека
        await state.update_data(person_company=company)
        await _finalize_person_creation(message, state, is_callback=False)


@people_admin_router.callback_query(F.data == "people_skip_company")
async def callback_skip_company(callback: CallbackQuery, state: FSMContext) -> None:
    """Пропуск ввода компании."""
    await state.update_data(person_company="")
    await _finalize_person_creation(callback.message, state, is_callback=True)


async def _finalize_person_creation(message, state: FSMContext, is_callback: bool = False) -> None:
    """Финализация создания человека с полной информацией."""
    data = await state.get_data()
    name = data.get("new_person_name")
    selected_aliases = data.get("selected_aliases", [])
    role = data.get("person_role", "")
    company = data.get("person_company", "")

    if not name:
        error_text = "❌ Ошибка: имя не найдено."
        if is_callback:
            await message.edit_text(error_text)
        else:
            await message.answer(error_text)
        return

    # Формируем финальные алиасы
    final_aliases = [name]
    for alias in selected_aliases:
        if alias not in final_aliases:
            final_aliases.append(alias)

    # Создаем человека с новыми полями
    people = load_people_json()
    new_person = {"name_en": name, "aliases": final_aliases}

    # Добавляем роль и компанию если указаны
    if role:
        new_person["role"] = role
    if company:
        new_person["company"] = company

    people.append(new_person)

    if save_people_json(people):
        text = (
            f"✅ **Человек успешно добавлен!**\n\n"
            f"👤 **Имя:** `{name}`\n"
            f"📝 **Алиасы ({len(final_aliases)}):**\n"
        )
        for alias in final_aliases:
            text += f"• `{alias}`\n"

        if role:
            text += f"\n🏢 **Роль:** `{role}`"
        if company:
            text += f"\n🏢 **Компания:** `{company}`"

        logger.info(
            f"Admin {message.from_user.id if hasattr(message, 'from_user') else 'unknown'} added new person: {name} with {len(final_aliases)} aliases, role: {role}, company: {company}"
        )
    else:
        text = "❌ Ошибка при сохранении. Попробуйте еще раз."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")]
        ]
    )

    if is_callback:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")

    await state.set_state(PeopleAdminStates.main_menu)


@people_admin_router.callback_query(F.data == "people_skip_aliases")
async def callback_skip_aliases(callback: CallbackQuery, state: FSMContext) -> None:
    """Пропуск добавления алиасов - переход к вводу роли."""
    await state.update_data(selected_aliases=[])
    await state.set_state(PeopleAdminStates.add_role_input)

    data = await state.get_data()
    name = data.get("new_person_name")

    text = (
        f"⏭️ **Алиасы пропущены**\n\n"
        f"👤 **Имя:** `{name}`\n"
        f"📝 **Алиасы:** только основное имя\n\n"
        "🏢 **Введите роль/должность человека**\n"
        "(например: `Senior Developer`, `Product Manager`, `CEO`):\n\n"
        "Или отправьте `/skip` чтобы пропустить."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить роль", callback_data="people_skip_role")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="people_main_menu")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data.startswith("people_list_page_"))
async def callback_list_page(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка пагинации списка людей."""
    page = int(callback.data.replace("people_list_page_", ""))

    await state.set_state(PeopleAdminStates.manage_person_select)

    people = load_people_json()
    if not people:
        text = "📭 База людей пуста. Добавьте первого человека!"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👤 Добавить человека", callback_data="people_add_new")],
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")],
            ]
        )
    else:
        text = (
            f"👥 **Выберите человека для управления** ({len(people)} всего, страница {page + 1}):"
        )
        keyboard = build_person_list_keyboard(people, page)

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_manage_existing")
async def callback_manage_existing(callback: CallbackQuery, state: FSMContext) -> None:
    """Показ списка существующих людей для управления."""
    await state.set_state(PeopleAdminStates.manage_person_select)

    people = load_people_json()
    if not people:
        text = "📭 База людей пуста. Добавьте первого человека!"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👤 Добавить человека", callback_data="people_add_new")],
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")],
            ]
        )
    else:
        text = f"👥 **Выберите человека для управления** ({len(people)} всего):"
        keyboard = build_person_list_keyboard(people)

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data.startswith("people_select_"))
async def callback_select_person(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор конкретного человека для управления."""
    person_name = callback.data.replace("people_select_", "")

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await callback.answer("❌ Человек не найден")
        return

    await state.update_data(selected_person=person_name)
    await state.set_state(PeopleAdminStates.manage_person_menu)

    aliases = person.get("aliases", [])
    role = person.get("role", "")
    company = person.get("company", "")

    text = f"👤 **{person['name_en']}**\n\n" f"📝 **Алиасы ({len(aliases)}):**\n"

    for alias in aliases:
        text += f"• `{alias}`\n"

    if role:
        text += f"\n🏢 **Роль:** `{role}`"
    if company:
        text += f"\n🏢 **Компания:** `{company}`"

    text += "\n\nВыберите действие:"

    await callback.message.edit_text(
        text, reply_markup=build_person_menu_keyboard(person_name), parse_mode="Markdown"
    )


@people_admin_router.callback_query(F.data == "people_stats")
async def callback_people_stats(callback: CallbackQuery) -> None:
    """Показ статистики по базе людей."""
    people = load_people_json()
    candidates = load_candidates_json()

    if not people:
        text = "📭 База людей пуста."
    else:
        total_aliases = sum(len(p.get("aliases", [])) for p in people)
        avg_aliases = total_aliases / len(people)

        # Топ по количеству алиасов
        top_people = sorted(people, key=lambda x: len(x.get("aliases", [])), reverse=True)[:5]

        text = (
            f"📊 **Статистика базы людей**\n\n"
            f"👥 Всего людей: **{len(people)}**\n"
            f"📝 Всего алиасов: **{total_aliases}**\n"
            f"📈 Среднее алиасов на человека: **{avg_aliases:.1f}**\n\n"
            f"🏆 **Топ по количеству алиасов:**\n"
        )

        for i, person in enumerate(top_people, 1):
            alias_count = len(person.get("aliases", []))
            text += f"{i}. `{person['name_en']}` — {alias_count} алиасов\n"

    # Статистика кандидатов
    candidates_count = len(candidates.get("candidates", {}))
    text += f"\n🔍 **Кандидатов для анализа:** {candidates_count}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")]
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data.startswith("people_add_alias_"))
async def callback_add_alias(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления алиаса."""
    person_name = callback.data.replace("people_add_alias_", "")

    await state.update_data(selected_person=person_name, action="add_alias")
    await state.set_state(PeopleAdminStates.manage_person_add_alias)

    text = (
        f"➕ **Добавление алиаса для {person_name}**\n\n"
        "Введите новый алиас или несколько алиасов через запятую:"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"people_select_{person_name}")]
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.message(PeopleAdminStates.manage_person_add_alias)
async def process_add_alias(message: Message, state: FSMContext) -> None:
    """Обработка добавления алиаса."""
    data = await state.get_data()
    person_name = data.get("selected_person")

    if not person_name:
        await message.answer("❌ Ошибка: человек не выбран.")
        return

    # Парсим новые алиасы
    aliases_text = message.text.strip()
    new_aliases = []
    for line in aliases_text.split("\n"):
        for alias in line.split(","):
            alias = alias.strip()
            if alias:
                new_aliases.append(alias)

    if not new_aliases:
        await message.answer("❌ Не введено ни одного алиаса. Попробуйте еще раз:")
        return

    # Обновляем базу
    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await message.answer("❌ Человек не найден в базе.")
        return

    # Добавляем новые алиасы (избегаем дубликатов)
    existing_aliases = [a.lower() for a in person.get("aliases", [])]
    added_aliases = []

    for alias in new_aliases:
        if alias.lower() not in existing_aliases:
            person.setdefault("aliases", []).append(alias)
            added_aliases.append(alias)
            existing_aliases.append(alias.lower())

    if added_aliases and save_people_json(people):
        text = (
            f"✅ **Алиасы добавлены для {person_name}!**\n\n"
            f"➕ **Добавлено ({len(added_aliases)}):**\n"
        )
        for alias in added_aliases:
            text += f"• `{alias}`\n"

        if len(added_aliases) < len(new_aliases):
            skipped = len(new_aliases) - len(added_aliases)
            text += f"\n⚠️ Пропущено {skipped} дубликатов"

        logger.info(
            f"Admin {message.from_user.id} added {len(added_aliases)} aliases to {person_name}"
        )
    else:
        text = "❌ Не удалось добавить алиасы (возможно, все уже существуют)."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 К профилю", callback_data=f"people_select_{person_name}"
                )
            ],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")],
        ]
    )

    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    await state.set_state(PeopleAdminStates.manage_person_menu)


@people_admin_router.callback_query(F.data.startswith("people_remove_alias_"))
async def callback_remove_alias(callback: CallbackQuery, state: FSMContext) -> None:
    """Показ алиасов для удаления."""
    person_name = callback.data.replace("people_remove_alias_", "")

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await callback.answer("❌ Человек не найден")
        return

    aliases = person.get("aliases", [])
    if len(aliases) <= 1:
        await callback.answer("❌ Нельзя удалить все алиасы")
        return

    # Исключаем основное имя из удаления
    removable_aliases = [a for a in aliases if a != person["name_en"]]

    if not removable_aliases:
        await callback.answer("❌ Нет алиасов для удаления")
        return

    text = f"🗑️ **Удаление алиасов для {person_name}**\n\n" "Выберите алиасы для удаления:"

    keyboard = build_aliases_keyboard(removable_aliases, person_name, "remove")

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data.startswith("people_remove_alias_confirm_"))
async def callback_remove_alias_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение удаления алиаса."""
    parts = callback.data.replace("people_remove_alias_confirm_", "").split("_", 1)
    if len(parts) != 2:
        await callback.answer("❌ Ошибка в данных")
        return

    person_name, alias_to_remove = parts

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await callback.answer("❌ Человек не найден")
        return

    aliases = person.get("aliases", [])
    if alias_to_remove in aliases and alias_to_remove != person["name_en"]:
        aliases.remove(alias_to_remove)

        if save_people_json(people):
            await callback.answer(f"✅ Алиас '{alias_to_remove}' удален")
            logger.info(
                f"Admin {callback.from_user.id} removed alias '{alias_to_remove}' from {person_name}"
            )

            # Обновляем отображение
            text = f"👤 **{person['name_en']}**\n\n" f"📝 **Алиасы ({len(aliases)}):**\n"

            for alias in aliases:
                text += f"• `{alias}`\n"

            text += "\nВыберите действие:"

            await callback.message.edit_text(
                text, reply_markup=build_person_menu_keyboard(person_name), parse_mode="Markdown"
            )
        else:
            await callback.answer("❌ Ошибка при сохранении")
    else:
        await callback.answer("❌ Алиас не найден или нельзя удалить")


@people_admin_router.callback_query(F.data.startswith("people_suggest_aliases_"))
async def callback_suggest_aliases(callback: CallbackQuery, state: FSMContext) -> None:
    """Предложение алиасов из кандидатов."""
    person_name = callback.data.replace("people_suggest_aliases_", "")

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await callback.answer("❌ Человек не найден")
        return

    candidates = load_candidates_json()
    suggested_aliases = get_suggested_aliases(person_name, candidates)

    # Исключаем уже существующие алиасы
    existing_aliases = [a.lower() for a in person.get("aliases", [])]
    new_suggestions = [a for a in suggested_aliases if a.lower() not in existing_aliases]

    if not new_suggestions:
        text = (
            f"🤖 **Предложения алиасов для {person_name}**\n\n"
            "❌ Новых предложений не найдено.\n"
            "Все подходящие алиасы уже добавлены."
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 Назад", callback_data=f"people_select_{person_name}"
                    )
                ]
            ]
        )
    else:
        text = (
            f"🤖 **Предложения алиасов для {person_name}**\n\n"
            f"Найдено {len(new_suggestions)} новых предложений из анализа текстов.\n"
            "Выберите алиасы для добавления:"
        )
        keyboard = build_aliases_keyboard(new_suggestions, person_name, "add")

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data.startswith("people_add_alias_confirm_"))
async def callback_add_alias_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение добавления предложенного алиаса."""
    parts = callback.data.replace("people_add_alias_confirm_", "").split("_", 1)
    if len(parts) != 2:
        await callback.answer("❌ Ошибка в данных")
        return

    person_name, alias_to_add = parts

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await callback.answer("❌ Человек не найден")
        return

    aliases = person.get("aliases", [])
    if alias_to_add.lower() not in [a.lower() for a in aliases]:
        aliases.append(alias_to_add)

        if save_people_json(people):
            await callback.answer(f"✅ Алиас '{alias_to_add}' добавлен")
            logger.info(
                f"Admin {callback.from_user.id} added suggested alias '{alias_to_add}' to {person_name}"
            )
        else:
            await callback.answer("❌ Ошибка при сохранении")
    else:
        await callback.answer("❌ Алиас уже существует")


@people_admin_router.callback_query(F.data == "people_review_candidates")
async def callback_review_candidates(callback: CallbackQuery, state: FSMContext) -> None:
    """Просмотр кандидатов из people_candidates.json."""
    candidates = load_candidates_json()
    candidates_dict = candidates.get("candidates", {})

    if not candidates_dict:
        text = "📭 Кандидаты не найдены. Запустите анализ текстов (people_miner_v2)."
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")]
            ]
        )
    else:
        # Сортируем по частоте
        sorted_candidates = sorted(candidates_dict.items(), key=lambda x: x[1], reverse=True)
        top_candidates = sorted_candidates[:20]  # Топ 20

        text = (
            f"🔍 **Анализ кандидатов**\n\n"
            f"📊 Всего кандидатов: **{len(candidates_dict)}**\n"
            f"🏆 Топ-20 по частоте упоминаний:\n\n"
        )

        for candidate, freq in top_candidates:
            text += f"• `{candidate}` — {freq} раз\n"

        text += (
            "\n💡 **Рекомендации:**\n"
            "• Кандидаты с частотой 3+ могут быть именами\n"
            "• Проверьте контекст в исходных текстах\n"
            "• Добавьте подходящие через 'Добавить человека'"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")]
            ]
        )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_miner_start")
async def callback_miner_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Запуск people_miner v2 из интерфейса people_admin."""
    # Используем People Miner v2 (новый формат кандидатов)
    try:
        from app.bot.handlers_people_v2 import _show_candidate_page
        from app.bot.states.people_states import PeopleStates
        from app.core.people_miner2 import list_candidates

        # Проверяем есть ли кандидаты в новом формате
        items, total = list_candidates(sort="freq", page=1, per_page=1)

        if not items or total == 0:
            text = (
                "🧩 **People Miner v2 - Перенос кандидатов**\n\n"
                "❌ Кандидатов для обработки нет.\n"
                "Используйте бота для обработки встреч, чтобы собрать новых кандидатов.\n\n"
                "💡 **Совет:** Добавьте несколько встреч с текстом, система автоматически найдет потенциальных людей."
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🏠 В главное меню", callback_data="people_main_menu"
                        )
                    ]
                ]
            )

            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            # Переключаемся в состояние People Miner v2
            await state.set_state(PeopleStates.v2_reviewing)
            await state.update_data(current_page=1, sort_mode="freq")

            # Показываем первую страницу кандидатов
            await _show_candidate_page(callback, 1, "freq", edit_message=True)

        logger.info(f"Admin {callback.from_user.id} started people_miner from people_admin")

    except ImportError as e:
        logger.error(f"Failed to import people_miner_v2 functions: {e}")
        await callback.message.edit_text(
            "❌ Ошибка: не удалось загрузить People Miner v2.\n"
            "Проверьте что модуль handlers_people_v2 доступен."
        )


@people_admin_router.callback_query(F.data == "people_close")
async def callback_close(callback: CallbackQuery, state: FSMContext) -> None:
    """Закрытие меню управления людьми."""
    await state.clear()
    await callback.message.edit_text("✅ Управление людьми завершено.")


# Добавляем команду в help
@people_admin_router.message(Command("people_help"))
async def cmd_people_help(message: Message) -> None:
    """Справка по командам управления людьми."""
    user_id = message.from_user.id if message.from_user else 0

    if not settings.is_admin(user_id):
        await message.answer("❌ У вас нет прав для просмотра этой справки.")
        return

    text = (
        "🧑‍💼 **Справка по управлению людьми**\n\n"
        "**Доступные команды:**\n"
        "• `/people_admin` — главное меню управления\n"
        "• `/people_help` — эта справка\n\n"
        "**Возможности:**\n"
        "👤 **Добавление людей** — создание новых записей\n"
        "✏️ **Управление алиасами** — добавление/удаление\n"
        "🤖 **Умные предложения** — алиасы из анализа текстов\n"
        "📊 **Статистика** — информация о базе\n\n"
        "**Источники предложений:**\n"
        "• Анализ текстов встреч (people_miner_v2)\n"
        "• Частотный анализ упоминаний\n"
        "• Контекстные совпадения\n\n"
        "Все изменения сохраняются в `people.json` и сразу доступны боту."
    )

    await message.answer(text, parse_mode="Markdown")


# =============== ОБРАБОТЧИКИ РЕДАКТИРОВАНИЯ РОЛИ И КОМПАНИИ ===============


@people_admin_router.callback_query(F.data.startswith("people_edit_role_"))
async def callback_edit_role(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало редактирования роли."""
    person_name = callback.data.replace("people_edit_role_", "")

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await callback.answer("❌ Человек не найден")
        return

    await state.update_data(edit_person=person_name, edit_field="role")
    await state.set_state(PeopleAdminStates.add_role_input)

    current_role = person.get("role", "")

    text = (
        f"🏢 **Редактирование роли для {person_name}**\n\n"
        f"📋 **Текущая роль:** `{current_role or 'не указана'}`\n\n"
        "Введите новую роль/должность:\n"
        "(например: `Senior Developer`, `Product Manager`, `CEO`)\n\n"
        "Или отправьте `/skip` чтобы очистить роль."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Очистить роль", callback_data="people_clear_role")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"people_select_{person_name}")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data.startswith("people_edit_company_"))
async def callback_edit_company(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало редактирования компании."""
    person_name = callback.data.replace("people_edit_company_", "")

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await callback.answer("❌ Человек не найден")
        return

    await state.update_data(edit_person=person_name, edit_field="company")
    await state.set_state(PeopleAdminStates.add_company_input)

    current_company = person.get("company", "")

    text = (
        f"🏢 **Редактирование компании для {person_name}**\n\n"
        f"📋 **Текущая компания:** `{current_company or 'не указана'}`\n\n"
        "Введите новую компанию:\n"
        "(например: `Yandex`, `Google`, `Freelancer`)\n\n"
        "Или отправьте `/skip` чтобы очистить компанию."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑️ Очистить компанию", callback_data="people_clear_company"
                )
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"people_select_{person_name}")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@people_admin_router.callback_query(F.data == "people_clear_role")
async def callback_clear_role(callback: CallbackQuery, state: FSMContext) -> None:
    """Очистка роли."""
    await _update_person_field(callback, state, "role", "")


@people_admin_router.callback_query(F.data == "people_clear_company")
async def callback_clear_company(callback: CallbackQuery, state: FSMContext) -> None:
    """Очистка компании."""
    await _update_person_field(callback, state, "company", "")


async def _update_person_field(
    callback: CallbackQuery, state: FSMContext, field: str, value: str
) -> None:
    """Обновление поля человека (для callback)."""
    data = await state.get_data()
    person_name = data.get("edit_person")

    if not person_name:
        await callback.answer("❌ Ошибка: человек не выбран")
        return

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        await callback.answer("❌ Человек не найден")
        return

    # Обновляем поле
    if value:
        person[field] = value
    elif field in person:
        del person[field]

    if save_people_json(people):
        field_name = "роль" if field == "role" else "компанию"
        action = "обновлена" if value else "очищена"

        await callback.answer(f"✅ {field_name.capitalize()} {action}")
        logger.info(f"Admin {callback.from_user.id} updated {field} for {person_name}: '{value}'")

        # Возвращаемся к профилю человека
        await callback_select_person(callback, state)
    else:
        await callback.answer("❌ Ошибка при сохранении")


async def _update_person_field_direct(
    message, state: FSMContext, field: str, value: str, is_callback: bool = False
) -> None:
    """Обновление поля человека (для прямого ввода)."""
    data = await state.get_data()
    person_name = data.get("edit_person")

    if not person_name:
        error_text = "❌ Ошибка: человек не выбран"
        if is_callback:
            await message.edit_text(error_text)
        else:
            await message.answer(error_text)
        return

    people = load_people_json()
    person = get_person_by_name(people, person_name)

    if not person:
        error_text = "❌ Человек не найден"
        if is_callback:
            await message.edit_text(error_text)
        else:
            await message.answer(error_text)
        return

    # Обновляем поле
    if value:
        person[field] = value
    elif field in person:
        del person[field]

    if save_people_json(people):
        field_name = "роль" if field == "role" else "компанию"
        action = "обновлена" if value else "очищена"

        text = f"✅ {field_name.capitalize()} {action}: `{value or 'очищено'}`"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="👤 К профилю", callback_data=f"people_select_{person_name}"
                    )
                ],
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="people_main_menu")],
            ]
        )

        if is_callback:
            await message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")

        logger.info(
            f"Admin {message.from_user.id if hasattr(message, 'from_user') else 'unknown'} updated {field} for {person_name}: '{value}'"
        )
        await state.set_state(PeopleAdminStates.manage_person_menu)
    else:
        error_text = "❌ Ошибка при сохранении"
        if is_callback:
            await message.edit_text(error_text)
        else:
            await message.answer(error_text)
