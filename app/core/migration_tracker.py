"""
Система отслеживания прогресса миграции в облако.

Читает и обновляет статус миграции из markdown документа,
обеспечивая персистентный контекст между сессиями.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

# Путь к документу плана миграции
MIGRATION_PLAN_PATH = (
    Path(__file__).resolve().parent.parent.parent / "docs" / "cloud_migration_render_plan.md"
)


class MigrationStatus:
    """Статус миграции в облако."""

    def __init__(self):
        self.status = "NOT_STARTED"
        self.last_updated = ""
        self.current_phase = "PLANNING"
        self.completion = 0
        self.next_action = ""
        self.tasks = {}
        self.session_context = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "last_updated": self.last_updated,
            "current_phase": self.current_phase,
            "completion": self.completion,
            "next_action": self.next_action,
            "tasks": self.tasks,
            "session_context": self.session_context,
        }


def read_migration_status() -> MigrationStatus:
    """
    Читает текущий статус миграции из документа.

    Returns:
        Объект MigrationStatus с текущим состоянием
    """
    status = MigrationStatus()

    if not MIGRATION_PLAN_PATH.exists():
        return status

    try:
        with open(MIGRATION_PLAN_PATH, encoding="utf-8") as f:
            content = f.read()

        # Извлекаем метаданные из HTML комментариев
        metadata_patterns = {
            "status": r"<!-- MIGRATION_STATUS: (\w+) -->",
            "last_updated": r"<!-- LAST_UPDATED: ([\d-]+) -->",
            "current_phase": r"<!-- CURRENT_PHASE: (\w+) -->",
            "completion": r"<!-- COMPLETION: (\d+)% -->",
            "next_action": r"<!-- NEXT_ACTION: (\w+) -->",
        }

        for key, pattern in metadata_patterns.items():
            match = re.search(pattern, content)
            if match:
                value = match.group(1)
                if key == "completion":
                    setattr(status, key, int(value))
                else:
                    setattr(status, key, value)

        # Извлекаем задачи из канбан секции
        status.tasks = _parse_kanban_tasks(content)

        # Извлекаем контекст сессии
        status.session_context = _parse_session_context(content)

        return status

    except Exception as e:
        print(f"Error reading migration status: {e}")
        return status


def _parse_kanban_tasks(content: str) -> dict[str, dict[str, Any]]:
    """Парсит задачи из канбан секции."""
    tasks: dict[str, dict[str, Any]] = {}

    # Ищем секцию канбан
    kanban_start = content.find("<!-- KANBAN_STATUS_START -->")
    kanban_end = content.find("<!-- KANBAN_STATUS_END -->")

    if kanban_start == -1 or kanban_end == -1:
        return tasks

    kanban_section = content[kanban_start:kanban_end]

    # Парсим задачи
    task_pattern = r"<!-- TASK_STATUS: (\w+) -->\s*- \[([ x])\] \*\*(\w+)\*\* \(([^)]+)\) `([^`]+)`"

    for match in re.finditer(task_pattern, kanban_section):
        task_status = match.group(1)
        is_completed = match.group(2) == "x"
        task_id = match.group(3)
        duration = match.group(4)
        tags = match.group(5)

        tasks[task_id] = {
            "status": task_status,
            "completed": is_completed,
            "duration": duration,
            "tags": tags,
            "priority": _extract_priority(tags),
            "phase": _extract_phase(tags),
        }

    return tasks


def _parse_session_context(content: str) -> dict[str, Any]:
    """Парсит контекст сессии."""
    context: dict[str, Any] = {}

    # Ищем секцию контекста
    context_start = content.find("<!-- SESSION_CONTEXT_START -->")
    context_end = content.find("<!-- SESSION_CONTEXT_END -->")

    if context_start == -1 or context_end == -1:
        return context

    context_section = content[context_start:context_end]

    # Извлекаем ключевую информацию
    patterns = {
        "last_activity": r"\*\*Последняя активность:\*\* (.+)",
        "current_focus": r"\*\*Текущий фокус:\*\* (.+)",
        "next_steps": r"\*\*Следующие шаги:\*\*\s*\n((?:\d+\..+\n?)+)",
        "key_decisions": r"\*\*Ключевые решения:\*\*\s*\n((?:- .+\n?)+)",
        "critical_files": r"\*\*Критические файлы для изменения:\*\*\s*\n((?:- .+\n?)+)",
        "blocked_tasks": r"\*\*Заблокированные задачи:\*\*\s*\n((?:- .+\n?)+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, context_section)
        if match:
            context[key] = match.group(1).strip()

    return context


def _extract_priority(tags: str) -> str:
    """Извлекает приоритет из тегов."""
    if "PRIORITY:HIGH" in tags:
        return "HIGH"
    elif "PRIORITY:MEDIUM" in tags:
        return "MEDIUM"
    elif "PRIORITY:LOW" in tags:
        return "LOW"
    return "MEDIUM"


def _extract_phase(tags: str) -> int:
    """Извлекает фазу из тегов."""
    phase_match = re.search(r"PHASE:(\d+)", tags)
    return int(phase_match.group(1)) if phase_match else 1


def update_migration_status(
    status: str | None = None,
    current_phase: str | None = None,
    completion: int | None = None,
    next_action: str | None = None,
) -> bool:
    """
    Обновляет статус миграции в документе.

    Args:
        status: Новый статус миграции
        current_phase: Текущая фаза
        completion: Процент завершения (0-100)
        next_action: Следующее действие

    Returns:
        True если обновление успешно
    """
    if not MIGRATION_PLAN_PATH.exists():
        return False

    try:
        with open(MIGRATION_PLAN_PATH, encoding="utf-8") as f:
            content = f.read()

        # Обновляем метаданные
        current_date = datetime.now().strftime("%Y-%m-%d")

        if status:
            content = re.sub(
                r"<!-- MIGRATION_STATUS: \w+ -->", f"<!-- MIGRATION_STATUS: {status} -->", content
            )

        content = re.sub(
            r"<!-- LAST_UPDATED: [\d-]+ -->", f"<!-- LAST_UPDATED: {current_date} -->", content
        )

        if current_phase:
            content = re.sub(
                r"<!-- CURRENT_PHASE: \w+ -->", f"<!-- CURRENT_PHASE: {current_phase} -->", content
            )

        if completion is not None:
            content = re.sub(
                r"<!-- COMPLETION: \d+% -->", f"<!-- COMPLETION: {completion}% -->", content
            )

        if next_action:
            content = re.sub(
                r"<!-- NEXT_ACTION: \w+ -->", f"<!-- NEXT_ACTION: {next_action} -->", content
            )

        # Сохраняем обновленный документ
        with open(MIGRATION_PLAN_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        return True

    except Exception as e:
        print(f"Error updating migration status: {e}")
        return False


def update_task_status(task_id: str, status: str, progress: int | None = None) -> bool:
    """
    Обновляет статус конкретной задачи.

    Args:
        task_id: ID задачи
        status: Новый статус (todo, in_progress, done, blocked)
        progress: Процент выполнения задачи

    Returns:
        True если обновление успешно
    """
    if not MIGRATION_PLAN_PATH.exists():
        return False

    try:
        with open(MIGRATION_PLAN_PATH, encoding="utf-8") as f:
            content = f.read()

        # Находим задачу и обновляем статус
        task_pattern = f"(<!-- TASK_STATUS: \\w+ -->\\s*- \\[[ x]\\] \\*\\*{task_id}\\*\\*[^\\n]*)"

        def replace_task(match):
            task_line = match.group(1)

            # Обновляем статус в комментарии
            updated_line = re.sub(
                r"<!-- TASK_STATUS: \w+ -->", f"<!-- TASK_STATUS: {status} -->", task_line
            )

            # Обновляем чекбокс
            if status == "done":
                updated_line = re.sub(r"- \[[ x]\]", "- [x]", updated_line)
            else:
                updated_line = re.sub(r"- \[[ x]\]", "- [ ]", updated_line)

            return updated_line

        content = re.sub(task_pattern, replace_task, content)

        # Если указан прогресс, обновляем его в описании задачи
        if progress is not None:
            progress_pattern = f"(\\*\\*{task_id}\\*\\*.*?\\*\\*Progress:\\*\\* )\\d+%"
            content = re.sub(progress_pattern, f"\\g<1>{progress}%", content)

        # Сохраняем
        with open(MIGRATION_PLAN_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        return True

    except Exception as e:
        print(f"Error updating task status: {e}")
        return False


def get_next_actions() -> list[dict[str, Any]]:
    """
    Возвращает список следующих действий на основе текущего статуса.

    Returns:
        Список задач готовых к выполнению
    """
    status = read_migration_status()
    next_actions = []

    # Находим задачи со статусом 'todo' и высоким приоритетом
    for task_id, task_data in status.tasks.items():
        if (
            task_data["status"] == "todo"
            and task_data["priority"] == "HIGH"
            and not task_data["completed"]
        ):
            next_actions.append(
                {
                    "task_id": task_id,
                    "duration": task_data["duration"],
                    "phase": task_data["phase"],
                    "priority": task_data["priority"],
                }
            )

    # Сортируем по фазе и приоритету
    next_actions.sort(key=lambda x: (x["phase"], x["priority"] != "HIGH"))

    return next_actions


def get_migration_summary() -> str:
    """
    Возвращает краткое резюме статуса миграции.

    Returns:
        Строка с кратким статусом
    """
    status = read_migration_status()

    # Подсчитываем статистику задач
    total_tasks = len(status.tasks)
    completed_tasks = sum(1 for task in status.tasks.values() if task["completed"])
    in_progress_tasks = sum(1 for task in status.tasks.values() if task["status"] == "in_progress")
    blocked_tasks = sum(1 for task in status.tasks.values() if task["status"] == "blocked")

    completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

    summary = f"""
🌐 Migration Status: {status.status}
📊 Progress: {completion_rate:.0f}% ({completed_tasks}/{total_tasks} tasks)
🎯 Current Phase: {status.current_phase}
⏭️ Next Action: {status.next_action}
📅 Last Updated: {status.last_updated}

📋 Tasks Breakdown:
✅ Completed: {completed_tasks}
🟨 In Progress: {in_progress_tasks}
🟥 Blocked: {blocked_tasks}
🟦 Todo: {total_tasks - completed_tasks - in_progress_tasks - blocked_tasks}
"""

    return summary.strip()


def update_session_context(
    last_activity: str,
    current_focus: str,
    next_steps: list[str] | None = None,
    decisions: list[str] | None = None,
    critical_files: list[str] | None = None,
    blocked_tasks: list[str] | None = None,
) -> bool:
    """
    Обновляет контекст сессии в документе.

    Args:
        last_activity: Описание последней активности
        current_focus: Текущий фокус работы
        next_steps: Список следующих шагов
        decisions: Ключевые принятые решения
        critical_files: Критические файлы для изменения
        blocked_tasks: Заблокированные задачи

    Returns:
        True если обновление успешно
    """
    if not MIGRATION_PLAN_PATH.exists():
        return False

    try:
        with open(MIGRATION_PLAN_PATH, encoding="utf-8") as f:
            content = f.read()

        # Находим секцию контекста
        context_start = content.find("<!-- SESSION_CONTEXT_START -->")
        context_end = content.find("<!-- SESSION_CONTEXT_END -->")

        if context_start == -1 or context_end == -1:
            return False

        # Формируем новый контекст
        new_context = f"""<!-- SESSION_CONTEXT_START -->
**Последняя активность:** {last_activity}
**Текущий фокус:** {current_focus}
"""

        if next_steps:
            new_context += "**Следующие шаги:** \n"
            for i, step in enumerate(next_steps, 1):
                new_context += f"{i}. {step}\n"
            new_context += "\n"

        if decisions:
            new_context += "**Ключевые решения:**\n"
            for decision in decisions:
                new_context += f"- ✅ {decision}\n"
            new_context += "\n"

        if critical_files:
            new_context += "**Критические файлы для изменения:**\n"
            for file in critical_files:
                new_context += f"- `{file}` - {_get_file_description(file)}\n"
            new_context += "\n"

        if blocked_tasks:
            new_context += "**Заблокированные задачи:**\n"
            for task in blocked_tasks:
                new_context += f"- {task}\n"

        new_context += "<!-- SESSION_CONTEXT_END -->"

        # Заменяем секцию контекста
        updated_content = (
            content[:context_start]
            + new_context
            + content[context_end + len("<!-- SESSION_CONTEXT_END -->") :]
        )

        # Сохраняем
        with open(MIGRATION_PLAN_PATH, "w", encoding="utf-8") as f:
            f.write(updated_content)

        return True

    except Exception as e:
        print(f"Error updating session context: {e}")
        return False


def _get_file_description(file_path: str) -> str:
    """Возвращает описание файла для контекста."""
    descriptions = {
        "app/bot/main.py": "облачный режим запуска",
        "app/core/people_store.py": "асинхронное хранилище",
        "app/core/people_miner2.py": "облачные операции",
        "requirements.txt": "добавить Redis",
        "render.yaml": "конфигурация деплоя",
        "app/core/storage/": "абстракция хранилища",
        "app/gateways/notion_people_catalog.py": "People Catalog API",
        "app/core/cloud_sync.py": "синхронизация данных",
    }

    return descriptions.get(file_path, "изменения для облака")


def get_current_context() -> str:
    """
    Возвращает текущий контекст для восстановления сессии.

    Returns:
        Строка с контекстом текущей работы
    """
    status = read_migration_status()

    context_text = f"""
🎯 КОНТЕКСТ МИГРАЦИИ MEET-COMMIT В ОБЛАКО

📊 Текущий статус: {status.status}
🎯 Фаза: {status.current_phase} 
📈 Прогресс: {status.completion}%
⏭️ Следующее действие: {status.next_action}
📅 Обновлено: {status.last_updated}

🔍 Последняя активность: {status.session_context.get('last_activity', 'Не указана')}
🎯 Текущий фокус: {status.session_context.get('current_focus', 'Не указан')}

📋 Готовые к выполнению задачи:
"""

    next_actions = get_next_actions()
    for i, action in enumerate(next_actions[:3], 1):  # Показываем топ-3
        context_text += (
            f"{i}. {action['task_id']} ({action['duration']}) - Фаза {action['phase']}\n"
        )

    if len(next_actions) > 3:
        context_text += f"... и еще {len(next_actions) - 3} задач\n"

    context_text += f"""
🚨 Заблокированные задачи: {sum(1 for task in status.tasks.values() if task['status'] == 'blocked')}
🟨 В работе: {sum(1 for task in status.tasks.values() if task['status'] == 'in_progress')}
✅ Завершено: {sum(1 for task in status.tasks.values() if task['completed'])}

💡 Используйте функции migration_tracker для обновления прогресса:
- read_migration_status() - получить текущий статус
- update_task_status(task_id, status) - обновить задачу
- update_session_context() - обновить контекст работы
"""

    return context_text.strip()


# Convenience функции для быстрого использования
def mark_task_completed(task_id: str) -> bool:
    """Отмечает задачу как выполненную."""
    return update_task_status(task_id, "done")


def mark_task_in_progress(task_id: str, progress: int = 0) -> bool:
    """Отмечает задачу как выполняющуюся."""
    return update_task_status(task_id, "in_progress", progress)


def mark_task_blocked(task_id: str) -> bool:
    """Отмечает задачу как заблокированную."""
    return update_task_status(task_id, "blocked")


def get_phase_summary(phase: int) -> dict[str, Any]:
    """
    Возвращает сводку по конкретной фазе.

    Args:
        phase: Номер фазы (1-8)

    Returns:
        Словарь с информацией о фазе
    """
    status = read_migration_status()

    phase_tasks = [task for task_id, task in status.tasks.items() if task["phase"] == phase]

    completed = sum(1 for task in phase_tasks if task["completed"])
    total = len(phase_tasks)

    return {
        "phase": phase,
        "total_tasks": total,
        "completed_tasks": completed,
        "completion_rate": (completed / total * 100) if total > 0 else 0,
        "tasks": phase_tasks,
    }
