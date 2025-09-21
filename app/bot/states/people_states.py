"""FSM состояния для работы с людьми и кандидатами."""

from aiogram.fsm.state import State, StatesGroup


class PeopleStates(StatesGroup):
    """Состояния для people miner."""

    idle = State()  # Бездействие
    reviewing = State()  # Идет показ кандидатов
    waiting_assign_en = State()  # Ждем ввод канонического EN-имени
    batch_processing = State()  # Массовая обработка кандидатов
