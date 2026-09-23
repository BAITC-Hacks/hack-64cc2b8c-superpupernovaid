> Дополнение: теперь доступен [NVIDIA cloud provider](nvidia-cloud-speech.md); ниже описаны локальные адаптеры.

# Speech Processing

Граница: `NormalizedAudio → ASR + diarization → alignment → AttributedTranscript`.
Speech возвращает только кто (условная метка), что и когда сказал. MeetingContext,
участники/имена, смысл встречи, LLM, поручения, summary и внешние provider API сюда не входят.

Модуль реализован, адаптеры подготовлены к локальным моделям. Реальное качество RU/KZ/mixed,
расход GPU и совместимость конкретных checkpoints пока не подтверждены: модели не скачивались
и ML inference в текущей среде не запускался. Unit tests используют явно заданные fake adapters,
приложение не подменяет реальную речь фиктивным результатом.

## Структура

```text
backend/src/app/speech/
  models.py             # vendor-neutral Pydantic DTO
  interfaces.py         # два независимых Protocol
  alignment.py          # attribution по временным интервалам
  service.py            # sequential orchestration, admission, persistence
  dependencies.py       # provider selection, startup validation, cached DI
  repository.py         # SQLAlchemy TranscriptRecord, JSON payload
  router.py             # отдельный POST speech
  errors.py             # безопасные коды/сообщения
  adapters/
    audio.py            # storage → private disk file → ASR windows
    base.py             # thread-safe lazy load / executor / close
    asr.py              # NemoSpeechRecognizer, WhisperSpeechRecognizer
    diarization.py      # NemoSpeakerDiarizer, PyannoteSpeakerDiarizer
backend/migrations/versions/0004_speech_transcripts.py
backend/tests/speech/
backend/requirements/speech-{nemo,whisper,pyannote}.txt
```

Изменены `app/config.py`, FastAPI lifespan, регистрация Alembic metadata, pytest markers,
`.env.example`, README и контекст проекта. Существующие медиа/аудио-контракты не менялись.

## Контракты

```python
class SpeechRecognizer(Protocol):
    async def transcribe(self, audio: NormalizedAudio) -> TranscriptionResult: ...

class SpeakerDiarizer(Protocol):
    async def diarize(self, audio: NormalizedAudio) -> DiarizationResult: ...

# Pydantic-модели, здесь показаны только поля:
TranscriptionSegment(start: float, end: float, text: str)
TranscriptionResult(segments: list[TranscriptionSegment])
SpeakerSegment(start: float, end: float, speaker_id: str)
DiarizationResult(segments: list[SpeakerSegment])
AttributedTranscriptSegment(id: str, start: float, end: float, speaker_id: str, text: str)
AttributedTranscript(source_audio_id: UUID, segments: list[AttributedTranscriptSegment])
```

Timestamps конечные, неотрицательные, end > start; output дополнительно проверяется относительно
длительности исходного NormalizedAudio. Сейчас ASR выдаёт сегменты уровня слов, сохраняя текст
модели без нормализации/перевода. Исходное время не сжимается; silence не вырезается.
Native Hypothesis/Segment/Annotation остаются внутри adapters. Ни интерфейсы, ни alignment
не импортируют NeMo, Whisper, Pyannote, Torch или FastAPI.

`SpeakerTranscriptAligner.align(transcription, diarization, *, source_audio_id)` получает
идентичность аудио для результата и генерации ID. Покрытие одного speaker суммируется по
объединённым непересекающимся интервалам. Нужны одновременно: overlap ≥ 0.05 сек,
покрытие ≥ 50% реплики, преимущество над вторым speaker ≥ 10% длительности реплики.
Нет overlap, слишком короткий overlap, ничья/неоднозначная одновременная речь → `UNKNOWN`.
Никаких имён участников; diarization labels канонизируются `SPEAKER_00`, `SPEAKER_01`, …
по первому появлению во всей записи. Boundary touch без положительного overlap не считается.

`id = "seg_" + UUIDv5(source_audio_id, JSON(start,end,text) + duplicate_occurrence)`.
Позиция в полном списке не используется. Повторяющиеся полностью идентичные сегменты различаются
локальным счётчиком совпадений. Вставка постороннего сегмента не меняет ID прежних реплик.
ID сохраняются вместе с JSON в таблице `speech_transcripts`. Уникальный ключ —
`source_audio_id + profile_hash`; повторный POST возвращает сохранённый результат без inference.
Profile включает выбранные providers/models/devices, версию алгоритма и SPEECH_MODEL_REVISION.
При замене весов по тому же пути или обновлении ML runtime увеличьте SPEECH_MODEL_REVISION.
Удаление исходного NormalizedAudio каскадно удаляет связанные transcripts; отдельной политики
архивирования/версий в UI пока нет. Имена speaker могут отличаться при новом inference/model profile.

## Providers и настройки

Provider selection существует только в `speech/dependencies.py`. `SpeechService` получает
готовые recognizer/diarizer; router и alignment не знают выбранного vendor.

Default:

```dotenv
ASR_PROVIDER=nemo
DIARIZATION_PROVIDER=nemo
```

Fallback:

```dotenv
ASR_PROVIDER=whisper
DIARIZATION_PROVIDER=pyannote
```

Hybrid:

```dotenv
ASR_PROVIDER=whisper
DIARIZATION_PROVIDER=nemo
```

Четвёртое сочетание `nemo + pyannote` также поддержано и проверено unit-тестом.
Ни одно сочетание не требует изменения service, aligner, router или downstream-кода.

Все новые переменные:

| Переменная | Default / назначение |
| --- | --- |
| SPEECH_ENABLED | false; явное включение после подготовки моделей |
| ASR_PROVIDER | nemo; nemo / whisper |
| DIARIZATION_PROVIDER | nemo; nemo / pyannote |
| NVIDIA_API_KEY | пусто; SecretStr, исключён из repr и model_dump |
| NEMO_ASR_MODEL | пусто; абсолютный путь к локальному .nemo с word timestamps |
| NEMO_DIARIZATION_MODEL | пусто; локальный streaming Sortformer .nemo |
| NEMO_DEVICE | cuda; cuda / cpu |
| WHISPER_MODEL | large-v3; при включении заменить абсолютным local CTranslate2 directory |
| WHISPER_DEVICE | cuda; cuda / cpu |
| WHISPER_COMPUTE_TYPE | default; также float16 / float32 / int8 |
| PYANNOTE_MODEL | пусто; абсолютный путь к локальному community-1 directory |
| PYANNOTE_DEVICE | cuda; cuda / cpu |
| SPEECH_MAX_DURATION_SECONDS | 14400; верхний предел длительности |
| SPEECH_DIARIZATION_MAX_DECODED_BYTES | 536870912; бюджет одного float32 waveform |
| SPEECH_MODEL_REVISION | 1; версия локальных весов/runtime для cache |

Unknown provider отклоняется Pydantic Settings даже при выключенном speech.
При SPEECH_ENABLED=true lifespan проверяет существование выбранных локальных моделей
и установленных пакетов. CUDA/совместимость checkpoint проверяются при первом lazy load;
ошибка превращается в speech_model_unavailable, а не сырой vendor traceback в HTTP.
После неудачной инициализации требуется исправить конфигурацию и перезапустить процесс.

NVIDIA_API_KEY читается существующим Settings, но **не используется локальным inference**:
NeMo восстанавливается через restore_from(local_path). Поле оставлено для отдельного будущего
provisioning/registry auth. Никаких NVIDIA cloud calls и искусственного требования ключа нет.
PYANNOTE_TOKEN не добавлен: выбранный local-only inference его не требует. Доступ к gated
весам оформляется отдельно при подготовке моделей, credentials не передаются SpeechService.

На startup включаются HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1,
HF_HUB_DISABLE_TELEMETRY=1, PYANNOTE_METRICS_ENABLED=0. Это runtime-настройки приложения,
не параметры для разрешения cloud inference. Для строгого on-prem дополнительно используется
сетевая изоляция среды. Логи приложения содержат IDs, класс адаптера, device, длительность,
число сегментов/speakers и controlled error code; содержимое записи и ключ не логируются.

## Модели и память

Модель создаётся лениво один раз на кешируемый adapter. Lock защищает load и inference.
Весь blocking inference исполняется в thread через asyncio.to_thread; event loop свободен.
Lifespan при завершении ждёт активную обработку, закрывает adapters и очищает DI cache.

Один активный SpeechService job на процесс, остальные получают 429 и Retry-After: 5.
Порядок всегда ASR → diarization → alignment; parallel inference пока не включён.
При отмене HTTP coroutine внутренняя task shielded, слот освобождается только после окончания
работы. Не создаются новые Celery/Redis tasks. Несколько Uvicorn workers/реплик умножат лимит:
для GPU сейчас следует запускать **один процесс**.

Модели кешируются, поэтому их веса могут одновременно оставаться в VRAM даже при sequential
inference. Нужен запас под обе модели и activation buffers; один concurrent job не гарантирует,
что выбранная пара помещается на любом GPU. Автоматического CPU offload пока нет.

Audio передаётся по storage_key. Файл копируется в приватный temporary directory блоками
1 МиБ с проверкой размера/SHA256. Требуется WAV PCM16 mono 16000 Hz (текущий default audio
preprocessing); другой профиль → контролируемая ошибка, а не неявная смена timebase.

ASR получает окна: 25 секунд основной части + до 2.5 секунды контекста с каждой стороны.
На диске переиспользуется один WAV-window, в Python читается максимум секунда PCM за раз.
Native library декодирует только окно до 30 секунд. Word timestamps сдвигаются на offset;
слово целиком относится к окну, содержащему его midpoint, а не обрезается по границе.
Перекрывающиеся дубликаты с одинаковым текстом удаляются. Точность слов на границах требует
реальной проверки выбранных моделей; алгоритм не является гарантией безошибочного ASR.

Diarization получает запись целиком, без независимых chunk-speaker IDs.
NeMo adapter поддерживает **streaming Sortformer** с native состоянием speakers на запись;
нестриминговый checkpoint отклоняется. Лимит speakers определяется checkpoint (например,
4spk не подходит для доказанного распознавания большего числа участников).
Pyannote adapter использует полный local community-1 pipeline и обычную speaker_diarization,
сохраняющую overlap, а не exclusive-версию.

Native diarizers могут загрузить весь waveform и промежуточные признаки в RAM/VRAM.
Это не O(1)-memory diarization. До ASR/diarization проверяются длительность и бюджет waveform:
512 МиБ float32 при 16 кГц ≈ 2 ч 20 мин; фактический допустимый предел — минимум этого
значения и SPEECH_MAX_DURATION_SECONDS. Большая запись отклоняется до загрузки моделей.
Для более длинных встреч лимиты повышают только после benchmark RAM/VRAM выбранного pipeline.
Объём текста/списка сегментов также растёт с длительностью. Native feature extraction и
clustering требуют дополнительной памяти сверх waveform budget; диск — места под private copy.

## Установка и запуск

Базовый Docker/dev-образ намеренно не получает Torch/NeMo: быстрый workflow сохранён.
Текущий лимит API-контейнера 1 ГиБ предназначен для ingestion/preprocessing, не ML моделей.
Для real inference подготовьте отдельное Python-окружение на целевой Linux/CUDA машине
или отдельный ML-образ того же монолитного приложения с подходящими RAM/VRAM лимитами,
GPU passthrough и read-only mount модели. На macOS CUDA недоступна; CPU smoke test возможен
для совместимых моделей. Готового/проверенного GPU Docker-образа этот этап не поставляет.

В отдельном Python 3.12 environment, из backend/:

```sh
uv venv .venv-speech --python 3.12
uv pip install --python .venv-speech/bin/python -e . pytest httpx
# Выберите только нужные providers; Torch/CUDA установите под целевую машину.
uv pip install --python .venv-speech/bin/python -r requirements/speech-nemo.txt
# Для fallback:
uv pip install --python .venv-speech/bin/python \
  -r requirements/speech-whisper.txt -r requirements/speech-pyannote.txt
```

Прямые версии закреплены (NeMo 2.7.0, faster-whisper 1.2.1, pyannote.audio 4.0.4),
но полный CUDA/transitive lock должен быть зафиксирован после проверки на целевой машине.
Не запускайте uv sync поверх ML-окружения: базовый uv.lock не включает эти optional пакеты.
Не используйте базовый API-контейнер с лимитом 1 ГиБ для реального inference.

Перед startup положите локальные веса, настройте выбранные пути и SPEECH_ENABLED=true.
Пример local NeMo:

```dotenv
SPEECH_ENABLED=true
ASR_PROVIDER=nemo
DIARIZATION_PROVIDER=nemo
NEMO_ASR_MODEL=/models/asr/model.nemo
NEMO_DIARIZATION_MODEL=/models/diar/streaming-sortformer.nemo
NEMO_DEVICE=cuda
```

Для локального API используйте PostgreSQL localhost:5332 из make infra, задав DATABASE_URL
в окружении. .env читается из корня проекта; существующий файл не перезаписывается.

```sh
# Из backend/, после настройки окружения:
.venv-speech/bin/alembic upgrade head
.venv-speech/bin/uvicorn app.entrypoints.api:app --host 0.0.0.0 --port 8000
```

Перед этим остановите Docker backend, если он занимает порт 8000. API без --reload и
без нескольких --workers сохраняет один экземпляр моделей между запросами.

## HTTP

```sh
curl -X POST \
  http://localhost:8000/api/v1/meetings/MEETING_UUID/media/MEDIA_UUID/speech
```

Body не нужен. Маршрут проверяет meeting/media и ищет NormalizedAudio текущего
профиля preprocessing; сам preprocessing не запускается. 404 — неизвестное media,
409 — нужен preprocessing, 422 — неподдержанное/повреждённое аудио или невалидный output,
429 — capacity busy, 503 — выключено/модель/хранилище/БД недоступны.

Иллюстративный ответ 200 (ID в реальности детерминированный UUIDv5):

```json
{
  "source_audio_id": "0ea7b5c2-441e-4857-aecd-681dfeae16f1",
  "segments": [
    {
      "id": "seg_d4aa4869cc795726962e015817d9f244",
      "start": 125.4,
      "end": 126.1,
      "speaker_id": "SPEAKER_01",
      "text": "Данияр,"
    }
  ]
}
```

Это синхронный по HTTP результат, не queued job. Для многочасового inference клиенту
может понадобиться больший timeout; nginx сейчас ждёт 1000 сек. При disconnect работа
продолжается и сохраняет результат: retry после завершения возвращает cache. При аварийной
остановке процесса незавершённый job не восстанавливается, следующий запрос начинает заново.
Отдельного GET/status/cancel endpoint и durable queue пока нет.

## Проверки

```sh
cd backend
uv run pytest
uv run pytest -m integration
# В provisioned ML environment; короткий реальный WAV PCM16 mono16k:
RUN_SPEECH_INTEGRATION=1 SPEECH_TEST_AUDIO=/fixtures/consented-speech.wav \
  NEMO_ASR_MODEL=/models/asr/model.nemo \
  NEMO_DIARIZATION_MODEL=/models/diar/streaming-sortformer.nemo \
  .venv-speech/bin/pytest -m 'integration and gpu and nemo'
# Аналогично marks whisper / pyannote, соответствующие *_MODEL variables.
# SPEECH_TEST_DEVICE=cpu позволяет отдельно проверить совместимый CPU runtime.
```

Проверка этого этапа: **131 unit/API passed**, **16 media/audio integration passed**,
**4 real-model tests skipped**. Ruff и diff check прошли. Миграция 0004 применена
к PostgreSQL; alembic check не выявил расхождений. SQLite upgrade/downgrade/upgrade
также проверены. Swagger содержит Speech route, обычный dev-стек работает.

GPU-тесты не читают секреты и не скачивают модели; нужны RUN_SPEECH_INTEGRATION=1,
локальный sample и явно экспортированные пути. Даже при `pytest -m integration` без opt-in
они пропускаются. Обычные tests работают без ML packages/GPU/API keys.

Проверяются: все provider combinations, startup config, secret repr/dump/log/HTTP,
alignment exact/partial/boundary/short/no overlap/multiple speakers/empty results,
stable IDs при вставках, persistence/cache, DTO mapping всех четырёх adapters,
lazy load, bounded ASR windows/global timestamps, audio integrity/resource budget,
HTTP scoping, cancellation, sequential execution и controlled errors.

## Оставшаяся проверка на реальных моделях

- Выбор checkpoint с поддержкой RU/KZ/mixed и настоящими word timestamps; WER/CER.
- Качество diarization/DER, overlap, количество говорящих, границы ASR windows.
- Точные совместимые Torch/CUDA зависимости, offline smoke test всех нужных combinations.
- RSS/VRAM и время на многочасовой записи; только после этого повышать limits.
- Настройка ML deployment и request timeouts; durable jobs при необходимости отдельным этапом.

Основные API сверены с первичными источниками:
[NeMo 2.7 transcription](https://github.com/NVIDIA-NeMo/NeMo/blob/v2.7.0/nemo/collections/asr/parts/mixins/transcription.py),
[NeMo 2.7 Sortformer](https://github.com/NVIDIA-NeMo/NeMo/blob/v2.7.0/nemo/collections/asr/models/sortformer_diar_models.py),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[local community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).
