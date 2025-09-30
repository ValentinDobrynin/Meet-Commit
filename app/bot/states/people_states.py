"""FSM состояния для работы с людьми и кандидатами."""

from aiogram.fsm.state import State, StatesGroup


class PeopleStates(StatesGroup):
    """Состояния для people miner."""

    idle = State()  # Бездействие
    reviewing = State()  # Идет показ кандидатов
    waiting_assign_en = State()  # Ждем ввод канонического EN-имени (v1)
    batch_processing = State()  # Массовая обработка кандидатов

    # People Miner v2 состояния
    v2_reviewing = State()  # Просмотр кандидатов v2
    v2_waiting_custom_name = State()  # Ждем ввод кастомного имени v2
