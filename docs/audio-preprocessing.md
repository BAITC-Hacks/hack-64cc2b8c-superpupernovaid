# Audio preprocessing

Самостоятельный модуль `backend/src/app/audio/`, не привязанный к FastAPI в сервисном
контракте. `await AudioPreprocessor.process(media: MediaAsset) -> NormalizedAudio`.
Синхронная работа с диском, SQLAlchemy и FFmpeg выполняется в отдельном thread;
event loop остаётся доступен. Конвертер заменяем через `AudioConverter`, хранение —
через существующий `FileStorage`. Сейчас используется общий local volume `media-data`.

## Структура

- `config.py`: валидируемый профиль и fingerprint с версией pipeline.
- `converter.py`, `ffmpeg.py`: контракт и реальный FFmpeg-конвертер.
- `service.py`: обработка, контроль параллельности, cache, checksum, cleanup.
- `models.py`, `repository.py`: артефакт и сохранение в PostgreSQL.
- `router.py`, `errors.py`: HTTP и контролируемые ошибки.
- `migrations/versions/0003_normalized_audio.py`: таблица `normalized_audio`.

NormalizedAudio хранит `id`, `source_media_id`, `storage_key`, `sample_rate`,
`channels`, `codec`, `format`, `duration_seconds`, `size_bytes`, `sha256`,
`config_hash`, `created_at`. FK ссылается на исходный MediaAsset; уникальность пары
source/config обеспечивает один опубликованный результат. Размер и SHA256 проверяются
при повторном запросе; отсутствующий/повреждённый артефакт перестраивается.
Временная недоступность storage не удаляет запись cache.

Оригинал неизменяем. Derived key:
`<meeting>/<media>/processed/<config_hash>/<artifact_uuid>/speech_input.wav`.
Одновременная обработка в разных процессах может дублировать вычисления; DB выбирает
единственный результат, лишний файл удаляется. Распределённого lock пока нет.

## Настройки

| Переменная | По умолчанию |
| --- | --- |
| AUDIO_TARGET_SAMPLE_RATE | 16000 |
| AUDIO_TARGET_CHANNELS | 1 |
| AUDIO_TARGET_CODEC | pcm_s16le |
| AUDIO_TARGET_FORMAT | wav |
| AUDIO_FFMPEG_TIMEOUT_SECONDS | 900 |
| AUDIO_FFMPEG_EXECUTABLE | ffmpeg |
| AUDIO_MAX_CONCURRENT_PROCESSES | 1 |
| MEDIA_MAX_CONCURRENT_UPLOADS | 2 |

Также поддерживаются WAV PCM24/PCM32/float32 и FLAC (`flac` + `flac`),
8–192 кГц, 1–2 канала. Несовместимая пара codec/format отклоняется при старте.
Формат следует уточнить после выбора speech-модели. FFmpeg/ffprobe входят в Docker.

Команда без shell (WAV по умолчанию):

```sh
ffmpeg -nostdin -hide_banner -v error -n -xerror \
  -filter_threads 1 -max_alloc 67108864 -threads 1 \
  -protocol_whitelist file -format_whitelist wav,mp3,flac,ogg,mov,matroska,webm \
  -copyts -start_at_zero -i SOURCE \
  -map 0:a:0 -vn -sn -dn -map_metadata -1 -map_chapters -1 \
  -af aresample=16000:async=1:first_pts=0 -ar 16000 -ac 1 \
  -c:a pcm_s16le -f wav -fflags +bitexact -flags:a +bitexact \
  -threads 1 -rf64 auto OUTPUT
```

Выбирается первый audio stream. Сохраняются тишина и временное смещение аудио
относительно видео; VAD, denoise и обрезки нет. Выход проверяется ffprobe до публикации.
Timeout завершает subprocess; stderr записывается на диск, наружу детали команды не выдаются.

## HTTP

Сначала загрузить оригинал через media endpoint, затем:

```sh
curl -X POST \
  http://localhost:8000/api/v1/meetings/MEETING_UUID/media/MEDIA_UUID/preprocess
```

Тело запроса не требуется. Ответ 200 — объект NormalizedAudio, например:

```json
{
  "id": "4d662e9e-3d11-4535-8fe5-787e7951ab00",
  "source_media_id": "66c9f0b3-07d8-446a-8824-655b6611a92a",
  "storage_key": "<meeting>/<media>/processed/<hash>/<artifact>/speech_input.wav",
  "sample_rate": 16000,
  "channels": 1,
  "codec": "pcm_s16le",
  "format": "wav",
  "duration_seconds": 60.0,
  "size_bytes": 1920044,
  "sha256": "<64 hex characters>",
  "config_hash": "<64 hex characters>",
  "created_at": "2026-09-23T00:00:00Z"
}
```

UUID/размеры в примере иллюстративные. Это завершённая обработка в рамках HTTP,
не ответ 202 из очереди. 404 — нет media в этой встрече, 422 — нет аудио/невалидный
вход/ошибка конвертации, 429 — занята мощность, 503 — инфраструктурная ошибка,
504 — timeout. При 429 клиент получает Retry-After: 5 и может повторить позже.
Nginx ждёт до 1000 секунд. meeting_id пока не проверяется через таблицу meetings.

## Память, параллельность и диск

Файлы читаются/сохраняются порциями 1 МиБ, multipart spooling и промежуточные файлы
используют диск. Upload admission limit проверяется до чтения тела и multipart parsing.
Сверхлимитные загрузки не создают неограниченную очередь ожидающих больших файлов.
Для конвертации слот удерживается до завершения thread даже при отмене HTTP coroutine.
Один API-процесс допускает две загрузки и одну обработку одновременно; это разные лимиты.
Backend-контейнер ограничен 1 ГиБ, 2 CPU и 128 PID; FFmpeg использует один thread на
decoder/encoder/filter. `-max_alloc` ограничивает одну аллокацию, не всю память процесса.

Проверка в Docker через nginx + PostgreSQL + реальный FFmpeg: две параллельные
загрузки WAV по 300 МиБ завершились 201; третья получила 429. Два параллельных
preprocess дали 200/429, последующий retry успешно обработан. Повторный запрос
вернул тот же artifact ID, checksum оригиналов и результатов проверены.
По 27 измерениям: пик суммы RSS процессов ≈161 МиБ, anonymous memory ≈91 МиБ,
working set ≈117 МиБ. Cgroup memory.current доходил до 1 ГиБ из-за файлового кеша;
ядро освобождало кеш, OOM kills = 0. Это измерение синтетического PCM, не гарантия
для всех кодеков и повреждённых файлов. Тестовые файлы и DB-записи удалены.

Диск должен вмещать оригиналы, multipart spool и рабочие копии. Во время upload
могут сосуществовать до трёх копий входа; при конвертации — рабочий input и несколько
копий output. PCM может значительно превосходить размер сжатого входа. Ограничение
upload size не является квотой output или диска. Нужны мониторинг свободного места,
retention/квоты и budget длительности перед публичным запуском. Лимиты текущего кода
локальны одному API-процессу; при масштабировании требуется общий admission control.

## Проверки и дальнейшее подключение

```sh
cd backend
uv run ruff check .
uv run pytest
uv run pytest -m integration
```

На этапе реализации: 88 обычных + 16 integration тестов прошли. Проверены ошибки,
cleanup, cache, конфигурация, отмена coroutine, overload до чтения тела, WAV/MP3/M4A/MP4,
FLAC, resampling/downmix, сохранение тишины и offset видео. Integration требует ffmpeg/ffprobe.

Будущий вызывающий сценарий (speech ещё не реализован):

```python
normalized = await audio_preprocessor.process(media_asset)
# Отдельный локальный speech-модуль открывает normalized.storage_key через FileStorage.
# Затем независимо ASR и diarization, после них alignment.
```

ASR, diarization, NeMo, LLM, queue-based audio jobs, live API и provider integrations
не добавлены. Следующие задачи: выбор локальной speech-модели и профиля, disk budgets,
перенос длительной обработки в worker с состояниями/retry, проверка реального S3,
распределённые лимиты при появлении нескольких процессов.
