"""
Модуль красивого форматирования сообщений для Telegram бота.

Обеспечивает единообразное отображение карточек встреч, коммитов и других элементов
с использованием эмодзи, HTML разметки и структурированного layout'а.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, NamedTuple

# Эмодзи для статусов
STATUS_EMOJI = {
    "open": "🟡",
    "done": "✅",
    "completed": "✅",
    "resolved": "✅",
    "dropped": "❌",
    "cancelled": "❌",
    "pending": "🟠",
    "needs-review": "🔍",
    "in-progress": "🔄",
}

# Эмодзи для направлений (direction)
DIRECTION_EMOJI = {
    "mine": "📤",
    "theirs": "📥",
    "mutual": "🤝",
}

# Эмодзи для приоритета по срокам
URGENCY_EMOJI = {
    "overdue": "🚨",
    "today": "⚡",
    "this_week": "⏰",
    "next_week": "📅",
    "no_due": "📋",
}

# Эмодзи для категорий тегов
TAG_CATEGORY_EMOJI = {
    "Finance": "💰",
    "Business": "🏢",
    "People": "👥",
    "Projects": "📁",
    "Topic": "🎯",
    "Area": "🗂️",
}


class AdaptiveLimits(NamedTuple):
    """Адаптивные лимиты для разных типов устройств."""

    title: int
    description: int
    attendees: int
    tags: int
    id_length: int


# Профили лимитов для разных устройств
DEVICE_LIMITS = {
    "mobile": AdaptiveLimits(title=100, description=300, attendees=3, tags=3, id_length=6),
    "tablet": AdaptiveLimits(title=100, description=300, attendees=4, tags=4, id_length=8),
    "desktop": AdaptiveLimits(title=100, description=300, attendees=6, tags=5, id_length=12),
}


# Эвристики для определения типа устройства на основе длины сообщения
def _detect_device_type(context_hint: str | None = None) -> str:
    """
    Определяет тип устройства для адаптивного форматирования.

    Args:
        context_hint: Подсказка о контексте (mobile, tablet, desktop)

    Returns:
        Тип устройства: mobile, tablet, desktop
    """
    if context_hint and context_hint.lower() in DEVICE_LIMITS:
        return context_hint.lower()

    # По умолчанию используем tablet как компромисс между mobile и desktop
    return "tablet"


def _get_adaptive_limits(device_type: str | None = None) -> AdaptiveLimits:
    """Получает адаптивные лимиты для устройства."""
    device = _detect_device_type(device_type)
    return DEVICE_LIMITS.get(device, DEVICE_LIMITS["tablet"])


def _get_urgency_level(due_iso: str | None) -> str:
    """Определяет уровень срочности на основе дедлайна."""
    if not due_iso:
        return "no_due"

    try:
        from datetime import date

        due_date = datetime.fromisoformat(due_iso.replace("Z", "+00:00")).date()
        today = date.today()

        diff_days = (due_date - today).days

        if diff_days < 0:
            return "overdue"
        elif diff_days == 0:
            return "today"
        elif diff_days <= 7:
            return "this_week"
        elif diff_days <= 14:
            return "next_week"
        else:
            return "no_due"

    except (ValueError, TypeError):
        return "no_due"


def _format_date(date_str: str | None) -> str:
    """Форматирует дату для отображения."""
    if not date_str:
        return "—"

    try:
        # Пробуем разные форматы
        if len(date_str) == 10 and "-" in date_str:  # YYYY-MM-DD
            year, month, day = date_str.split("-")
            return f"{day}.{month}.{year}"
        elif len(date_str) > 10:  # ISO with time
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y")
        else:
            return date_str
    except (ValueError, TypeError):
        return date_str or "—"


def _format_tags_list(tags: list[str], max_tags: int = 3, *, device_type: str | None = None) -> str:
    """
    Форматирует список тегов с эмодзи категорий и адаптивными лимитами.

    Args:
        tags: Список тегов
        max_tags: Базовый лимит тегов (может быть переопределен адаптивными лимитами)
        device_type: Тип устройства для адаптивных лимитов
    """
    if not tags:
        return "—"

    # Используем адаптивные лимиты если не задан конкретный max_tags
    if device_type and max_tags == 3:  # 3 - дефолтное значение
        limits = _get_adaptive_limits(device_type)
        max_tags = limits.tags

    formatted_tags = []
    for tag in tags[:max_tags]:
        if "/" in tag:
            category, name = tag.split("/", 1)
            emoji = TAG_CATEGORY_EMOJI.get(category, "🏷️")
            formatted_tags.append(f"{emoji} <code>{name}</code>")
        else:
            formatted_tags.append(f"🏷️ <code>{tag}</code>")

    result = " • ".join(formatted_tags)

    if len(tags) > max_tags:
        result += f" <i>+{len(tags) - max_tags}</i>"

    return result


def _escape_html(text: str) -> str:
    """Экранирует HTML символы в тексте."""
    if not text:
        return ""

    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _truncate_text(text: str, max_length: int = 80, *, device_type: str | None = None) -> str:
    """
    Обрезает текст с умным добавлением многоточия и адаптивными лимитами.

    Args:
        text: Текст для обрезания
        max_length: Базовый лимит (может быть переопределен адаптивными лимитами)
        device_type: Тип устройства для адаптивных лимитов

    Returns:
        Обрезанный текст с многоточием если необходимо
    """
    if not text:
        return "—"

    text = text.strip()

    # Используем адаптивные лимиты если не задан конкретный max_length
    if device_type and max_length == 80:  # 80 - дефолтное значение
        limits = _get_adaptive_limits(device_type)
        max_length = limits.description

    if len(text) <= max_length:
        return text

    # Пытаемся обрезать по словам
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")

    if last_space > max_length * 0.7:  # Если можем обрезать по слову без большой потери
        truncated = truncated[:last_space]

    return truncated + "..."


def format_meeting_card(
    meeting: dict[str, Any], *, show_url: bool = True, device_type: str | None = None
) -> str:
    """
    Форматирует карточку встречи для красивого отображения с адаптивными лимитами.

    Args:
        meeting: Данные встречи (из Notion или internal format)
        show_url: Показывать ли ссылку на Notion
        device_type: Тип устройства для адаптивных лимитов (mobile, tablet, desktop)

    Returns:
        Отформатированная HTML строка для Telegram
    """
    # Извлекаем данные с fallback значениями
    title = meeting.get("Name") or meeting.get("title") or "Встреча без названия"
    date_str = meeting.get("Date") or meeting.get("date") or meeting.get("meeting_date")
    tags = meeting.get("Tags") or meeting.get("tags") or []
    attendees = meeting.get("Attendees") or meeting.get("attendees") or []
    url = meeting.get("url") or meeting.get("notion_url")

    # Получаем адаптивные лимиты
    limits = _get_adaptive_limits(device_type)

    # Форматируем компоненты с адаптивными лимитами
    title_escaped = _escape_html(_truncate_text(str(title), limits.title, device_type=device_type))
    formatted_date = _format_date(date_str)

    attendees_str = ", ".join(str(a) for a in attendees[: limits.attendees]) if attendees else "—"
    if len(attendees) > limits.attendees:
        attendees_str += f" <i>+{len(attendees) - limits.attendees}</i>"

    tags_str = _format_tags_list(tags, max_tags=limits.tags, device_type=device_type)

    # Собираем карточку
    card = (
        f"📅 <b>{title_escaped}</b>\n"
        f"🗓️ <b>Дата:</b> {formatted_date}\n"
        f"👥 <b>Участники:</b> {attendees_str}\n"
        f"🏷️ <b>Теги:</b> {tags_str}"
    )

    if show_url and url:
        card += f"\n🔗 <a href='{url}'>Открыть в Notion</a>"

    return card


def format_commit_card(
    commit: dict[str, Any], *, show_meeting_link: bool = False, device_type: str | None = None
) -> str:
    """
    Форматирует карточку коммита для красивого отображения с адаптивными лимитами.

    Args:
        commit: Данные коммита (из Review или Commits)
        show_meeting_link: Показывать ли ссылку на встречу
        device_type: Тип устройства для адаптивных лимитов (mobile, tablet, desktop)

    Returns:
        Отформатированная HTML строка для Telegram
    """
    # Извлекаем данные
    text = commit.get("text") or commit.get("Text") or commit.get("title") or "Задача без описания"
    status = commit.get("status") or commit.get("Status") or "open"
    direction = commit.get("direction") or commit.get("Direction") or "theirs"
    assignees = commit.get("assignees") or commit.get("Assignee") or []
    from_person = commit.get("from_person") or []
    tags = commit.get("tags") or commit.get("Tags") or []
    due_iso = commit.get("due_iso") or commit.get("Due")
    short_id = commit.get("short_id") or commit.get("page_id", "")[-6:]

    # Получаем эмодзи
    status_emoji = STATUS_EMOJI.get(str(status).lower(), "⬜")
    direction_emoji = DIRECTION_EMOJI.get(str(direction).lower(), "📋")
    urgency_emoji = URGENCY_EMOJI.get(_get_urgency_level(due_iso), "📋")

    # Получаем адаптивные лимиты
    limits = _get_adaptive_limits(device_type)

    # Форматируем компоненты с адаптивными лимитами
    text_escaped = _escape_html(
        _truncate_text(str(text), limits.description, device_type=device_type)
    )

    # Форматируем исполнителей с адаптивным лимитом
    max_assignees = min(limits.attendees, 3)  # Для коммитов не более 3 исполнителей
    if isinstance(assignees, list) and assignees:
        who = ", ".join(str(a) for a in assignees[:max_assignees])
        if len(assignees) > max_assignees:
            who += f" <i>+{len(assignees) - max_assignees}</i>"
    elif isinstance(assignees, str) and assignees:
        who = str(assignees)
    else:
        who = "—"

    # Форматируем дедлайн
    due_formatted = _format_date(due_iso)

    # Форматируем confidence (удалено - не используется в новом формате)

    # Форматируем заказчика
    requester_line = ""
    if from_person:
        requester = ", ".join(str(f) for f in from_person[:2])
        if len(from_person) > 2:
            requester += f" <i>+{len(from_person) - 2}</i>"
        requester_line = f"💼 <b>Заказчик:</b> {requester}\n"

    # Форматируем теги
    tags_line = ""
    if tags:
        tags_display = ", ".join(str(t) for t in tags[:3])
        if len(tags) > 3:
            tags_display += f" <i>+{len(tags) - 3}</i>"
        tags_line = f"🏷️ <b>Tags:</b> {tags_display}\n"

    # Форматируем статус
    status_text = {
        "open": "🟢 Активно",
        "done": "✅ Выполнено",
        "dropped": "❌ Отменено",
        "cancelled": "❌ Отменено",
    }.get(str(status).lower(), f"❓ {str(status).title()}")

    # Собираем карточку
    card = (
        f"{status_emoji} <b>{text_escaped}</b>\n"
        f"{requester_line}"
        f"{tags_line}"
        f"{direction_emoji} <b>Исполнитель:</b> {who}\n"
        f"📊 <b>Статус:</b> {status_text}\n"
        f"{urgency_emoji} <b>Срок:</b> {due_formatted}"
    )

    if short_id:
        # Адаптивная длина ID
        display_id = short_id[: limits.id_length] if len(short_id) > limits.id_length else short_id
        card += f"\n🆔 <code>{display_id}</code>"

    return card


def format_review_card(review: dict[str, Any], *, device_type: str | None = None) -> str:
    """
    Форматирует карточку Review элемента для красивого отображения.

    Args:
        review: Данные Review элемента

    Returns:
        Отформатированная HTML строка для Telegram
    """
    # Используем базовую логику commit карточки с передачей device_type
    card = format_commit_card(review, device_type=device_type)

    # Добавляем Review специфичную информацию
    reasons = review.get("reasons") or []
    if reasons:
        reasons_str = ", ".join(str(r) for r in reasons[:2])
        if len(reasons) > 2:
            reasons_str += f" <i>+{len(reasons) - 2}</i>"
        card += f"\n⚠️ <b>Причины ревью:</b> {reasons_str}"

    context = review.get("context")
    if context:
        context_short = _truncate_text(str(context), 50)
        card += f"\n💭 <b>Контекст:</b> <i>{_escape_html(context_short)}</i>"

    return card


def format_people_candidate_card(candidate: dict[str, Any], index: int, total: int) -> str:
    """
    Форматирует карточку кандидата в People Miner.

    Args:
        candidate: Данные кандидата
        index: Текущий индекс (для показа прогресса)
        total: Общее количество

    Returns:
        Отформатированная HTML строка для Telegram
    """
    alias = candidate.get("alias", "Неизвестно")
    freq = candidate.get("freq", 0)
    name_en = candidate.get("name_en", "")

    # Прогресс бар
    progress = f"📊 <b>{index}/{total}</b>"

    # Частота встречаемости с эмодзи
    if freq >= 10:
        freq_emoji = "🔥"
    elif freq >= 5:
        freq_emoji = "⭐"
    elif freq >= 2:
        freq_emoji = "💫"
    else:
        freq_emoji = "📝"

    card = (
        f"👤 <b>Новый кандидат</b>\n\n"
        f"🔤 <b>Имя:</b> <code>{_escape_html(alias)}</code>\n"
        f"{freq_emoji} <b>Встречается:</b> {freq} раз\n"
    )

    if name_en:
        card += f"🌐 <b>Английское имя:</b> <code>{_escape_html(name_en)}</code>\n"

    card += f"\n{progress}"

    return card


def format_tags_stats_card(stats: dict[str, Any]) -> str:
    """
    Форматирует карточку статистики тегирования.

    Args:
        stats: Статистика тегирования

    Returns:
        Отформатированная HTML строка для Telegram
    """
    # Основная статистика
    total_calls = stats.get("total_calls", 0)
    total_tags = stats.get("total_tags_found", 0)
    avg_score = stats.get("avg_score", 0)
    cache_hit_rate = stats.get("cache_hit_rate", 0)

    card = (
        f"📊 <b>Статистика тегирования</b>\n\n"
        f"🎯 <b>Вызовов:</b> {total_calls:,}\n"
        f"🏷️ <b>Тегов найдено:</b> {total_tags:,}\n"
        f"⭐ <b>Средний счет:</b> {avg_score:.2f}\n"
        f"⚡ <b>Кэш hit-rate:</b> {cache_hit_rate:.1%}\n"
    )

    # Топ теги
    top_tags = stats.get("top_tags", {})
    if top_tags:
        card += "\n🏆 <b>Топ теги:</b>\n"
        for i, (tag, count) in enumerate(list(top_tags.items())[:3], 1):
            if "/" in tag:
                category, name = tag.split("/", 1)
                emoji = TAG_CATEGORY_EMOJI.get(category, "🏷️")
                card += f"{i}. {emoji} <code>{name}</code> ({count})\n"
            else:
                card += f"{i}. 🏷️ <code>{tag}</code> ({count})\n"

    # Breakdown по режимам
    mode_stats = stats.get("mode_breakdown", {})
    if mode_stats:
        card += "\n🔧 <b>По режимам:</b>\n"
        for mode, count in mode_stats.items():
            card += f"• <code>{mode}</code>: {count}\n"

    return card


def format_admin_command_response(title: str, data: dict[str, Any], *, success: bool = True) -> str:
    """
    Форматирует ответ на административную команду.

    Args:
        title: Заголовок команды
        data: Данные для отображения
        success: Успешность выполнения

    Returns:
        Отформатированная HTML строка для Telegram
    """
    status_emoji = "✅" if success else "❌"

    card = f"{status_emoji} <b>{title}</b>\n\n"

    for key, value in data.items():
        # Форматируем ключ
        key_formatted = key.replace("_", " ").title()

        # Форматируем значение
        if isinstance(value, dict):
            card += f"📊 <b>{key_formatted}:</b>\n"
            for sub_key, sub_value in list(value.items())[:5]:
                card += f"  • {sub_key}: {sub_value}\n"
        elif isinstance(value, list):
            if len(value) <= 3:
                value_str = ", ".join(str(v) for v in value)
            else:
                value_str = ", ".join(str(v) for v in value[:3]) + f" <i>+{len(value)-3}</i>"
            card += f"📋 <b>{key_formatted}:</b> {value_str}\n"
        elif isinstance(value, int | float):
            if key.endswith("_rate") or key.endswith("_percent"):
                card += f"📈 <b>{key_formatted}:</b> {value:.1%}\n"
            elif key.endswith("_count") or key.endswith("_total"):
                card += f"🔢 <b>{key_formatted}:</b> {value:,}\n"
            else:
                card += f"📊 <b>{key_formatted}:</b> {value}\n"
        else:
            card += f"ℹ️ <b>{key_formatted}:</b> {value}\n"

    return card


def format_error_card(error_title: str, error_details: str, *, show_details: bool = True) -> str:
    """
    Форматирует карточку ошибки.

    Args:
        error_title: Краткое описание ошибки
        error_details: Детали ошибки
        show_details: Показывать ли детали

    Returns:
        Отформатированная HTML строка для Telegram
    """
    card = f"❌ <b>{error_title}</b>\n\n"

    if show_details and error_details:
        details_short = _truncate_text(str(error_details), 200)
        card += f"📝 <b>Детали:</b>\n<code>{_escape_html(details_short)}</code>\n\n"

    card += "💡 <b>Что делать:</b>\n"
    card += "• Попробуйте еще раз через несколько секунд\n"
    card += "• Проверьте формат данных\n"
    card += "• Обратитесь к администратору если проблема повторяется"

    return card


def format_success_card(title: str, details: dict[str, Any] | None = None) -> str:
    """
    Форматирует карточку успешного выполнения операции.

    Args:
        title: Заголовок успешной операции
        details: Дополнительные детали

    Returns:
        Отформатированная HTML строка для Telegram
    """
    card = f"✅ <b>{title}</b>\n\n"

    if details:
        for key, value in details.items():
            key_formatted = key.replace("_", " ").title()

            if key.endswith("_id") and isinstance(value, str) and len(value) > 10:
                # Сокращаем длинные ID
                short_value = f"{value[:8]}..."
                card += f"🆔 <b>{key_formatted}:</b> <code>{short_value}</code>\n"
            elif isinstance(value, int | float) and value > 0:
                card += f"📊 <b>{key_formatted}:</b> {value}\n"
            elif isinstance(value, str) and value:
                card += f"ℹ️ <b>{key_formatted}:</b> {_escape_html(str(value))}\n"

    return card


def format_progress_card(current: int, total: int, operation: str) -> str:
    """
    Форматирует карточку прогресса операции.

    Args:
        current: Текущий элемент
        total: Общее количество
        operation: Название операции

    Returns:
        Отформатированная HTML строка для Telegram
    """
    percent = (current / total * 100) if total > 0 else 0

    # Прогресс бар из эмодзи
    filled = int(percent / 10)
    progress_bar = "🟩" * filled + "⬜" * (10 - filled)

    card = (
        f"⏳ <b>{operation}</b>\n\n"
        f"📊 <b>Прогресс:</b> {current}/{total} ({percent:.0f}%)\n"
        f"{progress_bar}\n\n"
        f"⏱️ <i>Обработка в процессе...</i>"
    )

    return card


def format_adaptive_demo(sample_data: dict[str, Any]) -> dict[str, str]:
    """
    Демонстрирует адаптивное форматирование для разных устройств.

    Args:
        sample_data: Пример данных для форматирования

    Returns:
        Словарь с форматированными версиями для каждого устройства
    """
    result = {}

    for device in ["mobile", "tablet", "desktop"]:
        limits = DEVICE_LIMITS[device]
        formatted = format_meeting_card(sample_data, device_type=device)

        result[device] = (
            f"📱 <b>{device.title()} ({limits.title}x{limits.description}):</b>\n{formatted}"
        )

    return result


# Константы для экспорта
__all__ = [
    "format_meeting_card",
    "format_commit_card",
    "format_review_card",
    "format_people_candidate_card",
    "format_tags_stats_card",
    "format_admin_command_response",
    "format_error_card",
    "format_success_card",
    "format_progress_card",
    "format_adaptive_demo",
    "DEVICE_LIMITS",
    "_get_adaptive_limits",
]


# CLI для демонстрации адаптивного форматирования
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        # Пример данных для демонстрации
        sample_meeting = {
            "title": "Финансовое планирование и бюджетирование на Q4 2025 с обсуждением IFRS стандартов",
            "date": "2025-09-23",
            "attendees": [
                "Valya Dobrynin",
                "Nodari Kezua",
                "Sergey Lompa",
                "Vlad Sklyanov",
                "Serezha Ustinenko",
                "Ivan Petrov",
            ],
            "tags": [
                "Finance/IFRS",
                "Finance/Budget",
                "Business/Market",
                "Topic/Planning",
                "People/Valya Dobrynin",
            ],
            "url": "https://notion.so/sample-meeting-12345",
        }

        sample_commit = {
            "text": "Подготовить детальный отчет по продажам и маркетинговым активностям за Q3 с анализом конверсии",
            "status": "open",
            "direction": "theirs",
            "assignees": ["Daniil Petrov", "Maria Sidorova"],
            "due_iso": "2025-10-15",
            "confidence": 0.85,
            "short_id": "abc123def456ghi789",
        }

        print("🎨 Демонстрация адаптивного форматирования Meet-Commit\n")

        print("📅 ВСТРЕЧА:")
        demo_results = format_adaptive_demo(sample_meeting)
        for _device, formatted in demo_results.items():
            print(f"\n{formatted}")

        print("\n" + "=" * 60 + "\n")

        print("📝 КОММИТ:")
        for device in ["mobile", "tablet", "desktop"]:
            limits = DEVICE_LIMITS[device]
            formatted = format_commit_card(sample_commit, device_type=device)
            print(f"\n📱 <b>{device.title()} ({limits.description} chars):</b>")
            print(formatted)

        print("\n" + "=" * 60)
        print("🎯 Адаптивные лимиты:")
        for device, limits in DEVICE_LIMITS.items():
            print(
                f"• {device.title()}: title={limits.title}, desc={limits.description}, attendees={limits.attendees}, tags={limits.tags}"
            )
    else:
        print("Usage: python -m app.bot.formatters demo")


def format_agenda_card(bundle, device_type: str = "mobile") -> str:
    """
    Форматирование повестки в виде карточки для Telegram.

    Args:
        bundle: AgendaBundle с данными повестки
        device_type: Тип устройства для адаптивного форматирования

    Returns:
        Отформатированная карточка повестки в HTML
    """
    limits = DEVICE_LIMITS[device_type]

    # Заголовок повестки
    context_emoji = {"Meeting": "🏢", "Person": "👤", "Tag": "🏷️"}.get(bundle.context_type, "📋")
    title = f"{context_emoji} Повестка — {bundle.context_type}"

    if bundle.context_type == "Person":
        person_name = bundle.context_key.replace("People/", "")
        title = f"👤 Повестка — {person_name}"
    elif bundle.context_type == "Tag":
        title = f"🏷️ Повестка — {bundle.context_key}"
    elif bundle.context_type == "Meeting":
        title = "🏢 Повестка — Встреча"

    title = _truncate_text(title, limits.title)

    # Статистика
    stats = []
    if bundle.debts_mine:
        stats.append(f"📋 Заказчик: {len(bundle.debts_mine)}")
    if bundle.debts_theirs:
        stats.append(f"📤 Исполнитель: {len(bundle.debts_theirs)}")
    if bundle.review_open:
        stats.append(f"❓ Вопросы: {len(bundle.review_open)}")
    if bundle.recent_done:
        stats.append(f"✅ Выполнено: {len(bundle.recent_done)}")

    stats_line = " | ".join(stats) if stats else "📋 Пусто"

    # Убираем неинформативные строки с тегами и участниками
    tags_line = ""
    people_line = ""

    # Полное содержимое (без ограничений)
    content_preview = ""
    if bundle.summary_md:
        # Убираем HTML теги для превью
        preview_text = bundle.summary_md.replace("<b>", "").replace("</b>", "")
        preview_text = preview_text.replace("<i>", "").replace("</i>", "")

        # Показываем все строки без ограничений
        content_preview = f"\n\n{preview_text}"

    # Дата генерации
    from datetime import datetime

    now = datetime.now(UTC).strftime("%d.%m %H:%M UTC")

    # Собираем карточку
    card = (
        f"<b>{title}</b>\n"
        f"📊 {stats_line}"
        f"{tags_line}"
        f"{people_line}"
        f"{content_preview}\n\n"
        f"🕒 Сгенерировано: {now}"
    )

    return card
