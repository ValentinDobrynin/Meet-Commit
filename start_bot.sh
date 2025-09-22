#!/bin/bash

# Скрипт для запуска Meet-Commit бота
# Предотвращает множественные запуски и конфликты

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Meet-Commit Bot Manager${NC}"
echo "================================"

# Проверяем, активирована ли виртуальная среда
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo -e "${YELLOW}⚠️  Virtual environment not activated. Activating...${NC}"
    source venv/bin/activate
fi

# Проверяем наличие .env файла
if [[ ! -f ".env" ]]; then
    echo -e "${RED}❌ .env file not found!${NC}"
    echo "Please create .env file with required variables:"
    echo "  TELEGRAM_TOKEN=your_bot_token"
    echo "  OPENAI_API_KEY=your_openai_key"
    echo "  NOTION_TOKEN=your_notion_token"
    echo "  NOTION_DB_MEETINGS_ID=your_database_id"
    exit 1
fi

# Проверяем, не запущен ли уже бот
if pgrep -f "app.bot.main" > /dev/null; then
    echo -e "${RED}❌ Bot is already running!${NC}"
    echo "Running processes:"
    pgrep -f "app.bot.main" | xargs ps -p
    echo ""
    echo "To stop existing bot, run:"
    echo "  ./stop_bot.sh"
    echo "  or"
    echo "  pkill -f 'app.bot.main'"
    exit 1
fi

# Проверяем lock-файл
LOCK_FILE="/tmp/meet_commit_bot.lock"
if [[ -f "$LOCK_FILE" ]]; then
    echo -e "${YELLOW}⚠️  Lock file exists. Checking if process is still running...${NC}"
    if pgrep -f "app.bot.main" > /dev/null; then
        echo -e "${RED}❌ Bot process is still running!${NC}"
        exit 1
    else
        echo -e "${YELLOW}🧹 Cleaning up stale lock file...${NC}"
        rm -f "$LOCK_FILE"
    fi
fi

# Устанавливаем PYTHONPATH
export PYTHONPATH="/Users/vdobrynin/Documents/Meet-Commit:$PYTHONPATH"

# Создаем директорию для логов
mkdir -p logs

echo -e "${GREEN}✅ Starting bot with logging...${NC}"
echo "Logs will be saved to:"
echo "  • logs/bot.log (all logs)"
echo "  • logs/bot_errors.log (errors only)"
echo ""
echo "To view logs in real-time:"
echo "  tail -f logs/bot.log"
echo ""
echo "Press Ctrl+C to stop the bot"
echo "================================"

# Запускаем бота
python -m app.bot.main
