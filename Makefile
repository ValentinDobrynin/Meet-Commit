.PHONY: dev up down logs test lint fmt precommit-install precommit-run

dev: up

up:
	docker compose -f docker-compose.local.yml up --build

down:
	docker compose -f docker-compose.local.yml down -v

logs:
	docker compose -f docker-compose.local.yml logs -f app

test:
	TELEGRAM_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789 \
	OPENAI_API_KEY=test \
	NOTION_TOKEN=test \
	NOTION_DB_MEETINGS_ID=test \
	pytest -v

lint:
	ruff check .

fmt:
	ruff format .

precommit-install:
	pip install -r requirements.txt
	pre-commit install

precommit-run:
	pre-commit run --all-files
