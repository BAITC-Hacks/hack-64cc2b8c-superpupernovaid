# Экспорт протокола совещания

Модуль `app.protocols` представляет готовые данные в DOCX/PDF и доставляет сохранённый
файл. Он не вызывает OpenAI, NVIDIA, ASR или агентов, не генерирует summary и не
редактирует стенограмму, поручения или сроки.

## Структура

```text
backend/src/app/protocols/
├── models.py          # immutable MeetingProtocol и ExportedDocument
├── interfaces.py      # ProtocolRenderer
├── loader.py          # read-only адаптер сохранённых сущностей в snapshot
├── presentation.py    # timestamps, выбор текста, таблица поручений
├── docx.py            # DocxProtocolRenderer: python-docx
├── pdf.py             # PdfProtocolRenderer: ReportLab + DejaVu Sans
├── service.py         # лимиты, fingerprint, render, storage, download spool
├── repository.py      # метаданные protocol_exports
├── dependencies.py    # cached DI, общий FileStorage, shutdown
├── errors.py          # безопасные ошибки
└── router.py          # POST metadata, GET attachment
```

ReportLab выбран для прямой Python-генерации без HTML/CSS runtime и LibreOffice.
Для DOCX используются Word styles Title, Heading 1, Heading 2, Normal, Table Grid.
Оба renderer используют одинаковые поля и общие функции presentation; разбиение
на страницы может отличаться. Для корпоративного шаблона позже достаточно заменить
renderer и повысить его `revision`.

## Контракты и источник данных

Отдельной сохранённой сущности MeetingProtocol раньше не было. Теперь loader собирает
immutable Pydantic snapshot в одной read-only транзакции (PostgreSQL REPEATABLE READ):

- Meeting: UUID, название, дата.
- Актуальная сохранённая Speech-стенограмма и MeetingAnalysis именно этой версии.
- Participant этой версии; без имени показывается speaker_id.
- CanonicalTranscript только при совпадении audio ID, хеша исходной стенограммы,
  ID сегментов и неизменяемых исходных полей. При отсутствии используется original.
- Сохранённые Decisions и текущие Tasks. Задачи старой версии стенограммы исключены,
  ручные задачи без transcript_id включены. Имена и статус задач берутся через
  существующее представление Task API (в том числе вычисляемый overdue).

`MeetingProtocol`: meeting_id, source_transcript_id, title, scheduled_at, participants,
summary, topics, decisions, action_items, transcript. Коллекции — tuples, модели frozen.
Темы пока не хранятся в существующей БД, поэтому loader оставляет `topics=()`;
прямой вызов сервиса поддерживает переданные темы. Evidence IDs сохраняются в snapshot,
но не печатаются. Сроки из БД выводятся в ISO-формате, без догадок и пересчёта даты.

`ExportedDocument`: id, meeting_id, format (`docx|pdf`), filename, storage_key,
size_bytes, sha256, protocol_hash, created_at. Это ссылка на artifact, не Base64/bytes.
`storage_key` — внутренний ключ, не публичный URL.

```python
class ProtocolRenderer(Protocol):
    @property
    def revision(self) -> str: ...
    async def render(self, protocol: MeetingProtocol, destination: Path) -> Path: ...

artifact: ExportedDocument = await service.export(protocol, "pdf")
```

Renderer отвечает за локальный файл; сервис — за публикацию и ExportedDocument.
Отсутствующие разделы не печатаются; отсутствующие ответственный/срок показываются
как «Не определён» / «Не указан». Колонка статуса появляется, если хотя бы одна
задача имеет status. Стенограмма содержит один выбранный вариант текста и сохраняет
порядок реплик. Timestamps отбрасывают дробную секунду; часы могут превышать 24.

## Полный flow и хранение

```text
DB → ProtocolLoader → MeetingProtocol
                         ↓
                 ProtocolExportService
                   ├─ DocxProtocolRenderer → temporary protocol.docx
                   └─ PdfProtocolRenderer  → temporary protocol.pdf
                         ↓
               существующий FileStorage.save(chunks)
                         ↓
                 protocol_exports в БД
                         ↓
                 ExportedDocument
                         ↓
           проверенная временная копия → FileResponse
```

В текущем bootstrap используется LocalMediaStorage / volume media-data. Контракт
FileStorage тот же, что у media/audio; существующий S3 adapter можно подставить через DI.
Live MinIO в этом этапе не проверялся.

Ключ: `{meeting_id}/exports/{protocol_hash}/{artifact_id}.{format}`.
Имя скачивания: `meeting_11111111-1111-1111-1111-111111111111_protocol.docx`.
Название встречи не участвует в файловом пути.

Fingerprint включает точный snapshot, версию renderer и режим текста; PDF также
учитывает хеши шрифтов. Unique `(meeting_id, protocol_hash, format)` обеспечивает один
artifact для повторов и конкурирующих процессов. Проигравший при публикации удаляет
свой временный объект. Кэш проверяется по размеру/SHA-256; потерянный или повреждённый
файл пересоздаётся. Изменение данных создаёт новую версию. Бинарная идентичность
DOCX/PDF при принудительной повторной генерации не гарантируется: библиотеки могут
включать служебные даты. Содержимое детерминировано относительно snapshot.

## API и Swagger

| Метод | Endpoint | Ответ |
| --- | --- | --- |
| POST | `/api/v1/meetings/{id}/exports` | JSON ExportedDocument, body `{"format":"docx"}` или `pdf` |
| GET | `/api/v1/meetings/{id}/exports/docx` | DOCX attachment |
| GET | `/api/v1/meetings/{id}/exports/pdf` | PDF attachment |

DOCX MIME: `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.
PDF MIME: `application/pdf`.
GET выставляет `Content-Disposition: attachment; filename="meeting_<UUID>_protocol.<ext>"`,
`Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`.
Контракты доступны в `/docs` и `/openapi.json`.

```sh
# Подставьте UUID встречи с уже сохранённым анализом текущей стенограммы.
MEETING_ID=11111111-1111-1111-1111-111111111111
curl --fail-with-body -X POST "http://localhost:8000/api/v1/meetings/$MEETING_ID/exports" \
  -H 'Content-Type: application/json' -d '{"format":"docx"}'
curl --fail-with-body -OJ "http://localhost:8000/api/v1/meetings/$MEETING_ID/exports/docx"
curl --fail-with-body -OJ "http://localhost:8000/api/v1/meetings/$MEETING_ID/exports/pdf"
```

Ошибки: 404 — нет встречи; 409 `meeting_protocol_not_ready` — нет стенограммы/анализа;
413 — превышен лимит; 422 — формат/ошибка render; 429 — занят export slot
(`Retry-After: 5`); 503 — недоступен artifact/ошибка чтения источника.
Валидационные 422 используют стандарт FastAPI; ошибки модуля — `detail.code/message`.
Raw filesystem/library exceptions, API keys и текст протокола не возвращаются и не логируются.

## Настройки и ресурсы

```env
PROTOCOL_TRANSCRIPT_TEXT_MODE=canonical
PROTOCOL_PDF_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
PROTOCOL_PDF_BOLD_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
PROTOCOL_EXPORT_MAX_CHARACTERS=2000000
PROTOCOL_EXPORT_MAX_BYTES=52428800
```

`original` включает исходную стенограмму; `canonical` использует canonical_text,
если он есть, иначе original_text. PDF встраивает DejaVu Sans. Dockerfile устанавливает
`fonts-dejavu-core`, без проприетарных файлов. Для локального macOS/Windows запуска
задайте пути к установленным DejaVu Sans Regular/Bold; при отсутствии шрифта PDF
возвращает контролируемую ошибку вместо документа с квадратами. DOCX хранит Unicode
и название шрифта; отображение в Word зависит от доступных шрифтов клиента.

Одна генерация/проверка кэша на API-процесс. Остальные запросы получают 429; отмена
HTTP-запроса не освобождает слот до завершения реального render. Копирование в storage
и подготовка скачивания идут блоками 64 KiB. HTTP читает временный файл через
FileResponse, очищает его также при ошибке отправки/отключении клиента. Ошибки storage
проверяются до отправки заголовков.

Это не гарантия постоянного потребления RAM: snapshot, python-docx DOM и ReportLab
flowables находятся в памяти. Лимит 2 млн символов относится к сериализованному
snapshot, 50 MiB — к результату; вход уже должен быть загружен до проверки размера.
Несколько API workers умножают число одновременных генераций. Отдельная очередь
экспорта, общий лимит скачиваний/дисковой квоты и профилирование предельного объёма — TODO.

## Проверки

```sh
cd backend
uv run ruff check .
# Linux с установленными fonts-dejavu-core:
uv run pytest tests/protocols -q
# На macOS/Windows укажите каталог с DejaVuSans.ttf и DejaVuSans-Bold.ttf:
PROTOCOL_TEST_FONT_DIR=/absolute/path/to/dejavu uv run pytest tests/protocols -q
```

`tests/protocols/fixtures.py` — golden RU/KZ/Latin snapshot: resolved/unresolved speaker,
задачи с/без срока, несколько решений и реплик. Проверяются чтение DOCX, PDF header
и извлечённый текст, казахские буквы, неизменность входа, canonical/original, пустые
разделы, перенос длинной строки на несколько страниц, timestamps, безопасные имена,
идемпотентность, восстановление кэша, лимиты, отмена запроса, очистка скачивания,
сопоставление canonical со Speech и HTTP flow с реальным локальным storage/SQLite.
Тесты экспорта не обращаются во внешние API и не требуют GPU.

Дополнительно визуально проверены все страницы двух коротких образцов и длинных
таблиц в PDF и DOCX (DOCX преобразован LibreOffice только для QA).
Миграция `0007` применена в dev PostgreSQL; `alembic check` не выявил расхождений.

## Ограничения интеграции

Экспорт требует сохранённый MeetingAnalysis. Анализ создаётся отдельным `/analyze`
или общей обработкой `/process` при настроенных моделях. Сам GET экспорта upstream
обработку не запускает и возвращает 409 при отсутствии готового анализа.

Текущий прототип не имеет авторизации/проверки владельца встречи; private/no-store
не заменяет access control. Перед внешним развёртыванием нужна общая авторизация API.
Исторические версии artifact сохраняются; retention/сборщик orphan-файлов после
аварийного завершения между storage и DB пока отсутствует. Render timeout/worker
изоляция, фирменный шаблон, электронная подпись и отправка почты не входят в этот этап.
