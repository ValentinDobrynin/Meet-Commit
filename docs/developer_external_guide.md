# 👨‍💻 Meet-Commit: подробное описание проекта для стороннего разработчика

Этот документ — технический onboarding для разработчика, который подключается к проекту извне и хочет быстро понять:
1. **функционал**,
2. **архитектуру**,
3. **устройство в проде на Render и интеграции (Telegram, OpenAI, Notion, Redis)**.

---

## 1) Функционал

### 1.1. Что делает система

**Meet-Commit** — Telegram-бот, который принимает текст/файлы встречи, обрабатывает их AI-пайплайном и сохраняет результаты в Notion.

На выходе формируются:
- суммаризация встречи (несколько шаблонов),
- список обязательств/задач (commits),
- теги,
- участники,
- повестки,
- очередь ручной проверки сомнительных задач (Review Queue).

### 1.2. Пользовательские сценарии

Ключевые сценарии:
- **Ingest встречи**: пользователь отправляет файл (`.txt/.pdf/.docx/.vtt`) или текст → бот запускает обработку.
- **Суммаризация**: выбор шаблона из `prompts/summarization/*`.
- **Извлечение коммитов**: автоматический разбор обещаний/обязательств из текста.
- **Тегирование**: автоматическая постановка тегов + интерактивная корректировка.
- **Работа с задачами**: `/commit`, `/llm`, `/mine`, `/due`, `/commits`, `/by_tag`, `/by_assignee`.
- **Повестки**: `/agenda`, `/agenda_person`, `/agenda_tag`, `/agenda_meeting`.
- **Review-процессы**: `/review`, `/confirm`, `/delete`, `/assign`, `/flip`.
- **People management**: автоматическое обнаружение людей + верификация через команды people miner.

### 1.3. Основные бизнес-объекты

- **Meeting**: карточка встречи (summary, date, attendees, tags, hash источника).
- **Commit**: обязательство/задача (title, assignee, due date, направление mine/theirs и т.д.).
- **Review item**: кандидат в задачу с недостаточной уверенностью, ожидающий ручного решения.
- **Agenda**: собранная повестка по встрече/человеку/тегу.
- **Tag catalog**: каталог правил тегирования (в т.ч. синхронизация с Notion).

### 1.4. Контуры качества данных

В проекте встроены механизмы защиты качества:
- дедупликация встреч по hash,
- валидация и нормализация коммитов,
- Review Queue для неоднозначных задач,
- словари людей и стоп-слов,
- метрики, структурированное логирование и health endpoint.

---

## 2) Архитектура

### 2.1. Слои приложения

Структура кода организована по слоям:

- `app/bot/*` — Telegram-интерфейс (aiogram router'ы, FSM-состояния, клавиатуры).
- `app/core/*` — бизнес-логика и доменные сервисы (normalization, tagging, LLM extraction/summarization, review, people, metrics, caching).
- `app/gateways/*` — интеграции с Notion API (meetings/commits/review/agendas/tag catalog).
- `app/server.py` — HTTP-контур (FastAPI, webhook endpoint, lifespan startup/shutdown).
- `app/settings.py` — конфигурация через `pydantic-settings` и env.
- `app/dictionaries/*` и `data/*` — локальные словари и правила.
- `prompts/*` — промпты для LLM-сценариев.

### 2.2. Runtime-потоки

#### Поток A: облачный webhook (основной production)

`Telegram update -> FastAPI /telegram/webhook -> aiogram Dispatcher -> handlers -> core -> gateways -> Notion`

Особенности:
- bot/dispatcher создаются один раз на уровне модуля,
- роутеры подключаются один раз в `lifespan`,
- webhook устанавливается на старте при `DEPLOYMENT_MODE=render`.

#### Поток B: локальный polling (dev)

`aiogram start_polling -> handlers -> core -> gateways`

Используется для разработки/отладки без публичного webhook URL.

### 2.3. Основные точки расширения

Если подключается внешний разработчик, наиболее частые места доработок:
- новые команды Telegram: `app/bot/handlers_*.py` + регистрация роутера в `register_all_routers()`;
- изменения логики извлечения/нормализации: `app/core/llm_extract_commits*.py`, `commit_normalize.py`, `commit_validate.py`;
- настройка/расширение тегирования: `app/core/tagger*.py`, `app/core/tags*.py`, `data/tag_rules.yaml`;
- интеграции Notion: `app/gateways/notion_*.py`;
- новые промпты: `prompts/summarization/*`, `prompts/extraction/*`, `prompts/commits/*`.

### 2.4. Внешние зависимости

- **Telegram Bot API** — входной канал событий.
- **OpenAI API** — суммаризация, извлечение/парсинг доменных сущностей.
- **Notion API** — основное хранилище (Meetings/Commits/Review/Agendas/Tag Catalog).
- **Redis** — FSM storage в облаке.
- **FastAPI/Uvicorn** — HTTP-сервис и webhook endpoint.

---

## 3) Устройство в проде (Render) и интеграции

### 3.1. Развертывание на Render

Проект целится в схему:
- **Render Web Service** (Python + Uvicorn + FastAPI),
- **Render Redis** (состояния FSM и transient runtime data).

Контейнерная сборка:
- `Dockerfile` поднимает Python 3.11 slim,
- устанавливает `requirements.txt`,
- экспонирует `8000`,
- стартует `uvicorn app.server:app --host 0.0.0.0 --port 8000`.

### 3.2. Конфигурация и env-переменные

Критичные переменные для production:
- `TELEGRAM_TOKEN`
- `OPENAI_API_KEY`
- `NOTION_TOKEN`
- `NOTION_DB_MEETINGS_ID`
- `COMMITS_DB_ID`
- `REVIEW_DB_ID`
- `AGENDAS_DB_ID`
- `NOTION_DB_TAG_CATALOG_ID`
- `APP_ADMIN_USER_IDS`
- `DEPLOYMENT_MODE=render`
- `WEBHOOK_URL=https://<render-domain>/telegram/webhook`
- `REDIS_URL`

`app/settings.py` использует `pydantic-settings`, алиасы для части переменных и префикс `APP_` для app-specific параметров.

### 3.3. Как проект общается с Telegram

1. Telegram отправляет update на `POST /telegram/webhook`.
2. FastAPI endpoint превращает JSON в `aiogram.types.Update`.
3. Update передается в `dp.feed_update(bot, update)`.
4. aiogram роутеры и FSM обрабатывают команду/сообщение.
5. Бизнес-логика вызывает OpenAI/Notion при необходимости.
6. Ответ уходит пользователю через Bot API.

Дополнительно:
- в cloud-режиме webhook настраивается автоматически при старте приложения,
- в локальном режиме используется polling.

### 3.4. Как проект общается с Notion

Интеграция разделена на gateway-модули:
- `notion_gateway.py` — встречи,
- `notion_commits.py` — задачи,
- `notion_review.py` — очередь проверки,
- `notion_agendas.py` — повестки,
- `notion_tag_catalog.py` и `tags_notion_sync.py` — каталог тегов и синхронизация.

Технические принципы:
- централизованный клиент (`app/core/clients.py`),
- единая конфигурация timeouts/connection limits,
- логирование/метрики вокруг внешних вызовов,
- обработка ошибок интеграционного слоя.

### 3.5. Как проект общается с OpenAI

OpenAI используется в сценариях:
- суммаризация встречи,
- извлечение коммитов,
- дополнительные LLM-процессы (например, подсказки по alias).

Клиенты OpenAI также централизованы в `app/core/clients.py`, где задаются timeout'ы и профиль использования sync/async-клиентов.

### 3.6. Storage-режимы и состояние FSM

- **Local/dev:** `MemoryStorage` (aiogram FSM в памяти процесса).
- **Render/prod:** `RedisStorage` через `REDIS_URL`.
- Если Redis не поднят/недоступен — есть fallback на in-memory storage (с предупреждением в логах).

### 3.7. Health, наблюдаемость и диагностика

- `GET /healthz` — простой health check.
- `GET /debug/bot_status` — диагностика инициализации bot/dp и cloud-конфига.
- Логирование в `logs/bot.log` и `logs/bot_errors.log` + stdout.
- Внутренние метрики и админ-команды мониторинга (`/metrics`, `/webhook_status`, `/webhook_reset`).

---

## 4) Быстрый technical onboarding для нового разработчика

1. Прочитать `README.md` и `docs/README.md`.
2. Поднять локальное окружение и заполнить `.env`.
3. Запустить `python -m app.bot.main` (polling) или `uvicorn app.server:app` (webhook-style локально).
4. Прогнать `./quick-check.sh` и/или `pytest tests/ -v`.
5. Проверить связи с Notion и Telegram токены на тестовом окружении.
6. Перед внесением изменений посмотреть существующие подробные гайды в `docs/*` по нужной подсистеме (commits/tags/people/agendas).

