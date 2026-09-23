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
make build
make up
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

## Media ingestion

Реализован самостоятельный модуль приёма аудио/видеозаписей:
`POST /api/v1/meetings/{meeting_id}/media` (multipart поле `file`).
Возвращает сохранённый `MediaAsset`; оригиналы лежат в volume `media-data`,
метаданные — в PostgreSQL. ffprobe входит в backend-образ. Обработка речи не запускается.

Контракт, curl, настройки, модель, хранение и расширение:
[docs/media-ingestion.md](docs/media-ingestion.md).

## Audio preprocessing

`POST /api/v1/meetings/{meeting_id}/media/{media_id}/preprocess` готовит отдельный
`NormalizedAudio`: по умолчанию WAV / PCM16 / 16 кГц / mono. Оригинал не изменяется.
Повторный вызов использует проверенный артефакт той же конфигурации. Конвертация через
FFmpeg идёт вне event loop, без ASR, diarization и внешних AI API.

По умолчанию одновременно принимаются две загрузки и выполняется одна конвертация;
перегрузка возвращает `429` с `Retry-After`. Ограничения действуют на один процесс API.
Контракт, настройки, ограничения памяти/диска и результаты проверки:
[docs/audio-preprocessing.md](docs/audio-preprocessing.md).

## Speech processing

Добавлен независимый `NormalizedAudio → ASR + diarization → AttributedTranscript`:
`POST /api/v1/meetings/{meeting_id}/media/{media_id}/speech`.
Результат содержит `source_audio_id` и сегменты `id/start/end/speaker_id/text`, сохраняется
в PostgreSQL и повторно используется. Имена участников и анализ смысла встречи сюда не входят.

По умолчанию `ASR_PROVIDER=nemo`, `DIARIZATION_PROVIDER=nemo`; поддержаны независимые
переключения на faster-whisper и local Pyannote, включая hybrid combinations.
`SPEECH_ENABLED=false` сохраняет лёгкий запуск без ML packages. Для real inference нужны
локальные модели, отдельное ML-окружение и подходящие ресурсы; базовый API-контейнер
с лимитом 1 ГиБ для этого не предназначен. Реальные GPU-модели пока не проверены.

[Контракты, настройки, установка, ограничения и тесты Speech](docs/speech-processing.md).

## Transcript canonicalization

`POST /api/v1/meetings/{meeting_id}/media/{media_id}/canonicalize` преобразует уже
сохранённый AttributedTranscript в отдельный CanonicalTranscript. ID, speakers,
timestamps и original_text сохраняются; LLM генерирует только canonical_text/uncertainty.
Один Agents SDK agent, bounded batches/retries/concurrency, отдельная таблица результатов.

Опциональный **OpenAI cloud** этап по новому запросу, по умолчанию выключен.
Модель задаётся TRANSCRIPT_CANONICALIZATION_MODEL, язык — TRANSCRIPT_CANONICAL_LANGUAGE=ru.
Это исключение из исходного on-prem направления, не локальный inference.
[Контракт, настройки, примеры и проверки](docs/transcript-canonicalization.md).

Реальная проверка записи через HTTP pipeline и повторяемый runner:
[docs/meeting-benchmark.md](docs/meeting-benchmark.md).

## Структура модульного монолита

```text
backend/
  src/app/
    media/           # самостоятельный media ingestion module
    audio/           # нормализация аудио и повторное использование артефактов
    speech/          # независимые ASR / diarization, alignment и transcript
    canonicalization/ # отдельный перевод mixed transcript с сохранением metadata
    domain/          # существующие Python-сущности заданий
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
compose.infra.yaml     # PostgreSQL/Redis и опциональные MinIO/Mailpit
compose.yaml           # приложение, включает инфраструктуру
compose.dev.yaml       # Vite HMR / Uvicorn reload
.env.example
```

Существующий модуль demo-заданий организован слоями: `entrypoints / infrastructure → application → domain`.
Сценарии принимают порты через конструктор; инфраструктура подставляется в `bootstrap.py`.
Добавляя бизнес-функцию, сначала создайте доменную модель и сценарий, затем адаптер и маршрут.
Для новых модулей используйте компактную функциональную структуру, как в `media/`:
FastAPI modular monolith + dependency inversion только на заменяемых границах.
Не вводите дополнительные архитектурные слои ради шаблона.
Не помещайте бизнес-правила в HTTP-обработчики, Celery-задачи или React-компоненты.
Новые внешние сервисы подключайте реализацией порта; отдельный микросервис для этого не нужен.

## ИИ

Следующий раздел относится к отдельному demo-заданию. Основное решение автопротоколирования
должно работать в закрытом контуре: реальные записи и транскрипты нельзя передавать в cloud API.
[Согласованный контекст и границы будущих модулей](docs/project-context.md).

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

Быстрый режим с hot reload:

```sh
make setup-dev       # один раз: собрать зависимости и запустить
make dev             # последующие старты, без сборки
make logs            # логи приложения
make restart-worker  # после изменений кода Celery
make migrate         # после добавления миграции (БД должна работать)
make stop-app        # остановить приложение, оставить БД и Redis
make rebuild-dev     # после изменения зависимостей / Dockerfile
```

React: http://localhost:5173, Swagger: http://localhost:8000/docs.
Изменения API и React подхватываются автоматически; `make dev` после каждого сохранения не нужен.
Описание экранов Qoryt, границ текущей реализации и точек подключения будущих API:
[docs/frontend-ui.md](docs/frontend-ui.md).
PostgreSQL/Redis вынесены в `compose.infra.yaml`; `make infra` запускает только их.
Основной `compose.yaml` включает инфраструктуру и сохраняет прежние volumes.
Backend, worker и migrate используют один Python-образ. Dev-образ содержит зависимости,
а исходники примонтированы с хоста. Полный упакованный стек: `make build && make up`.
Режимы dev и packaged используют один проект Compose и переключаются, а не работают одновременно.
Подробности и правила пересборки: [docs/development.md](docs/development.md).

Локальная разработка требует Python **3.12+**, `uv`, Node.js **22.12+**, npm.
Старая корневая `.venv` не используется; `uv` создаёт `backend/.venv`.

```sh
make infra
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
COMPOSE_IGNORE_ORPHANS=true docker compose -f compose.infra.yaml --profile storage --profile mail up -d
```

- MinIO API: http://localhost:9000, консоль: http://localhost:9001.
  Для разработки логин/пароль `minioadmin` / `minioadmin`; соответствуют `S3_ACCESS_KEY` / `S3_SECRET_KEY`.
  Создайте bucket `prototype` в консоли (или значение `S3_BUCKET`).
- Mailpit: SMTP `localhost:1025`, просмотр писем http://localhost:8025.
  Это локальный перехватчик писем, а не доставка во внешние почтовые ящики.
- Порты `FileStorage` и `MailSender` уже определены, адаптеры `S3FileStorage` и `SmtpMailSender`
  готовы для подключения в сценарии через `bootstrap.py`. Media upload уже реализован с local storage; рассылка пока не подключена.
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

Обычный запуск тестов использует SQLite и подменённые внешние адаптеры, без вызовов ИИ.
Отдельно: `uv run pytest -m integration` проверяет media через настоящий ffprobe/ffmpeg.
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

### Облачная обработка речи NVIDIA

Для запуска без локального GPU доступны `ASR_PROVIDER=nvidia` и
`DIARIZATION_PROVIDER=nvidia`: Parakeet возвращает текст, таймкоды и метки говорящих
одним запросом. Ключ — `NVIDIA_API_KEY` в `.env`. Русский проверен; казахский этим
режимом не покрывается. Лимит — 16 МиБ нормализованного WAV (~8 мин 44 с).
[Настройка, запуск и ограничения](docs/nvidia-cloud-speech.md).
