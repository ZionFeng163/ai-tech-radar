PYTHON ?= .venv/bin/python

.PHONY: dev down logs backend-test backend-lint frontend-test frontend-lint test lint

dev:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

backend-test:
	cd backend && $(PYTHON) -m pytest

backend-lint:
	cd backend && $(PYTHON) -m ruff check . && $(PYTHON) -m mypy app

frontend-test:
	cd frontend && npm test

frontend-lint:
	cd frontend && npm run lint && npm run typecheck

test: backend-test frontend-test

lint: backend-lint frontend-lint
