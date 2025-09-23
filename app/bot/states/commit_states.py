"""FSM состояния для создания прямых коммитов."""

from aiogram.fsm.state import State, StatesGroup


class DirectCommitStates(StatesGroup):
    """Состояния для создания прямого коммита без транскрипта встречи."""

    waiting_text = State()  # Ожидание текста коммита
    waiting_from = State()  # Ожидание отправителя
    waiting_to = State()  # Ожидание исполнителя
    waiting_due = State()  # Ожидание дедлайна
    confirm = State()  # Подтверждение создания
