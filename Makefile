.PHONY: up down test lint migrate revision seed seed-demo

up:
	docker compose up --build -d

down:
	docker compose down

test:
	docker compose exec backend pytest

lint:
	docker compose exec backend ruff check .
	docker compose exec frontend npm run lint

migrate:
	docker compose exec backend alembic upgrade head

# Usage: make revision m="add products"
revision:
	@test -n "$(m)" || (echo 'Usage: make revision m="message"' && exit 1)
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

seed:
	docker compose exec backend python -m app.seed

# Base seed + realistic demo data (idempotent)
seed-demo:
	docker compose exec backend python -m app.seed --demo
