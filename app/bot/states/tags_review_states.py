"""FSM состояния для интерактивного ревью тегов."""

from aiogram.fsm.state import State, StatesGroup


class TagsReviewStates(StatesGroup):
    """Состояния для интерактивного ревью тегов."""

    reviewing = State()  # Идет ревью тегов
    waiting_custom_tag = State()  # Ждем ввод кастомного тега
