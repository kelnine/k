# K Terminal — developer shortcuts. Run from the terminal/ directory.
.DEFAULT_GOAL := help
SHELL := /bin/bash

UV        := uv run --project backend
COMPOSE   := docker compose --project-directory deploy $(if $(wildcard .env),--env-file .env,) -f deploy/docker-compose.yml
COMPOSE_DEV := $(COMPOSE) -f deploy/docker-compose.dev.yml
TEST_DB   ?= postgresql://kterminal:kterminal@localhost:5432/kterminal_test

.PHONY: help install lint format typecheck contracts test test-unit check api engine worker \
        config secrets up down logs dev-up dev-db migrate catalog strategies demo demo-db

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install backend dependencies (uv)
	uv sync --project backend

lint: ## Ruff lint + format check
	cd backend && uv run ruff check . && uv run ruff format --check .

format: ## Auto-format and fix lint
	cd backend && uv run ruff format . && uv run ruff check --fix .

typecheck: ## mypy --strict
	cd backend && uv run mypy

contracts: ## Architecture contracts (import-linter)
	cd backend && uv run lint-imports

test: ## All tests (integration tests need PostgreSQL at TEST_DB)
	cd backend && KT_TEST_DATABASE_URL=$(TEST_DB) uv run pytest

test-unit: ## Unit tests only
	cd backend && uv run pytest tests/unit

check: lint typecheck contracts test ## Everything CI runs

api: ## Run the API locally (reads ./.env)
	$(UV) kterminal api

engine: ## Run the engine locally
	$(UV) kterminal engine

worker: ## Run a worker locally
	$(UV) kterminal worker

config: ## Validate and summarize configuration
	$(UV) kterminal config check

migrate: ## Apply database migrations (reads ./.env)
	$(UV) kterminal db upgrade

catalog: ## Validate the instrument catalog (config/catalog)
	$(UV) kterminal catalog validate

strategies: ## List strategy definitions and lab instances
	$(UV) kterminal strategies list

demo: ## Run the lab demo in memory (two strategies, two Paper 50K accounts)
	$(UV) kterminal lab demo

demo-db: ## Run the lab demo recording everything in PostgreSQL (run make migrate first)
	$(UV) kterminal lab demo --store postgres

secrets: ## Generate deploy/secrets/* (never committed)
	@install -d -m 700 deploy/secrets
	@if [ ! -f deploy/secrets/postgres_password ]; then \
		python3 -c "import secrets; print(secrets.token_urlsafe(32))" > deploy/secrets/postgres_password; \
		chmod 444 deploy/secrets/postgres_password; \
		echo "created deploy/secrets/postgres_password"; \
	else echo "deploy/secrets/postgres_password already exists"; fi

up: secrets ## Build and start the full stack
	$(COMPOSE) up -d --build

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow logs
	$(COMPOSE) logs -f --tail=100

dev-up: secrets ## Full stack with Postgres/API on localhost and console logs
	$(COMPOSE_DEV) up -d --build

dev-db: secrets ## Only PostgreSQL, published on 127.0.0.1:5432
	$(COMPOSE_DEV) up -d postgres
