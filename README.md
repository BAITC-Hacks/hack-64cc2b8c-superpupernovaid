# SuperPuperNovaID

Каркас для быстрой разработки прототипа: модульный монолит на **FastAPI**, отдельное
**React + TypeScript + Vite** приложение с Bootstrap 5 и фоновый процесс Celery.
API и воркер собираются из одного бэкенда и используют общие сценарии приложения.
Оркестрация ИИ — **OpenAI Agents SDK**. По умолчанию включён явный деморежим без запросов к ИИ.

## Быстрый запуск

Нужен запущенный Docker Desktop / Docker Engine с Compose **2.24.4+**.
Из корня репозитория:

```sh
# Только если .env ещё нет (существующий файл не перезаписывать):
test -f .env || cp .env.example .env
docker compose up --build -d
```

Существующий `.env` сохранён. Добавляйте недостающие переменные по `.env.example`.
Основной стек запускается и с минимальным `.env`: значения для разработки заданы по умолчанию.
Миграции выполняет одноразовый сервис `migrate` перед стартом API и воркера.

| Сервис | Адрес |
| --- | --- |
| React | http://localhost:8080 |
| FastAPI Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| OpenAPI JSON | http://localhost:8000/openapi.json |
| Проверка API | http://localhost:8000/api/v1/health |
| Готовность PostgreSQL и Redis | http://localhost:8000/api/v1/ready |

Откройте фронтенд, отправьте запрос и дождитесь результата. API сохраняет задание,
публикует его ID в Redis, Celery получает задание, запускает сценарий и сохраняет результат в PostgreSQL.
Фронтенд опрашивает статус. Состояния: `queued → running → succeeded / failed`.

```sh
docker compose logs -f backend worker
docker compose ps
docker compose down  # данные остаются в named volumes
```

## Структура и чистая архитектура

```text
backend/
  src/app/
    domain/          # Python-сущности и статусы, без внешних библиотек
    application/     # сценарии и порты (Protocol), без FastAPI / SQLAlchemy / SDK
    infrastructure/  # SQLAlchemy, Celery, OpenAI Agents, SMTP, S3
    entrypoints/     # HTTP API и Celery-задачи
    bootstrap.py     # связывание портов и адаптеров
    config.py        # настройки среды
  migrations/        # Alembic и начальная схема jobs
  tests/             # сценарии, HTTP-контракт, обработка ошибок, SDK wiring
  pyproject.toml
  uv.lock
frontend/
  src/
    components/layout/ # каркас страницы
    components/ui/     # переиспользуемые React-компоненты на Bootstrap
    features/jobs/     # экран, React hook и типизированный API заданий
    lib/               # общая HTTP-обвязка
  package-lock.json
compose.yaml           # основной стек и опциональные профили
compose.dev.yaml       # Vite HMR / Uvicorn reload
.env.example
```

Зависимости направлены внутрь: `entrypoints / infrastructure → application → domain`.
Сценарии принимают порты через конструктор; инфраструктура подставляется в `bootstrap.py`.
Добавляя бизнес-функцию, сначала создайте доменную модель и сценарий, затем адаптер и маршрут.
Не помещайте бизнес-правила в HTTP-обработчики, Celery-задачи или React-компоненты.
Новые внешние сервисы подключайте реализацией порта; отдельный микросервис для этого не нужен.

## ИИ

В `.env`:

```dotenv
AI_MODE=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4.1-mini
```

Модель — настраиваемое значение; укажите доступную вашему OpenAI-проекту модель.
Затем пересоздайте процессы:

```sh
docker compose up -d --force-recreate backend worker
```

`Coordinator` отвечает на простые запросы и может передать анализ требований агенту
`Prototype analyst` через handoff. Лимит — 8 шагов и 120 секунд на запуск.
Ключ остаётся на сервере; SDK tracing выключен в стартовой конфигурации.
`AI_MODE=mock` использует детерминированный адаптер и не вызывает OpenAI даже при наличии ключа.
Точки расширения: новые агенты и инструменты в `infrastructure/agents.py`,
новые сценарии в `application/`.

Документация: [OpenAI Agents SDK — Quickstart](https://developers.openai.com/api/docs/guides/agents/quickstart).

## Разработка

С hot reload в Docker:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

Фронтенд будет на http://localhost:5173. Код API перезагружается автоматически.
После изменения кода воркера: `docker compose restart worker`.
После изменения зависимостей пересоберите образы.

Локальная разработка требует Python **3.12+**, `uv`, Node.js **22.12+**, npm.
Старая корневая `.venv` не используется; `uv` создаёт `backend/.venv`.

```sh
docker compose up -d postgres redis
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn app.entrypoints.api:app --reload
```

В другом терминале из `backend/`:

```sh
uv run celery -A app.infrastructure.queue:celery_app worker --loglevel=info --pool=solo
```

В третьем терминале из `frontend/`:

```sh
npm ci
npm run dev
```

На macOS для локального Celery используйте `--pool=solo`; в Linux-контейнере работает prefork.
Vite проксирует `/api` в `localhost:8000`, nginx в контейнере — в `backend:8000`.
`.env` читается из корня проекта. Compose заменяет адреса PostgreSQL, Redis, SMTP и S3
на внутренние имена контейнеров. API ключи не помещайте в переменные `VITE_*`.

## API

```sh
curl -X POST http://localhost:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Составь план прототипа"}'

curl http://localhost:8000/api/v1/jobs/UUID_FROM_RESPONSE
```

Создание возвращает HTTP 202 с ID. Пустой запрос — 422, неизвестный ID — 404,
ошибка публикации в очередь — 503. Полная схема доступна в Swagger.

## Почта и S3 / MinIO

Сервисы включаются по мере необходимости:

```sh
docker compose --profile storage --profile mail up -d
```

- MinIO API: http://localhost:9000, консоль: http://localhost:9001.
  Для разработки логин/пароль `minioadmin` / `minioadmin`; соответствуют `S3_ACCESS_KEY` / `S3_SECRET_KEY`.
  Создайте bucket `prototype` в консоли (или значение `S3_BUCKET`).
- Mailpit: SMTP `localhost:1025`, просмотр писем http://localhost:8025.
  Это локальный перехватчик писем, а не доставка во внешние почтовые ящики.
- Порты `FileStorage` и `MailSender` уже определены, адаптеры `S3FileStorage` и `SmtpMailSender`
  готовы для подключения в сценарии через `bootstrap.py`. HTTP-эндпоинтов загрузки/рассылки пока нет.
- При подключении реального SMTP задайте `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
  `SMTP_STARTTLS=true`, `SMTP_FROM`. В Compose также замените принудительный `SMTP_HOST: mailpit`.
- S3 presigned URL использует `S3_ENDPOINT_URL`: внутреннее имя `minio` недоступно браузеру.
  Перед выдачей ссылок наружу настройте единый доступный hostname/reverse proxy и endpoint.

## Проверки и миграции

```sh
cd backend
uv run ruff check .
uv run pytest
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head

# Из frontend/:
npm ci
npm run build
```

Тесты используют SQLite и подменённые внешние адаптеры, без платных вызовов ИИ.
Проверяйте сгенерированные миграции перед применением. Зависимости зафиксированы в
`uv.lock` и `package-lock.json`; Docker использует frozen/ci установку.

## Границы стартового прототипа

Стек предназначен для локальной разработки: нет авторизации, разделения заданий по пользователям,
rate limiting, отмены заданий и восстановления истории в UI после обновления страницы.
Задания остаются в PostgreSQL и доступны по ID. Readiness проверяет БД и Redis, но не воркер.
При запуске на внешнем сервере добавьте авторизацию, TLS и собственные секреты.

Запись в БД и публикация в Redis пока не атомарны: для гарантированной доставки следующим шагом
нужен transactional outbox. Повторная доставка защищена атомарным захватом задания,
но при аварийном завершении воркера `running` может остаться без результата: нужен lease/timeout
и механизм восстановления. Автоповторы ИИ не включены, чтобы не дублировать платные операции.
MinIO и SMTP адаптеры подготовлены для будущих сценариев; они не вызываются при запуске приложения.
