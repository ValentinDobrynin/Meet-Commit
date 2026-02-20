#!/bin/bash

# Meet-Commit CI Pipeline
# Полная проверка качества кода (~2-3 мин)

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Счётчики
PASS=0
FAIL=0
SKIP=0
START_TIME=$(date +%s)

step() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}▶ $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
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
echo -e "${BLUE}🚀 Meet-Commit CI Pipeline${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Проверяем, что мы в правильной директории
if [ ! -f "requirements.txt" ] || [ ! -d "app" ]; then
    echo -e "${RED}❌ Ошибка: Запустите из корневой директории проекта${NC}"
    exit 1
fi

# Активируем виртуальное окружение
if [ -d "venv" ]; then
    echo "📦 Активация venv..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "📦 Активация .venv..."
    source .venv/bin/activate
else
    warn "venv не найден, используем системный Python"
fi

# Проверяем установку зависимостей
echo "🔍 Проверка зависимостей..."
if ! python -c "import pytest, mypy, bandit, deptry, ruff" 2>/dev/null; then
    echo "📥 Установка зависимостей..."
    pip install -r requirements.txt -q
fi

# ── 1. СИНТАКСИС ─────────────────────────────────────────────
step "1/9 Синтаксис Python"
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
    for e in errors: print(f'  ERROR: {e}')
    sys.exit(1)
print(f'  Проверено файлов: {sum(1 for r,d,fs in os.walk(\"app\") for f in fs if f.endswith(\".py\"))}')
"; then
    ok "Синтаксис всех .py файлов корректен"
else
    fail "SyntaxError — необходимо исправить!"
    exit 1
fi

# ── 2. RUFF LINT ─────────────────────────────────────────────
step "2/9 Ruff lint (E, F, I, B, UP)"
if ruff check . 2>&1; then
    ok "Ruff lint: ошибок не найдено"
else
    fail "Ruff нашёл ошибки. Запустите: ruff check . --fix"
    FAIL=$((FAIL+1))
fi

# ── 3. RUFF FORMAT ───────────────────────────────────────────
step "3/9 Ruff format"
if ruff format . --check 2>&1; then
    ok "Форматирование соответствует стандарту"
else
    warn "Есть неотформатированные файлы. Запустите: ruff format ."
    # Применяем автоматически в CI
    ruff format . 2>&1
    warn "Форматирование применено автоматически"
fi

# ── 4. ПРОВЕРКА ТИПОВ ────────────────────────────────────────
step "4/9 Mypy проверка типов"
if mypy app/ --ignore-missing-imports 2>&1; then
    ok "Типы корректны"
else
    warn "Mypy нашёл замечания (не блокирует CI)"
fi

# ── 5. PARSE_MODE AUDIT ──────────────────────────────────────
step "5/9 Audit: parse_mode в HTML-сообщениях"
# Проверяем что сообщения с HTML тегами имеют явный parse_mode="HTML"
BROKEN=$(grep -rn '\.answer(\|\.edit_text(' app/bot/ \
    | grep -v 'parse_mode' \
    | grep '<b>\|<i>\|<code>\|<pre>\|<a ' \
    | grep -v '^\s*#' || true)

if [ -z "$BROKEN" ]; then
    ok "Все HTML-сообщения имеют явный parse_mode"
else
    fail "Найдены .answer() с HTML тегами БЕЗ parse_mode=\"HTML\":"
    echo "$BROKEN" | head -10
    echo -e "  ${YELLOW}Опасность: сообщения упадут с TelegramBadRequest${NC}"
fi

# ── 6. BYTES В FSM STATE AUDIT ───────────────────────────────
step "6/9 Audit: bytes в FSM state (Redis несовместимо)"
BYTES_IN_STATE=$(grep -rn 'state\.update_data\|state\.set_data' app/ \
    | grep 'raw_bytes\b' \
    | grep -v 'raw_bytes_b64\|#' || true)

if [ -z "$BYTES_IN_STATE" ]; then
    ok "Нет прямого сохранения bytes в FSM state"
else
    fail "Найдено сохранение bytes в FSM state — Redis не сможет сериализовать:"
    echo "$BYTES_IN_STATE"
fi

# ── 7. ТЕСТЫ С ПОКРЫТИЕМ ─────────────────────────────────────
step "7/9 Pytest с покрытием"
TEST_ENV="TELEGRAM_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789 \
OPENAI_API_KEY=test NOTION_TOKEN=test NOTION_DB_MEETINGS_ID=test"

if eval "$TEST_ENV pytest --cov=app --cov-report=term-missing \
    --cov-report=xml -q 2>&1"; then
    ok "Все тесты прошли"
    # Извлекаем % покрытия
    COVERAGE=$(python3 -c "
import xml.etree.ElementTree as ET
try:
    tree = ET.parse('coverage.xml')
    cov = float(tree.getroot().attrib.get('line-rate', 0)) * 100
    print(f'{cov:.0f}%')
except: print('N/A')
" 2>/dev/null)
    ok "Покрытие тестами: $COVERAGE"
else
    fail "Тесты упали!"
fi

# ── 8. БЕЗОПАСНОСТЬ ──────────────────────────────────────────
step "8/9 Bandit безопасность"
if bandit -r app/ -ll -q 2>&1; then
    ok "Bandit: критических уязвимостей нет"
else
    warn "Bandit нашёл предупреждения (проверьте вручную)"
fi

# ── 9. ЗАВИСИМОСТИ ───────────────────────────────────────────
step "9/9 Зависимости"

echo "  pip-audit..."
if pip-audit --desc 2>&1; then
    ok "pip-audit: уязвимых зависимостей нет"
else
    warn "pip-audit: найдены уязвимые зависимости (проверьте вручную)"
fi

echo "  deptry (неиспользуемые / отсутствующие)..."
if deptry . --ignore DEP002 2>&1; then
    ok "deptry: зависимости в порядке"
else
    warn "deptry нашёл замечания"
fi

# ── ИТОГ ─────────────────────────────────────────────────────
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}🎉 CI Pipeline пройден! (${ELAPSED}с)${NC}"
else
    echo -e "${RED}❌ CI Pipeline завершён с ошибками (${ELAPSED}с)${NC}"
fi

echo ""
echo -e "  ${GREEN}✅ Pass:${NC}  $PASS"
echo -e "  ${YELLOW}⚠️  Warn:${NC}  $SKIP"
echo -e "  ${RED}❌ Fail:${NC}  $FAIL"
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "${RED}Исправьте ошибки перед пушем!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Код готов к коммиту и пушу!${NC}"
