# Transcript Canonicalization

Отдельный этап после Speech: `AttributedTranscript → CanonicalTranscript`.
Преобразует Russian/Kazakh/mixed speech в настроенный язык, по умолчанию `ru`.
Не выполняет summary, task extraction, назначение ответственных, вычисление дат,
интерпретацию намерений, сопоставление speakers с людьми или MeetingContext.

По новому прямому требованию пользователя здесь предусмотрен **OpenAI API**. Это
опциональный cloud-этап, отличающийся от исходного on-prem ТЗ: его нельзя считать
on-prem решением. По умолчанию выключен; локальный Speech остаётся независимым.
Реальные транскрипты при реализации не отправлялись во внешний API.

## Файлы и контракт

```text
app/canonicalization/
  models.py        # публичный CanonicalTranscript и внутренний structured batch output
  batching.py      # contiguous target batches и отдельный read-only context
  agent.py         # один OpenAITranscriptCanonicalizer, prompt, bounded retry
  service.py       # validation, metadata reconstruction, bounded workers, persistence
  repository.py    # отдельная canonical_transcripts table
  dependencies.py  # cached DI, startup validation, profile hash
  router.py        # отдельный HTTP endpoint
  errors.py        # controlled errors
migrations/versions/0005_canonical_transcripts.py
tests/canonicalization/
```

Новых dependencies нет: используется установленный Agents SDK/OpenAI client.
Metadata источника не меняется. Публичные модели:

```python
CanonicalTranscriptSegment(
    id: str, start: float, end: float, speaker_id: str,
    original_text: str, canonical_text: str,
    canonicalization_uncertain: bool = False,
)
CanonicalTranscript(
    source_audio_id: UUID, canonical_language: str,
    segments: list[CanonicalTranscriptSegment],
)
```

Internal structured output:

```python
class CanonicalizedSegmentOutput(BaseModel):
    id: str
    canonical_text: str
    uncertain: bool

class CanonicalizationBatchResult(BaseModel):
    segments: list[CanonicalizedSegmentOutput]
```

Модели запрещают extra fields, пустой/пробельный canonical_text отклоняется.
LLM не возвращает timestamps, speaker_id или original_text. Service копирует их из
snapshot исходного AttributedTranscript. IDs только сверяются с входом, новые не генерируются.
Исходный транскрипт не перезаписывается; original_text сохраняется точно, включая пробелы/Unicode.

## Agent и prompt

```python
Agent(
    name="TranscriptCanonicalizerAgent",
    instructions=INSTRUCTIONS,
    model=OpenAIResponsesModel(model=settings.transcript_canonicalization_model,
                              openai_client=client),
    output_type=CanonicalizationBatchResult,
    model_settings=ModelSettings(store=False, max_tokens=configured_limit),
)
await Runner.run(agent, batch_json, max_turns=1,
                 run_config=RunConfig(tracing_disabled=True,
                                      trace_include_sensitive_data=False))
```

Один agent без tools, handoffs, manager и разговоров между агентами.
Полный prompt находится в `app/canonicalization/agent.py:INSTRUCTIONS`.
Он предписывает переводить только необходимое, сохранять модальность, отрицания,
имена/термины/числа/версии/URLs/IDs и относительные сроки, не исправлять ASR по догадке,
не объединять/разбивать сегменты, не делать выводы и отмечать неоднозначность.
Текст transcript обозначен как недоверенные данные: инструкции внутри реплик нужно
переводить как содержание, а не исполнять. Поле canonical_language приходит из settings.
Русские примеры prompt объясняют default, но target language не зашит в service.

Structured output и программная validation защищают структуру; они **не доказывают**,
что LLM не изменил смысл. Semantic quality требует отдельной проверки на реальной модели.
store=false отключает сохранение Response как объекта API, но не является обещанием
zero data retention. Tracing SDK выключен; API всё равно получает target/context text.

## Batching, concurrency, retry

Default: до **50 target segments** и до **12 000 UTF-8 bytes JSON payload**, включая
IDs, язык и context. Это небольшой начальный batch, а не попытка вместить двухчасовую
встречу в один запрос. Bytes — ограничитель размера, не точный tokenizer/context-window budget.
Системный prompt и generated output требуют дополнительного места в выбранной модели.

Следующий batch получает до двух предыдущих сегментов только в
`context_only_do_not_output`; target segments передаются отдельно. При нехватке места
сначала сокращается context. Сегмент не режется: если даже один target не помещается,
весь input отклоняется до первого API call. Планирование не теряет и не дублирует targets.

После каждого ответа проверяются count, точное множество ожидаемых IDs, неизвестные,
пропущенные и повторные IDs. Порядок восстанавливается по источнику. После сборки
проверяются source_audio_id, язык, порядок, IDs, timestamps, speakers и exact original_text.
Проверка выполняется также для cached результата. Если один batch невалиден/упал,
остальные workers отменяются; частичный transcript не сохраняется и не выдаётся как успех.
Уже выполненные запросы при ошибке могли стоить денег; resumable batches пока нет.

Один активный transcript job на process-wide cached service; остальные получают 429.
Внутри job фиксированный пул до CANONICALIZATION_MAX_CONCURRENCY workers (default 3),
а не task на каждый сегмент. HTTP disconnect не запускает дубликат: shielded job
продолжает работу/сохранение, слот удерживается до завершения. Shutdown ждёт job и
закрывает AsyncOpenAI client. Несколько процессов умножают лимит; глобального lock нет.

SDK retries выключены (`max_retries=0`). Adapter делает до трёх попыток:
429, timeout, connection error, 5xx; exponential backoff с небольшим jitter и максимумом
около 10 сек. Auth/400/невалидная структура не retry. Timeout ограничивает каждую попытку.
Exception chaining сохраняется, но HTTP и application logs содержат только controlled codes,
IDs/counts/durations. Transcript, key и headers не логируются приложением.

## Persistence

Таблица `canonical_transcripts` отдельна от `speech_transcripts`. JSON хранит production DTO.
Cache key: source_audio_id + hash полного исходного DTO + profile hash.
Profile включает model, language, prompt/version, batching/context и output limit.
Изменение текста, metadata, языка или модели не возвращает старый cache.
Секрет и retry count не входят в cache key. При race DB выбирает один сохранённый результат;
межпроцессные повторные API calls этим не предотвращаются. Удаление NormalizedAudio
каскадно удаляет связанные canonical artifacts.

## Настройки

Используется существующий `OPENAI_API_KEY`, второй ключ не добавлен.

```dotenv
TRANSCRIPT_CANONICALIZATION_ENABLED=false
TRANSCRIPT_CANONICALIZATION_MODEL=
TRANSCRIPT_CANONICAL_LANGUAGE=ru
CANONICALIZATION_BATCH_MAX_SEGMENTS=50
CANONICALIZATION_BATCH_MAX_BYTES=12000
CANONICALIZATION_CONTEXT_SEGMENTS=2
CANONICALIZATION_MAX_CONCURRENCY=3
CANONICALIZATION_REQUEST_TIMEOUT_SECONDS=60
CANONICALIZATION_MAX_ATTEMPTS=3
CANONICALIZATION_RETRY_BASE_SECONDS=0.5
CANONICALIZATION_MAX_OUTPUT_TOKENS=4096
```

Чтобы включить, укажите модель с поддержкой structured output, OPENAI_API_KEY и
TRANSCRIPT_CANONICALIZATION_ENABLED=true. Model name выбирается конфигурацией, без
встроенного default. Startup проверяет обязательные настройки без API call.
AI_MODE существующего demo job не управляет canonicalization. Изменения .env требуют
пересоздания backend (`make dev`); менять service/router не нужно.

## Endpoint и пример

```sh
curl -X POST \
  http://localhost:8000/api/v1/meetings/MEETING_UUID/media/MEDIA_UUID/canonicalize
```

Body не требуется. Endpoint получает уже сохранённый Speech result текущего
preprocessing/speech profile. Не запускает автоматически preprocessing или speech.
404 — нет media; 409 — нет текущего audio/speech artifact; 422 — слишком большой
сегмент; 429 — job занят; 502 — invalid model output; 503 — disabled/config/provider/storage.
Swagger показывает production response schema.

Сквозной пример **из fake unit fixture**, не результат реального OpenAI вызова:

```json
{
  "source_audio_id": "0ea7b5c2-441e-4857-aecd-681dfeae16f1",
  "canonical_language": "ru",
  "segments": [{
    "id": "seg_0042",
    "start": 125.4,
    "end": 131.8,
    "speaker_id": "SPEAKER_01",
    "original_text": "Данияр, осы задачаны пятницаға дейін закройте.",
    "canonical_text": "Данияр, закройте эту задачу до пятницы.",
    "canonicalization_uncertain": false
  }]
}
```

Input имел те же source_audio_id/id/start/end/speaker_id и text, равный original_text.
Пример сохранения относительного срока: «Ертең до обеда жіберіңіз.» →
«Отправьте завтра до обеда.», без вычисления даты/12:00.

## Тесты и ограничения

```sh
cd backend
uv run pytest
uv run pytest -m integration
# Только явный opt-in: синтетическая фраза, оплачиваемый API call.
RUN_CANONICALIZATION_OPENAI_TESTS=1 \
  TRANSCRIPT_CANONICALIZATION_MODEL=YOUR_CONFIGURED_MODEL \
  uv run pytest -m 'integration and openai'
# OPENAI_API_KEY должен быть заранее экспортирован; не печатайте ключ в командной истории.
```

Unit tests используют FakeCanonicalizer/подмену Runner.run: mixed/relative/technical/no-task
fixtures, immutable metadata, порядок, UTF-8 byte budget/context, unknown/missing/duplicate IDs,
empty transcript, late oversized segment before calls, partial failure, concurrency/cancellation,
cache invalidation, SDK schema/tools/tracing/store configuration, retries и секреты в logs/HTTP.
Live OpenAI test без opt-in пропускается; реальная semantic quality пока не подтверждена.

Speech сейчас выдаёт word-level segments. Строгое соответствие 1:1 ограничивает плавность
перевода: предложение нельзя свободно перестроить с переносом слов между IDs. Context помогает,
но качество на этой гранулярности нужно оценить отдельно. Нельзя молча объединять Speech IDs.
При timeout клиента job может продолжаться; resumable processing, versioned UI и real-model
semantic evaluation остаются отдельными задачами. Scope заканчивается на CanonicalTranscript.

API wiring сверено с [OpenAI Agent definitions](https://developers.openai.com/api/docs/guides/agents/define-agents)
и [tracing controls](https://developers.openai.com/api/docs/guides/agents/integrations-observability),
а также с установленной версией Python SDK.
