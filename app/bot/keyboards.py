"""Клавиатуры для пагинации и навигации."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_pagination_keyboard(
    query_type: str,
    current_page: int,
    total_pages: int,
    total_items: int = 0,
    *,
    extra_params: str = "",
) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для пагинации результатов запросов.

    Args:
        query_type: Тип запроса (commits, mine, theirs, due, today, by_tag)
        current_page: Текущая страница (1-based)
        total_pages: Общее количество страниц
        total_items: Общее количество элементов
        extra_params: Дополнительные параметры (например, тег для by_tag)

    Returns:
        Клавиатура с кнопками навигации
    """
    buttons = []

    # Кнопки навигации
    nav_buttons = []

    if current_page > 1:
        callback_data = f"commits:{query_type}:{current_page - 1}"
        if extra_params:
            callback_data += f":{extra_params}"
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Пред", callback_data=callback_data))

    if current_page < total_pages:
        callback_data = f"commits:{query_type}:{current_page + 1}"
        if extra_params:
            callback_data += f":{extra_params}"
        nav_buttons.append(InlineKeyboardButton(text="След ➡️", callback_data=callback_data))

    # Если есть кнопки навигации, добавляем их
    if nav_buttons:
        buttons.append(nav_buttons)

    # Кнопка обновления (всегда есть)
    refresh_callback = f"commits:{query_type}:{current_page}"
    if extra_params:
        refresh_callback += f":{extra_params}"

    buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=refresh_callback)])

    # Информационная кнопка с номером страницы (всегда показываем если есть элементы)
    if total_items > 0:
        if total_pages > 1:
            info_text = f"📄 {current_page}/{total_pages} ({total_items} всего)"
        else:
            info_text = f"📊 {total_items} коммитов"
        buttons.append([InlineKeyboardButton(text=info_text, callback_data="noop")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_query_help_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру с подсказками по командам запросов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Все", callback_data="commits:recent:1"),
                InlineKeyboardButton(text="👤 Мои", callback_data="commits:mine:1"),
            ],
            [
                InlineKeyboardButton(text="👥 Чужие", callback_data="commits:theirs:1"),
                InlineKeyboardButton(text="⏰ Неделя", callback_data="commits:due:1"),
            ],
            [
                InlineKeyboardButton(text="🔥 Сегодня", callback_data="commits:today:1"),
                InlineKeyboardButton(text="🏷️ По тегу", callback_data="commits:help_tag:1"),
            ],
        ]
    )


def build_commit_action_keyboard(commit_id: str) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с быстрыми действиями для коммита.

    Args:
        commit_id: ID коммита для действий

    Returns:
        Клавиатура с кнопками действий
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выполнено", callback_data=f"commit_action:done:{commit_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data=f"commit_action:drop:{commit_id}"
                ),
            ],
            [
                InlineKeyboardButton(text="🔗 Открыть", url=f"https://notion.so/{commit_id}"),
            ],
        ]
    )
