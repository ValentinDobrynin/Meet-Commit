#!/bin/bash

# Скрипт для остановки Meet-Commit бота

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🛑 Meet-Commit Bot Stopper${NC}"
echo "================================"

# Ищем запущенные процессы бота
BOT_PIDS=$(pgrep -f "app.bot.main" || true)

if [[ -z "$BOT_PIDS" ]]; then
    echo -e "${YELLOW}⚠️  No bot processes found running${NC}"
else
    echo -e "${YELLOW}🔍 Found bot processes:${NC}"
    echo "$BOT_PIDS" | xargs ps -p
    echo ""
    
    echo -e "${GREEN}🛑 Stopping bot processes...${NC}"
    echo "$BOT_PIDS" | xargs kill
    
    # Ждем завершения процессов
    sleep 2
    
    # Проверяем, завершились ли процессы
    REMAINING_PIDS=$(pgrep -f "app.bot.main" || true)
    if [[ -n "$REMAINING_PIDS" ]]; then
        echo -e "${RED}⚠️  Some processes didn't stop gracefully. Force killing...${NC}"
        echo "$REMAINING_PIDS" | xargs kill -9
        sleep 1
    fi
    
    echo -e "${GREEN}✅ Bot processes stopped${NC}"
fi

# Очищаем lock-файл
LOCK_FILE="/tmp/meet_commit_bot.lock"
if [[ -f "$LOCK_FILE" ]]; then
    echo -e "${GREEN}🧹 Cleaning up lock file...${NC}"
    rm -f "$LOCK_FILE"
fi

echo -e "${GREEN}✅ Bot cleanup completed${NC}"
