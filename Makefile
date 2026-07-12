.PHONY: install test test-web test-all lint fmt web up down

install:
	uv sync

test-web:
	npm --prefix apps/web run test

test-all: test test-web

web:
	npm --prefix apps/web install
	npm --prefix apps/web run build

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run mypy

fmt:
	uv run ruff format core apps workers tests migrations

up:
	docker compose -f deploy/docker-compose.yml up -d --build

down:
	docker compose -f deploy/docker-compose.yml down
