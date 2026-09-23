# Контракт UI и backend для Qoryt

Этот документ фиксирует данные и действия, которые требуются уже собранному интерфейсу. Он нужен как очередь разработки backend-модулей: UI не следует считать подтверждением существования этих API.

## Пользовательский поток

```text
Обзор → Создать совещание → Загрузить запись → Подготовить аудио
                                              ↓
                        Распознать речь → Разделить спикеров → Выделить решения и поручения
                                              ↓
        Саммари / транскрипт / поручения → Экспорт PDF/DOCX → Контроль исполнения
```

## Экраны и требуемые данные

| Экран | Компонент | Данные | Действия пользователя |
| --- | --- | --- | --- |
| Обзор | `meetings/Dashboard.tsx` | последние совещания, счётчики, ближайшие поручения | открыть совещание, перейти к поручениям, создать совещание |
| Новое совещание | `meetings/NewMeeting.tsx` | форма совещания, файл, статус обработки | создать совещание, загрузить запись, запустить подготовку аудио |
| Рабочее пространство | `meetings/MeetingWorkspace.tsx` | совещание, участники, прогресс, саммари, решения, транскрипт, поручения | читать, редактировать, сопоставлять спикеров, экспортировать |
| Поручения | `tasks/TaskBoard.tsx` | список, статусы, сроки, ответственные, счётчики | искать, фильтровать, менять статус |

`features/meetings/data.ts` содержит только демонстрационные данные. Его структура — ориентир для DTO, но не источник истины для backend.

## Существующий интегрированный API

| Метод | Маршрут | Назначение | UI |
| --- | --- | --- | --- |
| `POST` | `/api/v1/meetings/{meeting_id}/media` | сохраняет оригинальный аудио- или видеофайл | `meetingMediaApi.upload()` |
| `POST` | `/api/v1/meetings/{meeting_id}/media/{media_id}/preprocess` | создаёт `NormalizedAudio` | `meetingMediaApi.preprocess()` |

Сейчас `NewMeeting.tsx` временно генерирует `meeting_id` в браузере. Когда появится модуль meetings, это нужно заменить на создание записи совещания через API до загрузки файла.

## Требуемые модули backend

| Приоритет | Модуль | Ответственность | Результат для UI |
| --- | --- | --- | --- |
| 1 | `meetings` | жизненный цикл совещания, метаданные, список и доступ | карточки обзора, заголовок workspace |
| 2 | `speech` | локальный ASR RU/KZ/mixed, diarization, alignment | транскрипт с `speaker_id` и таймкодами |
| 3 | `intelligence` | summary, решения, поручения и ссылки на сегменты транскрипта | вкладки «Саммари» и «Поручения» |
| 4 | `tasks` | статусы, сроки, ответственные, поиск и фильтры | доска поручений и виджеты обзора |
| 5 | `protocols` | рендер PDF/DOCX из структурированного результата | кнопка «Экспорт» |
| 6 | `notifications` | напоминания и просрочки | будущие уведомления и рассылки |

`media` и `audio` уже реализованы и остаются источником оригинала и нормализованного аудио. Они не должны брать на себя ASR, diarization или создание поручений.

## Минимальные HTTP-контракты

### Совещания

```text
POST   /api/v1/meetings
GET    /api/v1/meetings?cursor=&limit=&status=
GET    /api/v1/meetings/{meeting_id}
PATCH  /api/v1/meetings/{meeting_id}
GET    /api/v1/meetings/{meeting_id}/processing
```

`POST /meetings` принимает `title`, `scheduled_at`, `language_hint`, `expected_participant_count`, `recording_consent_confirmed` и возвращает `id`. Поле согласия должно храниться отдельно от записи и быть доступно аудиту.

`GET /meetings/{id}/processing` возвращает текущее состояние конвейера: `uploaded`, `preprocessing`, `transcribing`, `diarizing`, `analyzing`, `ready`, `failed`. Для каждого шага нужны `progress`, `message`, `updated_at` и безопасный для UI текст ошибки.

### Результат обработки

```text
GET    /api/v1/meetings/{meeting_id}/result
PATCH  /api/v1/meetings/{meeting_id}/participants/{speaker_id}
GET    /api/v1/meetings/{meeting_id}/transcript?cursor=&q=
GET    /api/v1/meetings/{meeting_id}/tasks
POST   /api/v1/meetings/{meeting_id}/exports
```

Ответ `GET /result`:

```json
{
  "meeting": {
    "id": "uuid",
    "title": "Планирование запуска Q4",
    "started_at": "2026-09-23T10:00:00+05:00",
    "duration_seconds": 2892,
    "language_detected": ["ru", "kk"],
    "processing_status": "ready"
  },
  "participants": [
    {"speaker_id": "speaker-1", "display_name": "Айдана С.", "speech_share": 0.26}
  ],
  "summary": "…",
  "decisions": [
    {"id": "uuid", "text": "Запустить пилот 1 октября", "source_segment_ids": ["uuid"]}
  ],
  "tasks": [
    {
      "id": "uuid",
      "text": "Подготовить финальную смету",
      "assignee": {"id": "uuid", "display_name": "Марат К."},
      "due_at": "2026-09-23T18:00:00+05:00",
      "status": "in_progress",
      "priority": "high",
      "source_segment_ids": ["uuid"]
    }
  ]
}
```

Транскрипт должен быть постраничным, а не вложенным в `GET /result`:

```json
{
  "items": [
    {
      "id": "uuid",
      "started_at_ms": 134000,
      "ended_at_ms": 151000,
      "speaker_id": "speaker-1",
      "text": "Коллеги, предлагаю…",
      "confidence": 0.94,
      "language": "ru"
    }
  ],
  "next_cursor": null
}
```

### Поручения

```text
GET    /api/v1/tasks?status=&assignee_id=&due_before=&q=&cursor=
PATCH  /api/v1/tasks/{task_id}
```

Для UI используйте транспортные статусы `in_progress`, `overdue`, `completed`; отображаемые русские названия остаются ответственностью фронтенда. `PATCH /tasks/{id}` принимает только разрешённые пользователю изменения: как минимум `status`, `assignee_id`, `due_at`, `text`.

### Экспорт

`POST /meetings/{id}/exports` принимает `{ "format": "pdf" | "docx" }` и возвращает состояние задачи экспорта либо готовый защищённый URL. Фронтенд не должен собирать итоговый протокол из локальных строк: текущий текстовый файл в `MeetingWorkspace.tsx` является временным demo-поведением.

## Доменные границы и очередь реализации

1. Добавить таблицу и API `meetings`; после этого заменить `crypto.randomUUID()` на `POST /meetings`.
2. Связать существующие `MediaAsset` и `NormalizedAudio` с настоящей встречей.
3. Реализовать локальные `speech` и `alignment`, писать сегменты транскрипта отдельно от медиа.
4. Реализовать `intelligence`, сохранять summary, решения и поручения с `source_segment_ids`.
5. Добавить `tasks` API и подключить фильтры, поиск и смену статуса из UI.
6. Реализовать `protocols` и заменить demo-export на серверный PDF/DOCX.
7. Добавить polling или SSE для статуса обработки. SSE предпочтительнее, если нужны live-обновления нескольких стадий.

## Ограничения безопасности

- Аудио, сегменты транскрипта, результаты speech и intelligence остаются в закрытом контуре.
- Имена участников могут быть назначены вручную секретарём; `speaker_id` не является биометрической идентификацией.
- Контроль доступа, аудит изменений поручений и экспорта нужны до внешнего развёртывания.
- Не выдавать прямые публичные ссылки на оригиналы записей; скачивание и экспорт должны проверять права пользователя.
