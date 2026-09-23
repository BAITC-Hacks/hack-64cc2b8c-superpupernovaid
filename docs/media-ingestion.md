# Media ingestion

Самостоятельный backend-модуль приёма оригинальных записей совещаний.
Результат — сохранённый `MediaAsset`; никакая обработка речи не запускается.
Модуль работает локально и не отправляет файлы в существующий demo/AI job pipeline.
ТЗ HackAlem требует закрытого контура и запрещает передачу аудио/текста во внешние
облачные API; будущие speech/analysis-модули должны учитывать это ограничение.

## Запуск

```sh
docker compose up --build -d
```

Образ backend содержит ffprobe (пакет FFmpeg). Миграция `0002` добавляет таблицу
`media_assets`. Оригиналы хранятся в named volume `media-data`, общем для backend и worker.
`docker compose down` сохраняет данные; удаление volumes удалит и записи.

Для локальной разработки установите FFmpeg (`brew install ffmpeg` на macOS,
`apt-get install ffmpeg` на Debian/Ubuntu) и выполните из `backend/`:

```sh
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn app.entrypoints.api:app --reload
```

Настройте `DATABASE_URL` на фактический порт вашей БД. В текущем Compose PostgreSQL
опубликован на `localhost:5332`, а внутри контейнеров используется `postgres:5432`.

## Контракт

`POST /api/v1/meetings/{meeting_id}/media`

- `meeting_id`: UUID. Таблицы meetings пока нет; это внешняя ссылка, существование встречи
  пока не проверяется. Когда появится модуль meetings, добавьте проверку/внешний ключ.
- `Content-Type: multipart/form-data`.
- Ровно один файл в поле `file`. Настройки ASR, модели, дополнительные поля и второй файл не принимаются.
- Ответ: **201 Created**, полный `MediaAsset`.

```sh
curl --fail-with-body \
  -F 'file=@/absolute/path/meeting.mp4' \
  http://localhost:8000/api/v1/meetings/11111111-1111-4111-8111-111111111111/media
```

Пример ответа (значения ID/метаданных зависят от файла):

```json
{
  "id": "22222222-2222-4222-8222-222222222222",
  "meeting_id": "11111111-1111-4111-8111-111111111111",
  "original_filename": "meeting.mp4",
  "media_type": "video",
  "mime_type": "video/mp4",
  "storage_key": "11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/source",
  "size_bytes": 12345678,
  "duration_seconds": 125.4,
  "container": "mov",
  "audio_codec": "aac",
  "video_codec": "h264",
  "status": "uploaded",
  "created_at": "2026-09-23T10:00:00Z"
}
```

`GET /api/v1/meetings/{meeting_id}/media/{media_id}` возвращает ту же запись после
перезапуска приложения. Несуществующий asset или другая встреча — **404**.
Это получение метаданных, не публичная ссылка на скачивание файла.
Swagger: http://localhost:8000/docs (раздел Media).

| Ошибка | HTTP | `detail.code` |
| --- | --- | --- |
| Превышен лимит файла/тела запроса | 413 | `media_too_large` |
| Неподдерживаемое семейство контейнеров | 415 | `unsupported_media` |
| Пустой/нераспознанный файл, нет usable audio/video | 422 | `invalid_media` |
| Хранилище недоступно | 503 | `media_storage_unavailable` |
| ffprobe отсутствует или не уложился в timeout | 503 | `media_probe_unavailable` |
| Ошибка регистрации в БД | 503 | `media_database_unavailable` |

Ошибки модуля: `{"detail":{"code":"...","message":"..."}}`, без stderr ffprobe,
секретов БД и локальных путей. FastAPI-ошибки UUID/отсутствующего поля имеют стандартный
формат 422; некорректный multipart/лишние поля — 400. На уровне nginx слишком большое
тело может быть отклонено собственным ответом 413 ещё до API.

## Модель и хранение

`MediaAsset` — SQLAlchemy-модель в общей БД. Отдельных DTO/entity-копий для каждого
архитектурного слоя нет; Pydantic `MediaAssetResponse` задаёт HTTP-контракт.

Обязательные данные: UUID media, UUID встречи, имя для отображения, тип, статус,
непрозрачный ключ хранилища и размер. Дополнительно сохраняются длительность,
контейнер, MIME (если однозначно известен), аудио/видеокодек и время создания.
Есть enum-значения `uploaded` и `invalid`; сейчас отклонённые загрузки удаляются,
а не сохраняются как invalid-строки. Расширенные processing-статусы ещё не введены.

Локальный путь:

```text
<MEDIA_UPLOAD_DIR>/<meeting UUID>/<media UUID>/source
```

Расширение намеренно не добавляется: содержимое определяет ffprobe, не суффикс.
`original_filename` очищается от компонентов пути и управляющих символов и служит
только для отображения. UUID и exclusive-create защищают от коллизий и перезаписи.
`storage_key` не содержит абсолютного пути и остаётся тем же при переносе в S3.

Запись выполняется чанками по 1 MiB с подсчётом реального размера. Multipart parser
использует spooled file: большой upload уходит на диск, а не целиком в RAM.
Дополнительный лимит HTTP-тела действует во время чтения, включая запросы без
Content-Length; допустимый multipart overhead — 1 MiB. Разрешён один file part.
nginx отключает дополнительную буферизацию request body.

ffprobe получает приватную временную копию из `storage.open()`, записанную чанками:
это поддерживает и будущие non-seekable S3 streams. Для текущего local storage во
время запроса возможны **три дисковые копии**: multipart spool, original и inspection copy.
Резервируйте место под параллельные загрузки; временные копии удаляются после запроса.
RAM ограничена размером буферов, а не длительностью записи. Синхронная файловая работа
и ffprobe выполняются в FastAPI threadpool, не блокируя event loop.

При ошибке записи storage удаляет частичный объект. При ошибке inspection или БД
сервис удаляет сохранённый оригинал. Ошибки cleanup логируются. БД и filesystem не
образуют общую транзакцию: аварийное завершение процесса может оставить orphan-файл;
периодическая сверка/очистка — будущая эксплуатационная задача.

## Настройки

```dotenv
MEDIA_MAX_FILE_SIZE_BYTES=5368709120
MEDIA_ALLOWED_FORMATS=["wav","mp3","flac","ogg","mov","matroska"]
MEDIA_UPLOAD_DIR=./data/media
MEDIA_FFPROBE_TIMEOUT_SECONDS=15
MEDIA_FFPROBE_EXECUTABLE=ffprobe
```

Относительный `MEDIA_UPLOAD_DIR` отсчитывается от корня репозитория. В Compose он
переопределён в `/data/media`, путь volume. При изменении лимита размера согласуйте
`client_max_body_size` в `frontend/nginx.conf`: сейчас 5 GiB + 1 MiB overhead.
`MEDIA_FFPROBE_TIMEOUT_SECONDS` ограничивает процесс inspection, не время передачи файла.

В allowlist используются **семейства демультиплексоров ffprobe**:

| Настройка | Распространённые файлы |
| --- | --- |
| `wav` | WAV |
| `mp3` | MP3 |
| `flac` | FLAC |
| `ogg` | Ogg/Opus/Vorbis |
| `mov` | MOV/MP4/M4A (семейство QuickTime/ISO BMFF, также 3GP) |
| `matroska` | MKV/WebM |

FFprobe не всегда разделяет MOV/MP4 или MKV/WebM однозначно. `container` сохраняет
семейство, а `mime_type` может быть null; клиентский MIME не подставляется как факт.
`media_type` определяется по streams: полноценный video stream → video, иначе audio.
Обложка альбома (`attached_pic`) не превращает MP3 в видео. Видео без звука допустимо;
будущий AudioProcessor должен отдельно обработать отсутствие audio stream.
ffprobe использует allowlist демультиплексоров, только локальный file protocol,
ограниченный объём метаданных и timeout. Это inspection, не полная проверка декодируемости
каждого кадра многочасовой записи.

## Структура и принятые решения

```text
app/media/
  models.py       # MediaAsset, enums, response schema
  router.py       # multipart transport, request limit, HTTP error mapping
  service.py      # ingestion orchestration and failure cleanup
  repository.py   # SQLAlchemy operations using the existing Base/engine
  storage.py      # LocalMediaStorage
  probe.py        # replaceable MediaProbe + ffprobe implementation
  validation.py   # bounded chunks and safe display filename
  errors.py       # controlled module errors
```

Зависимости собираются существующим `bootstrap.py`: `get_media_storage()` и
`get_media_service()` кешируют stateless adapters/service; DB sessions открываются
на операцию. Нового DI framework и новых domain/application/infrastructure слоёв нет.
Существующий `FileStorage` расширен до `save(chunks) / open / delete`.
Сервис не импортирует FastAPI и не знает о локальных путях. Обёртка ffprobe подменяется
в unit tests. Репозиторий конкретный: ещё одна абстракция над SQLAlchemy здесь не нужна.

`FileMediaSource` пока не создан: у одного источника он дублировал бы передачу
`filename + BinaryIO`. Будущие Teams/Zoom/Meet-адаптеры смогут вызывать тот же
`MediaService.ingest()` с потоком готовой записи. OBS-файл проходит обычный upload.
Для live предусмотрен другой будущий контракт: AudioStream / AsyncIterator[AudioChunk].
Непрерывный live-поток не требуется превращать в завершённый MediaAsset.
Полный согласованный контекст: [project-context.md](project-context.md).

## Замена на MinIO

Существующий `S3FileStorage` адаптирован к тому же потоковому `FileStorage` и покрыт
unit test с mock клиента. Live S3-интеграция не включается автоматически.
В `bootstrap.py` замените тело провайдера, не меняя `MediaService`:

```python
@lru_cache
def get_media_storage() -> FileStorage:
    return S3FileStorage(get_settings())  # import from app.infrastructure.storage
```

Запустите профиль `storage`, создайте bucket из `S3_BUCKET`, настройте endpoint и
credentials по основному README. При работе с реальными данными соблюдайте требование
ТЗ о закрытом контуре. Перед переключением перенесите существующие original-объекты
с теми же ключами; все записи сейчас используют один configured storage backend.
S3-адаптер сначала записывает bounded chunks во временный файл на диске, затем
использует boto3 managed multipart upload; `open()` возвращает поток, `delete()` удаляет объект.

## Следующий модуль

Позже отдельный job/workflow загрузит `MediaAsset` из БД и передаст его
`AudioProcessor`, который получит оригинал через `FileStorage.open(asset.storage_key)`.
Нормализованное аудио будет отдельным артефактом, исходная запись останется неизменной.
AudioProcessor не будет получать UploadFile или знать об HTTP/OBS/Zoom.
В текущем upload endpoint нет extraction, resampling, ASR, diarization, LLM или постановки
speech-задачи в очередь. Существующий agents demo остаётся независимым.

## Тесты

Из `backend/`:

```sh
uv run ruff check .
uv run pytest                      # unit/API, ffprobe заменён, GPU/сеть не нужны
uv run pytest -m integration       # отдельно реальные ffprobe + ffmpeg
```

Integration tests генерируют короткие синтетические аудио/видео локально, загружают их
через HTTP-контракт и проверяют неизменность сохранённого оригинала. Конвертации в
production endpoint нет. Требуются энкодеры AAC, MP3, Opus, FLAC, MPEG4 и VP9 в FFmpeg.
Unit tests покрывают лимиты, ошибки, cleanup, путь, подмену storage, ffprobe timeout,
chunked HTTP без Content-Length, закрытие multipart temp-файла и HTTP-коды.

Справка: [FastAPI UploadFile](https://fastapi.tiangolo.com/tutorial/request-files/),
[ffprobe](https://ffmpeg.org/ffprobe.html).
