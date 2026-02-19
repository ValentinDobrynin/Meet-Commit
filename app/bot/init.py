from aiogram import Bot, Dispatcher


def build_bot(token: str, storage=None) -> tuple[Bot, Dispatcher]:
    # Намеренно НЕ устанавливаем дефолтный parse_mode.
    # Каждый msg.answer() должен явно указывать parse_mode="HTML" если нужно.
    # Это предотвращает случайную ошибку когда AI-текст содержит <теги>.
    bot = Bot(token=token)
    dp = Dispatcher(storage=storage)
    return bot, dp
