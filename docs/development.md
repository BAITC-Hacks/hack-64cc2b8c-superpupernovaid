# Быстрая разработка

Не требуется перезапускать Docker Desktop или весь стек после правок кода.

| Файл | Назначение |
| --- | --- |
| compose.infra.yaml | PostgreSQL, Redis, опциональные MinIO и Mailpit |
| compose.yaml | API, worker, миграции, nginx/React; включает инфраструктуру |
| compose.dev.yaml | dev targets, bind mounts, Uvicorn reload, Vite HMR |

Все конфигурации используют проект `superpupernova`: существующие данные и имена
volumes сохранены. Это разделение жизненного цикла, приложение остаётся монолитом.

```sh
make setup-dev     # первый запуск, собирает только backend и frontend
make dev           # старт/возобновление, без build
make logs
make stop-app      # API, worker, frontend; PostgreSQL и Redis остаются
make infra         # только PostgreSQL/Redis, удобно для запуска Python/Node на хосте
```

API: http://localhost:8000/docs; React: http://localhost:5173.
Vite проксирует `/api` в API-контейнер. Python-код, миграции и React-код примонтированы
с хоста; зависимости остаются внутри образов. Backend, worker и migrate используют
один `superpupernova-backend:dev`, без трёх отдельных сборок.

| Изменение | Действие |
| --- | --- |
| Python API / React src | Просто сохранить файл: reload / HMR |
| Celery-задачи и импортируемый ими код | `make restart-worker` |
| Новая миграция | `make migrate` при работающей БД |
| .env | `make dev` пересоздаст сервисы с изменившейся конфигурацией |
| uv.lock, pyproject.toml, package-lock.json, Dockerfile | `make rebuild-dev` |
| Новый frontend config/public asset вне bind mounts | Добавить соответствующий mount в compose.dev.yaml |

`make dev` не собирает отсутствующий образ: сначала нужен `make setup-dev`.
Обычный повторный запуск не пересоздаёт неизменившиеся сервисы; одноразовый migrate
может запускаться повторно, `alembic upgrade head` безопасен при актуальной схеме.
После изменения backend-кода API reload не перезапускает Celery автоматически.

Для проверки упакованного приложения с nginx:

```sh
make build
make up
# React: http://localhost:8080
```

Dev и packaged режимы используют одни контейнеры/порты; переключение пересоздаёт
сервисы приложения. Инфраструктуру останавливать не нужно. `make down` — полная
остановка/удаление контейнеров без удаления volumes. Не используйте `down -v`,
если данные нужны. Для дополнительной инфраструктуры без переключения dev-приложения:

```sh
COMPOSE_IGNORE_ORPHANS=true docker compose -f compose.infra.yaml --profile storage --profile mail up -d
```

Локальный запуск без контейнеров приложения описан в README; PostgreSQL на хосте
доступен по порту 5332. Не запускайте локальный API одновременно с Docker API на 8000.
