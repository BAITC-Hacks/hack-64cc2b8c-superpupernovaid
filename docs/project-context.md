# Согласованный контекст проекта

AI-система автопротоколирования совещаний: русский, казахский и смешанная речь,
разделение говорящих, поручения с ответственными и сроками, summary, экспорт PDF/DOCX.
Документ фиксирует направление развития; не означает, что все перечисленные функции реализованы.

## Архитектура и границы

FastAPI modular monolith. Функциональные модули, dependency inversion только на
заменяемых границах. Существующий код сохраняется; новые слои, пустые провайдеры,
микросервисы и интерфейсы для каждого класса не добавляются ради шаблона.

```text
Recorded sources → Media ingestion → MediaAsset
Live sources     → future AudioStream / AudioChunk
                                      ↓
                             Audio Processing
                                      ↓
                              NormalizedAudio
                               ↙           ↘
                             ASR       Diarization
                               ↘           ↙
                                  Alignment
                                      ↓
                            AttributedTranscript
                                      ↓
                           Meeting Intelligence
                                      ↓
                          StructuredMeetingResult
                                      ↓
                              Protocol JSON
                               ↙          ↘
                             PDF          DOCX
```

- **Media** получает оригинал, проверяет контейнер/streams, сохраняет и регистрирует asset.
  Не выполняет extraction, resampling, speech/LLM и не зависит от FastAPI UploadFile за пределами router.
- **Audio** позже извлечёт и подготовит аудио; параметры canonical audio выбираются
  под фактическую speech-модель. FFmpeg-конвертация относится к этому модулю.
- **Speech** разделит ASR, diarization и alignment. NeMo — кандидат реализации,
  а не обязательная архитектура. Замена на другие локальные реализации не должна менять контракт.
- **Intelligence** получает атрибутированный transcript и возвращает поручения,
  решения и summary со ссылками на исходные сегменты; не занимается распознаванием речи.
- **Protocols** формирует PDF/DOCX обычным кодом из структурированных данных.
- **Напоминания** выполняет обычный scheduler/worker, а не LLM.

## Приватность и модели

ТЗ требует on-premise и запрещает передачу аудио/текста во внешние cloud API.
Speech и LLM inference основного решения должны поддерживать локальный/закрытый контур.
Существующий `/api/v1/jobs` — отдельный scaffold/demo, не pipeline записей совещаний.
Его cloud OpenAI adapter нельзя использовать для реальных записей/транскриптов этого кейса.
OpenAI Agents SDK может рассматриваться как orchestration framework только с соблюдением
этих требований к inference. Конкретный локальный provider ещё не выбран и не подключён.

Важные будущие проверки:

- ASR нужно отдельно оценить на RU, KZ и code-switching; поддержка двух языков
  не является подтверждением качества смешанной речи. План: 20–50 validation-реплик.
- Diarization выдаёт условные speaker IDs. Сопоставление с именами — отдельная задача;
  на MVP возможно ручное сопоставление секретарём. Биометрическая идентификация не входит в стартовый scope.
- GPU-модели загружаются один раз на lifecycle inference worker, не на HTTP request.
- ASR и diarization независимы; alignment совмещает их временные интервалы.

## Входные источники

Сейчас работает только file upload. Учёт будущих Zoom/Teams/Meet не означает наличие
API-интеграций: credentials, tenant access и development apps пока отсутствуют.
Пустых/fake `ZoomSource` или `TeamsSource` нет.

**Записи** из будущих сервисов смогут создавать тот же MediaAsset через ingestion.
**Live** потребует отдельного контракта AudioStream / AsyncIterator[AudioChunk],
с временными метками и опциональной идентичностью участника, когда её предоставляет источник.
Live-поток не нужно принудительно материализовывать в завершённый MediaAsset.
Streaming API, buffering, reconnect и backpressure пока не реализованы.

OBS — внешний инструмент записи; его MKV/MP4/WAV идёт через обычный upload.
OBS-интеграции и собственного capture client сейчас нет.

## Текущее состояние и порядок развития

Реализованы общая конфигурация, PostgreSQL/SQLAlchemy/Alembic, Celery/Redis,
React scaffold, независимый demo agents job и **media ingestion**.
Meeting lifecycle/table, audio processing, speech, alignment, intelligence, protocol export,
напоминания и provider/live integrations пока не реализованы.

`meeting_id` media endpoint — UUID-ссылка без проверки существования встречи:
таблица meetings и её API появятся отдельным этапом.

Последовательность следующих отдельных задач:

1. Audio Processing → NormalizedAudio.
2. Локальный ASR и проверка качества RU/KZ/mixed.
3. Diarization и alignment → AttributedTranscript.
4. Intelligence с локальным inference → StructuredMeetingResult.
5. Protocol JSON/PDF/DOCX, затем поручения и напоминания.
6. Provider integrations/live после получения доступа и отдельного исследования.

Ни один будущий этап не запускается внутри текущего upload endpoint.
Подробности реализованного этапа: [media-ingestion.md](media-ingestion.md).
