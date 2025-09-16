#!/bin/bash

# Meet-Commit Quick Check
# Быстрая проверка перед коммитом (без полного CI)

set -e

echo "⚡ Meet-Commit Quick Check"
echo "========================="

# Активируем виртуальное окружение
source venv/bin/activate

echo "🧹 Линтинг..."
make lint

echo "🔍 Проверка типов..."
make typecheck

echo "🧪 Тесты..."
make test

echo ""
echo "✅ Быстрая проверка пройдена!"
echo "💡 Для полной проверки запустите: ./ci.sh"
