PYTHON ?= .venv/bin/python

.PHONY: dev down logs backend-test backend-lint frontend-test frontend-lint frontend-build test lint e2e ci

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

frontend-build:
	cd frontend && npm run build

test: backend-test frontend-test frontend-build

lint: backend-lint frontend-lint

e2e:
	./scripts/e2e.sh

ci: lint test
