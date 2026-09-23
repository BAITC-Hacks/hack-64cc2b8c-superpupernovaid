.PHONY: up dev down logs test check
up:
	docker compose up --build -d
dev:
	docker compose -f compose.yaml -f compose.dev.yaml up --build
down:
	docker compose down
logs:
	docker compose logs -f backend worker
test:
	cd backend && uv run pytest
check:
	cd backend && uv run ruff check . && uv run pytest
	cd frontend && npm ci && npm run build
