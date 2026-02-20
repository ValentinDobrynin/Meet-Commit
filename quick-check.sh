#!/bin/bash

# Meet-Commit Quick Check
# Быстрая проверка перед коммитом (~30 сек)

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Счётчики
PASS=0
FAIL=0
SKIP=0

step() {
    echo ""
    echo -e "${BLUE}▶ $1${NC}"
}

ok() {
    echo -e "  ${GREEN}✅ $1${NC}"
    PASS=$((PASS+1))
}

warn() {
    echo -e "  ${YELLOW}⚠️  $1${NC}"
    SKIP=$((SKIP+1))
}

fail() {
    echo -e "  ${RED}❌ $1${NC}"
    FAIL=$((FAIL+1))
}

echo ""
echo -e "${BLUE}⚡ Meet-Commit Quick Check${NC}"
echo "================================"

# Активируем виртуальное окружение
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    warn "venv не найден, используем системный Python"
fi

# ── 1. СИНТАКСИС ─────────────────────────────────────────────
step "1/5 Синтаксис Python"
if python3 -c "
import ast, os, sys
errors = []
for root, dirs, files in os.walk('app'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                ast.parse(open(path).read())
            except SyntaxError as e:
                errors.append(f'{path}:{e.lineno}: {e.msg}')
if errors:
    for e in errors:
        print(f'  ERROR: {e}')
    sys.exit(1)
"; then
    ok "Синтаксис всех .py файлов корректен"
else
    fail "SyntaxError в коде — нужно исправить до коммита!"
    exit 1
fi

# ── 2. RUFF LINT ─────────────────────────────────────────────
step "2/5 Ruff lint"
if command -v ruff >/dev/null 2>&1; then
    if ruff check . --quiet 2>&1; then
        ok "Ruff: ошибок не найдено"
    else
        fail "Ruff нашёл ошибки. Запустите: ruff check . --fix"
        # Показываем ошибки но не прерываем (warn mode)
        ruff check . 2>&1 | head -20 || true
        exit 1
    fi
else
    warn "ruff не установлен: pip install ruff"
fi

# ── 3. RUFF FORMAT ───────────────────────────────────────────
step "3/5 Ruff format (проверка стиля)"
if command -v ruff >/dev/null 2>&1; then
    if ruff format . --check --quiet 2>&1; then
        ok "Форматирование соответствует стандарту"
    else
        warn "Есть файлы не в стиле. Запустите: ruff format ."
        # Не прерываем — это предупреждение
    fi
else
    warn "ruff не установлен: pip install ruff"
fi

# ── 4. ПРОВЕРКА ТИПОВ ────────────────────────────────────────
step "4/5 Mypy типы (app/bot/)"
if command -v mypy >/dev/null 2>&1; then
    # Проверяем только bot/ — самый критичный модуль, быстро
    if mypy app/bot/ --ignore-missing-imports --no-error-summary --quiet 2>&1; then
        ok "Типы в app/bot/ корректны"
    else
        warn "Mypy нашёл замечания (не блокирует коммит)"
    fi
else
    warn "mypy не установлен: pip install mypy"
fi

# ── 5. БЫСТРЫЕ ТЕСТЫ ─────────────────────────────────────────
step "5/5 Быстрые тесты (без медленных)"
TEST_ENV="TELEGRAM_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789 \
OPENAI_API_KEY=test NOTION_TOKEN=test NOTION_DB_MEETINGS_ID=test"

if command -v pytest >/dev/null 2>&1; then
    if eval "$TEST_ENV pytest tests/ -x -q \
        --ignore=tests/test_end_to_end_workflows.py \
        --ignore=tests/test_performance_benchmarks.py \
        --ignore=tests/test_system_resilience.py \
        -m 'not slow' 2>&1"; then
        ok "Тесты прошли"
    else
        fail "Тесты упали — нужно исправить до коммита!"
        exit 1
    fi
else
    warn "pytest не установлен"
fi

# ── ИТОГ ─────────────────────────────────────────────────────
echo ""
echo "================================"
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✅ Быстрая проверка пройдена!${NC}"
    echo -e "   Pass: ${GREEN}${PASS}${NC}  Warn: ${YELLOW}${SKIP}${NC}  Fail: ${RED}${FAIL}${NC}"
    echo ""
    echo -e "💡 Для полной проверки: ${BLUE}./ci.sh${NC}"
else
    echo -e "${RED}❌ Проверка не пройдена (${FAIL} ошибок)${NC}"
    echo -e "   Pass: ${GREEN}${PASS}${NC}  Warn: ${YELLOW}${SKIP}${NC}  Fail: ${RED}${FAIL}${NC}"
    exit 1
fi
