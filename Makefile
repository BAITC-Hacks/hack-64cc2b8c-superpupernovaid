DEV = docker compose -f compose.yaml -f compose.dev.yaml
INFRA = COMPOSE_IGNORE_ORPHANS=true docker compose -f compose.infra.yaml

.PHONY: up build infra setup-dev rebuild-dev dev migrate restart-worker stop-app down logs test check
# Full packaged stack; explicit build is separate from daily startup.
up:
	docker compose up -d --no-build
build:
	docker compose build backend frontend
infra:
	$(INFRA) up -d postgres redis
setup-dev: rebuild-dev
rebuild-dev:
	$(DEV) build backend frontend
	$(DEV) up -d --no-build --wait backend worker frontend
dev:
	$(DEV) up -d --no-build --wait backend worker frontend
migrate:
	$(DEV) run --rm --no-deps migrate
restart-worker:
	$(DEV) restart worker
stop-app:
	$(DEV) stop frontend backend worker
down:
	docker compose down
logs:
	$(DEV) logs -f backend worker frontend
test:
	cd backend && uv run pytest
check:
	cd backend && uv run ruff check . && uv run pytest
	cd frontend && npm ci && npm run build
