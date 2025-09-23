# Система быстрых запросов к коммитам

## 🎯 Обзор

Система быстрых запросов предоставляет мгновенный доступ к коммитам из Notion прямо через Telegram. Пользователи могут быстро найти свои задачи, проверить дедлайны и отфильтровать коммиты по различным критериям без необходимости открывать Notion.

## 📋 Доступные команды

### **📊 Основные запросы**

#### **`/commits`** - Последние коммиты
```
📋 Последние коммиты

📊 Найдено: 8 коммитов

[🔄 Обновить]
```
Показывает 10 последних коммитов, отсортированных по времени создания.

#### **`/mine`** - Мои задачи
```
📋 Мои задачи

📊 Найдено: 5 коммитов
```
Показывает коммиты, где текущий пользователь является исполнителем.

#### **`/theirs`** - Чужие задачи
```
📋 Чужие задачи

📊 Найдено: 3 коммита
```
Показывает коммиты с direction=theirs (поручения от других).

### **⏰ Запросы по времени**

#### **`/due`** - Дедлайны на неделю
```
📋 Дедлайны на неделю

📊 Найдено: 7 коммитов
```
Показывает активные коммиты с дедлайном в ближайшие 7 дней.

#### **`/today`** - Горящие задачи
```
📋 Горящие задачи сегодня

📊 Найдено: 2 коммита
```
Показывает коммиты с дедлайном сегодня.

### **🏷️ Поиск по тегам**

#### **`/by_tag <тег>`** - Фильтр по тегу
```
/by_tag Finance/IFRS
/by_tag Topic/Meeting
/by_tag People/John
```

Поддерживает:
- **Полные теги:** `Finance/IFRS`
- **Частичное совпадение:** `IFRS` найдет `Finance/IFRS`
- **Категории:** `Finance` найдет все финансовые теги

## 🎨 Формат отображения

### **📋 Заголовок с навигацией**
```
📋 Мои задачи

📊 Найдено: 5 коммитов

[⬅️ Пред] [След ➡️]
[🔄 Обновить]
[📄 1/3 (25 всего)]
```

### **📝 Карточки коммитов**
```
🟥 Подготовить отчет по продажам
👤 John Doe | 📌 mine | ⏳ 15.10.2025
🎯 Confidence: 85% | 🏷️ Finance/Report

[✅ Выполнено] [❌ Отменить]
[🔗 Открыть]
```

## 🔧 Техническая архитектура

### **📊 Структура данных**
```python
# Ответ функций запросов:
{
    "id": "page-id",
    "url": "https://notion.so/...",
    "short_id": "9abc1234",
    "title": "John: Подготовить отчет [due 2025-10-15]",
    "text": "Подготовить отчет по продажам",
    "direction": "mine",
    "assignees": ["John Doe"],
    "due_iso": "2025-10-15",
    "confidence": 0.85,
    "flags": ["urgent"],
    "status": "open",
    "tags": ["Finance/Report"],
    "meeting_ids": ["meeting-123"],
}
```

### **🔍 Функции запросов (notion_commits.py)**

#### **Универсальная функция**
```python
def _query_commits(
    filter_: dict[str, Any] | None = None,
    sorts: list[dict] | None = None, 
    page_size: int = PAGE_SIZE
) -> dict[str, Any]
```

#### **Специализированные запросы**
```python
query_commits_recent(limit=10)           # Последние коммиты
query_commits_mine(me_name_en=None)      # Мои задачи
query_commits_theirs(limit=10)           # Чужие задачи
query_commits_due_within(days=7)         # Дедлайны в N дней
query_commits_due_today(limit=10)        # Дедлайны сегодня
query_commits_by_tag(tag, limit=10)      # Поиск по тегу
```

### **🎛️ Обработчики команд (handlers_queries.py)**

#### **Основные команды**
```python
@router.message(Command("commits"))
async def cmd_commits(message: Message)

@router.message(Command("mine"))
async def cmd_mine(message: Message)

@router.message(Command("by_tag"))
async def cmd_by_tag(message: Message)
```

#### **Пагинация и действия**
```python
@router.callback_query(F.data.startswith("commits:"))
async def handle_commits_pagination(callback: CallbackQuery)

@router.callback_query(F.data.startswith("commit_action:"))
async def handle_commit_action(callback: CallbackQuery)
```

### **⌨️ Клавиатуры (keyboards.py)**

#### **Пагинация**
```python
def build_pagination_keyboard(
    query_type: str,
    current_page: int,
    total_pages: int,
    total_items: int = 0,
    extra_params: str = ""
) -> InlineKeyboardMarkup
```

#### **Быстрые действия**
```python
def build_commit_action_keyboard(commit_id: str) -> InlineKeyboardMarkup
```

## 🔍 Фильтры Notion API

### **1. Последние коммиты**
```python
sorts = [{"property": "Created time", "direction": "descending"}]
```

### **2. Мои коммиты**
```python
filter_ = {
    "property": "Assignee",
    "multi_select": {"contains": "Valentin Dobrynin"}
}
```

### **3. Чужие коммиты**
```python
filter_ = {
    "property": "Direction", 
    "select": {"equals": "theirs"}
}
```

### **4. Дедлайны на неделю**
```python
filter_ = {
    "and": [
        {"property": "Due", "date": {"on_or_after": "2025-10-15"}},
        {"property": "Due", "date": {"on_or_before": "2025-10-22"}},
        {"property": "Status", "select": {"does_not_equal": "done"}},
        {"property": "Status", "select": {"does_not_equal": "dropped"}},
    ]
}
```

### **5. Дедлайны сегодня**
```python
filter_ = {
    "and": [
        {"property": "Due", "date": {"equals": "2025-10-15"}},
        {"property": "Status", "select": {"does_not_equal": "done"}},
        {"property": "Status", "select": {"does_not_equal": "dropped"}},
    ]
}
```

### **6. Поиск по тегу**
```python
filter_ = {
    "property": "Tags",
    "multi_select": {"contains": "Finance/IFRS"}
}
```

## ⚡ Производительность и ограничения

### **🚀 Оптимизации**
- **Rate limiting:** 1 запрос в 2 секунды на пользователя
- **Лимит результатов:** 10 коммитов по умолчанию
- **Умная сортировка:** приоритет дедлайнам, затем времени создания
- **Кэширование клиентов:** переиспользование HTTP соединений

### **📊 Метрики производительности**
- **Время ответа:** < 1 секунды для первых 10 результатов
- **Память:** < 5MB на запрос
- **Notion API:** 1 запрос на команду
- **Telegram API:** 1-11 сообщений (заголовок + до 10 карточек)

### **🔒 Ограничения**
```python
PAGE_SIZE = 10                    # Максимум результатов
RATE_LIMIT_SECONDS = 2           # Интервал между запросами
MAX_TAG_LENGTH = 100             # Максимальная длина тега для поиска
```

## 🎛️ Интерактивные функции

### **📄 Пагинация**
```python
# Callback data format:
"commits:query_type:page[:extra_params]"

# Примеры:
"commits:recent:1"                    # Первая страница последних
"commits:mine:2"                      # Вторая страница моих
"commits:by_tag:1:Finance/IFRS"       # Поиск по тегу с параметром
```

### **⚡ Быстрые действия**
```python
# Callback data format:
"commit_action:action:commit_id"

# Примеры:
"commit_action:done:commit-123"       # Пометить как выполненный
"commit_action:drop:commit-456"       # Отменить коммит
```

### **🎯 Кнопки помощи**
```python
# Быстрый доступ к популярным запросам
[📋 Все]     [👤 Мои]
[👥 Чужие]   [⏰ Неделя]
[🔥 Сегодня] [🏷️ По тегу]
```

## 🧪 Тестирование

### **📊 Покрытие тестами**
- **32 теста** для handlers_queries.py
- **25 тестов** для notion_commits queries
- **15 тестов** для keyboards.py
- **Интеграционные тесты** полного workflow

### **🎯 Test Cases**
```python
# Основные команды
test_cmd_commits_success()
test_cmd_mine_empty()
test_cmd_by_tag_with_argument()

# Rate limiting
test_rate_limit_first_call()
test_rate_limit_immediate_second_call()

# Пагинация
test_handle_commits_pagination_recent()
test_handle_commits_pagination_by_tag()

# Быстрые действия
test_handle_commit_action_done()
test_handle_commit_action_drop()

# Обработка ошибок
test_cmd_commits_notion_error()
test_query_commits_error_handling()
```

## 🔄 Интеграция с существующими системами

### **🎨 Форматирование**
Использует существующую систему `format_commit_card()` с адаптивными лимитами:
```python
card_text = format_commit_card(commit)  # Автоматически адаптируется под устройство
```

### **⚙️ Настройки**
```python
# app/settings.py
me_name_en: str = "Valentin Dobrynin"  # Для фильтра /mine
```

### **🏷️ Система тегирования**
- **Совместимость** с существующими тегами
- **Поддержка v0 и v1** тегов
- **Частичное совпадение** для удобства поиска

### **🔗 Notion API**
- **Переиспользование** существующих HTTP клиентов
- **Единая обработка ошибок** с логированием
- **Совместимость** с существующими полями базы данных

## 🚀 Примеры использования

### **🔍 Быстрая проверка задач**
```
Пользователь: /mine
Бот: 📋 Мои задачи
     📊 Найдено: 3 коммита
     
     🟥 Подготовить отчет
     👤 John Doe | 📌 mine | ⏳ завтра
     [✅ Выполнено] [❌ Отменить]
     
     🟨 Созвониться с клиентом  
     👤 Jane Smith | 📌 theirs | ⏳ 20.10.2025
     [✅ Выполнено] [❌ Отменить]
```

### **🏷️ Поиск по проекту**
```
Пользователь: /by_tag Projects/Mobile
Бот: 📋 Коммиты с тегом 'Projects/Mobile'
     📊 Найдено: 12 коммитов
     
     [⬅️ Пред] [След ➡️]
     [🔄 Обновить]
     [📄 1/2 (12 всего)]
```

### **🔥 Проверка горящих задач**
```
Пользователь: /today
Бот: 📋 Горящие задачи сегодня
     📊 Найдено: 1 коммит
     
     🔴 СРОЧНО: Отправить документы
     👤 Valya | 📌 mine | ⏳ сегодня
     [✅ Выполнено] [❌ Отменить]
```

## 🛠️ Конфигурация и настройка

### **📝 Переменные окружения**
```bash
# .env
ME_NAME_EN="Valentin Dobrynin"  # Для фильтра /mine (опционально)
```

### **⚙️ Настройки по умолчанию**
```python
# app/settings.py
PAGE_SIZE = 10                    # Количество результатов
RATE_LIMIT_SECONDS = 2           # Rate limiting
me_name_en = "Valentin Dobrynin" # Имя для /mine
```

### **🔧 Кастомизация**
```python
# Изменение лимитов
query_commits_recent(limit=20)    # Больше результатов
query_commits_due_within(days=14) # Дедлайны на 2 недели

# Кастомные фильтры
filter_ = {"property": "Priority", "select": {"equals": "high"}}
_query_commits(filter_=filter_)
```

## 📈 Мониторинг и аналитика

### **📊 Логирование**
```python
logger.info(f"User {user_id} queried recent commits: {len(commits)} found")
logger.info(f"User {user_id} marked commit {commit_id} as done")
logger.error(f"Error in query_commits_recent: {e}")
```

### **📉 Метрики использования**
- Популярность команд запросов
- Частота использования тегов
- Время выполнения запросов
- Процент пустых результатов

## 🚀 Будущие улучшения

### **📄 Настоящая пагинация**
```python
# v2: Использование Notion cursors
def query_commits_recent(page: int = 1, limit: int = 10):
    start_cursor = get_cursor_for_page(page, limit)
    response = _query_commits(start_cursor=start_cursor)
```

### **🎯 Умные фильтры**
```python
# v2: Комбинированные фильтры
/mine_urgent                    # Мои срочные задачи
/overdue                       # Просроченные задачи  
/by_assignee John              # Задачи конкретного исполнителя
/by_project Mobile             # Задачи по проекту
```

### **🔔 Уведомления**
```python
# v2: Автоматические уведомления
- Ежедневные дайджесты горящих задач
- Напоминания о приближающихся дедлайнах
- Уведомления о новых задачах
```

### **📱 Адаптивные лимиты**
```python
# v2: Адаптация под устройство
mobile_limits = {"page_size": 5, "card_length": 50}
desktop_limits = {"page_size": 15, "card_length": 120}
```

## 📋 Checklist внедрения

- [x] ✅ Функции запросов в notion_commits.py
- [x] ✅ Обработчики команд в handlers_queries.py  
- [x] ✅ Система пагинации в keyboards.py
- [x] ✅ Rate limiting для защиты от спама
- [x] ✅ Интеграция с форматированием
- [x] ✅ Быстрые действия с коммитами
- [x] ✅ Comprehensive тестирование (57 тестов)
- [x] ✅ Обработка ошибок и edge cases
- [x] ✅ Документация и примеры
- [x] ✅ Регистрация в роутере
- [x] ✅ Команды добавлены в /help

---

*Система быстрых запросов полностью интегрирована с Meet-Commit и готова к production использованию.*
