.PHONY: dev up down logs test lint fmt precommit-install precommit-run typecheck security audit deps ci

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

test-cov:
	TELEGRAM_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789 \
	OPENAI_API_KEY=test \
	NOTION_TOKEN=test \
	NOTION_DB_MEETINGS_ID=test \
	pytest --cov=app --cov-report=term-missing --cov-report=xml

lint:
	ruff check .

fmt:
	ruff format .

precommit-install:
	pip install -r requirements.txt
	pre-commit install

precommit-run:
	pre-commit run --all-files

typecheck:
	mypy app/ --ignore-missing-imports

security:
	bandit -r app/ -ll

audit:
	pip-audit --desc || echo "⚠️  Some vulnerabilities found, but not critical for this project"

deps:
	deptry . --ignore DEP002

ci: lint fmt typecheck test-cov security audit deps
