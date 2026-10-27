.PHONY: help up down dev-setup lint type-check test migrate check-traceability ci-check

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo "Laptop Productivity Monitoring SaaS — Makefile"
	@echo ""
	@echo "  make up                Start the full dev stack (docker compose)"
	@echo "  make down              Stop and remove containers"
	@echo "  make dev-setup         First-time setup (install deps, migrate, seed)"
	@echo "  make lint              Run linters (ruff, eslint)"
	@echo "  make type-check        Run mypy + tsc"
	@echo "  make test              Run all test suites"
	@echo "  make migrate           Run Django migrations"
	@echo "  make check-traceability  Run scripts/check_traceability.py"
	@echo "  make ci-check          Full CI gate (lint + type + test + traceability)"

# ── Docker ────────────────────────────────────────────────────────────────────
up:
	docker compose -f deploy/docker-compose.dev.yml up -d

down:
	docker compose -f deploy/docker-compose.dev.yml down

# ── Dev setup ─────────────────────────────────────────────────────────────────
dev-setup:
	python -m pip install --upgrade pip
	pip install -r backend/requirements.txt
	pip install -r agent/requirements.txt
	cd frontend && npm ci
	pre-commit install
	$(MAKE) up
	sleep 5
	$(MAKE) migrate

# ── Linting ───────────────────────────────────────────────────────────────────
lint:
	ruff check backend/ agent/ scripts/
	cd frontend && npx eslint --max-warnings 0 .

# ── Type checking ─────────────────────────────────────────────────────────────
type-check:
	mypy --strict backend/ agent/
	cd frontend && npx tsc --noEmit

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	pytest backend/ tests/ -v --tb=short
	cd frontend && npx vitest run

# ── Django ────────────────────────────────────────────────────────────────────
migrate:
	cd backend && python manage.py migrate
	cd backend && python manage.py migrate --check

# ── Traceability ──────────────────────────────────────────────────────────────
check-traceability:
	python scripts/check_traceability.py

check-traceability-final:
	python scripts/check_traceability.py --final

# ── Full CI gate ──────────────────────────────────────────────────────────────
ci-check: lint type-check test check-traceability
