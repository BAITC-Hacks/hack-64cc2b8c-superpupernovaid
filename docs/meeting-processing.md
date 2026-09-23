# Общая обработка встречи

`MeetingProcessingService` запускает существующие сервисы в Celery после загрузки записи.
Это Python workflow; очередность этапов не выбирает LLM. Агентный модуль подключён
через `app.intelligence.dependencies.get_analysis_coordinator()`.

```text
POST /meetings → POST /meetings/{id}/media
                          ↓
           POST /meetings/{id}/process → 202 + run ID
                          ↓ Celery
               preprocess → speech/diarization
                          ↓
                     canonicalize
                          ↓
               speaker resolution artifact
                          ↓
            extraction → resolver → summary → review
                          ↓
                  сохранённый анализ/Tasks
                          ↓
             MeetingProtocol → DOCX + PDF → ready
```

## API

Все пути имеют префикс `/api/v1`.

```sh
curl --fail-with-body -X POST "http://localhost:8000/api/v1/meetings/$MEETING_ID/process" \
  -H 'Content-Type: application/json' \
  -d '{"media_id":"REPLACE_WITH_UPLOADED_MEDIA_UUID","export_formats":["docx","pdf"]}'
curl --fail-with-body "http://localhost:8000/api/v1/meetings/$MEETING_ID/processing-run"
curl --fail-with-body "http://localhost:8000/api/v1/meetings/$MEETING_ID/processing"
curl --fail-with-body "http://localhost:8000/api/v1/meetings/$MEETING_ID/result"
curl --fail-with-body -OJ "http://localhost:8000/api/v1/meetings/$MEETING_ID/exports/docx"
```

`process` возвращает 202 и durable RunView: `id`, `meeting_id`, `media_id`, `status`,
`stage`, `steps`, `export_formats`, `exports`, `error_code`, `error_message`, timestamps.
Frontend может опрашивать `processing-run` раз в 1–2 секунды, прекращая polling при
`completed`/`failed`. В `exports` — метаданные, а сами файлы отдаются существующим GET.
Встреча должна иметь актуальную загруженную запись; обработка старого media_id отклоняется.

Статусы запуска: queued → running → completed/failed. Статусы этапов:
preprocessing, transcribing, diarizing, canonicalizing, resolving_speakers, analyzing,
exporting. В существующем API встречи финальное состояние по-прежнему `ready`, чтобы
сохранить совместимость frontend-контракта. `ready` устанавливается после всех экспортов.
Speech tracker сообщает настоящие границы ASR/diarization; NVIDIA получает их одним
облачным запросом, поэтому второй этап может пройти сразу по кэшу.

Повторный запрос с тем же media/форматами возвращает текущий запуск. Повтор queued
может переотправить тот же ID в брокер, чтобы восстановить разрыв между DB и publish;
атомарный claim допускает только одного исполнителя. Новый набор форматов во время
активного запуска даёт 409. После failed следующий POST создаёт новую попытку;
старые доставки не смогут её захватить. Уже завершённый запуск переиспользуется;
`"refresh":true` создаёт новую попытку с переиспользованием кэшей отдельных сервисов.
Refresh не принуждает повторный LLM-анализ уже опубликованной версии стенограммы.

## Конфигурация

Нужны работающие PostgreSQL, Redis, API и Celery worker с одним и тем же environment
и доступом к media storage. Миграции: `0007 → 0008 → 0009`.

- `SPEECH_ENABLED=true` и настроенные провайдеры речи.
- `TRANSCRIPT_CANONICALIZATION_ENABLED=true`, модель и `OPENAI_API_KEY`.
- `MEETING_INTELLIGENCE_ENABLED=true` и модели из документации агентного модуля.
- DejaVu fonts для PDF входят в backend image.

`AI_MODE=mock` относится к старому демонстрационному jobs API и не включает fake
результаты обработки встречи. При отсутствии конфигурации запуск возвращает 503.
Текущий NVIDIA-путь разрешён только для `language_hint=ru`; kk/mixed/auto отклоняются
с 422. Ограничения 16 MiB WAV и максимум четырёх speakers сохраняются.

Worker использует один prefork-процесс (`--concurrency=1`) и один постоянный event loop,
чтобы cached SDK clients не переносились между asyncio loops. Задача ограничена часом.
На штатном завершении worker SDK clients закрываются; Celery task_failure фиксирует
ошибку исполнения. Повторы не выполняются бесконечно и не запускают незаметно новые
платные вызовы. Новый ручной запуск после ошибки использует сохранённые результаты.

При обновлении существующей dev-среды новые Python-файлы подхватываются bind mount;
зависимости этого шага не требуют повторной сборки образа:

```sh
make migrate
docker compose -f compose.yaml -f compose.dev.yaml up -d --no-build worker
# После обновления Python-кода уже работающего worker:
make restart-worker
```

## Реализация

`app/processing/models.py` — текущий запуск, typed request/response; `repository.py` —
атомарная резервация и переходы; `service.py` — workflow; `dependencies.py` — adapters
к существующим сервисам; `queue.py` — только ID в Celery; `router.py` — запуск/polling.
`entrypoints/worker.py` исполняет workflow. Большие bytes/transcripts не передаются
через брокер. `meeting_processing_runs` содержит одну текущую попытку на встречу.

Speaker stage сохраняет mapping artifact; анализатор повторно получает его из кэша.
При неизвестных именах unresolved сохраняется; имена не придумываются. Отдельный
MeetingProtocol snapshot по-прежнему собирается из сохранённого анализа при экспорте.

## Проверки и ограничения

Offline tests покрывают порядок этапов, конкурентные доставки, повтор POST,
ошибку очереди (включая timeout после захвата), остановку на ошибке, новую попытку,
защиту от старой доставки, смену записи, безопасные ошибки и владение статусом ready.
Агентные tests используют управляемые ответы вместо OpenAI; тесты экспорта создают
настоящие DOCX/PDF. Точность моделей этим не измеряется.

Остаются отдельными задачами frontend wiring, live benchmark качества RU/KZ и
диаризации, уведомления и access control. Общая очередь не имеет глобальной квоты
ожидающих встреч. Ограничение concurrency действует на worker; дополнительные workers
увеличивают параллелизм и расходы. Не запускайте ручные endpoints отдельных стадий
параллельно с общей обработкой той же встречи.

При полной потере worker host сигнал ошибки может не дойти до БД: автоматический
lease watchdog/recovery ещё не добавлен. Такой running-запуск требует операторского
сброса после подтверждения остановки старого worker. История всех попыток и outbox
не ведутся; хранится текущая попытка, а артефакты стадий сохраняются отдельно.
