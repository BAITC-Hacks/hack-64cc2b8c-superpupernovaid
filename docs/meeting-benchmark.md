> Для создания новой встречи runner теперь требует `--recording-consent-confirmed`. Для существующей используйте `--meeting-id`.

# Реальный meeting pipeline benchmark

Runner использует существующие production HTTP endpoints, не создаёт сущности вручную
и не дублирует FFmpeg/ASR/diarization/alignment/prompt. Meeting API пока отсутствует:
meeting_id — UUID namespace. Поэтому заголовок встречи не создаётся в несуществующей таблице.

Запуск из backend/ (API и PostgreSQL должны работать, миграции применены):

```sh
.venv/bin/python -m benchmarks.run_meeting \
  --audio "/Users/daniyar/Downloads/Совещание №2.mp3" \
  --output benchmarks/results/meeting_02/nemo_nemo
```

По умолчанию API http://127.0.0.1:8000 и контейнер superpupernova-backend-1.
--base-url / --container меняют их. Пустой --container отключает Docker inspection:
тогда не проверяются фактические server model config/artifact files и backend RSS.
Для воспроизводимого сравнения предпочтителен режим с доступным контейнером.

Runner делает ffprobe inspection без вывода tags, потоковый multipart upload через
httpx file object, POST preprocess, POST speech и только после его успеха POST canonicalize.
JSON каждого успешного этапа сохраняется по production DTO, без benchmark-specific transcript.
Временные пути/UUID не используются вместо текста; fake transcript не создаётся.

## Результат реального запуска

Полный baseline **не достигнут**. Ingestion и preprocessing прошли; остановка на Speech:
HTTP 503, code speech_disabled. Torch/NeMo и обе модели отсутствуют, SPEECH_ENABLED=false.
Canonicalization не вызывалась, так как AttributedTranscript не получен. Её настройки
тоже пока неполные: enabled=false, model пустая, OPENAI_API_KEY не задан.
NVIDIA_API_KEY для локального restore/inference не обязателен и не является причиной остановки.

Source: `/Users/daniyar/Downloads/Совещание №2.mp3`.
MP3: 3 334 695 байт, 206.031250 сек, stream 0 mp3 / 48000 Hz / mono.
Stream 1 png с attached_pic=1 — встроенная обложка. Ingestion определил тип audio;
preprocessing с -map 0:a:0 создал WAV без video stream.

- meeting_id: `30a8b807-f493-498f-ad5d-ece2c8731258`
- media_id: `60c46e87-b959-48b6-8507-3f8226fbf8de`
- normalized_audio_id: `dd862e43-bfe8-4594-8cb6-4b4a01c9608d`
- upload: 0.126268 сек, статус uploaded;
- preprocessing: 0.303831 сек;
- normalized: 16000 Hz / mono / pcm_s16le / WAV, 206.031250 сек, 6 593 080 байт;
- source MediaAsset до/после совпал; MP3 на хосте и stored original совпали по SHA256;
- hash normalized artifact сверён с DB DTO, фактические параметры проверены ffprobe;
- весь попытанный pipeline: 1.613025 сек, включая диагностику;
- detected speakers / transcript segments: **не определены**, inference не запускался.

Фактические пути внутри Docker volume media-data:

```text
source:
/data/media/30a8b807-f493-498f-ad5d-ece2c8731258/60c46e87-b959-48b6-8507-3f8226fbf8de/source

normalized:
/data/media/30a8b807-f493-498f-ad5d-ece2c8731258/60c46e87-b959-48b6-8507-3f8226fbf8de/processed/d077df9f7d2aaddb1c8195ca172f8dbe62057d59af99c6be6d85154a7fc102e9/dd862e43-bfe8-4594-8cb6-4b4a01c9608d/speech_input.wav
```

Результаты:

```text
/Users/daniyar/Documents/Self-Development/Hackathon/hack alem ai/hack-64cc2b8c-superpupernovaid/backend/benchmarks/results/meeting_02/nemo_nemo/20260923T102916_927937Z
  source_probe.json
  media_asset.json
  normalized_audio.json
  run_metadata.json
```

attributed_transcript.json / canonical_transcript.json отсутствуют, поскольку этапы не прошли.
Первая диагностическая попытка сохранена отдельно в 20260923T102810_105528Z; sampler не смог
получить host ps из sandbox. Во второй попытке sampler исправлен, реальные metrics ниже.
Оригинальные/derived файлы обеих попыток оставлены в storage, пользовательский MP3 не удалялся.

## Память и модельный lifecycle

Пять samples суммы RSS процессов backend container:

- before: 205406208 байт (195.89 МиБ);
- approximate peak: 260755456 байт (248.68 МиБ);
- after: 231567360 байт (220.84 МиБ).

Измерение раз в ~0.2 сек плюс время docker exec. Включает API/reloader/FFmpeg/диагностику,
может дважды учитывать shared pages и пропускать краткие пики. Это не exclusive heap и
не GPU benchmark. Client metric — resource.getrusage high-water RSS, а не current RSS.
Все samples записаны в run_metadata.json. Source и artifact hashes читаются блоками 1 МиБ;
httpx multipart читает file object порциями, whole-file read не используется.

В этом запуске NeMo модели вообще не загружались. Код адаптеров использует cached DI и
thread-safe lazy initialization (отдельная модель ASR и diarization по одному экземпляру),
но реальный GPU lifecycle необходимо подтвердить после установки моделей.

## Что нужно для продолжения

Подготовить ML environment/image на подходящей машине (базовый API Docker с 1 ГиБ
не предназначен для inference), установить optional speech dependencies, положить локально:

- NeMo ASR .nemo с настоящими word timestamps и нужными языками;
- streaming Sortformer .nemo для diarization; проверить допустимое число speakers модели.

Никаких огромных моделей runner не скачивает. Поставьте пути внутри выбранного runtime в .env:

```dotenv
SPEECH_ENABLED=true
ASR_PROVIDER=nemo
DIARIZATION_PROVIDER=nemo
NEMO_ASR_MODEL=/models/asr/model.nemo
NEMO_DIARIZATION_MODEL=/models/diar/streaming-sortformer.nemo
NEMO_DEVICE=cuda
TRANSCRIPT_CANONICALIZATION_ENABLED=true
TRANSCRIPT_CANONICALIZATION_MODEL=YOUR_CONFIGURED_MODEL
TRANSCRIPT_CANONICAL_LANGUAGE=ru
```

OPENAI_API_KEY задаётся существующим secret-setting, не выводится в терминал/metadata.
Canonicalization отправляет текст в OpenAI по текущему запросу; для закрытого контура нужна
другая implementation. Не включайте Speech в базовом контейнере без установки ML runtime.
После запуска API с этими settings можно продолжить на **том же исходном artifact**:

```sh
.venv/bin/python -m benchmarks.run_meeting \
  --audio "/Users/daniyar/Downloads/Совещание №2.mp3" \
  --meeting-id 30a8b807-f493-498f-ad5d-ece2c8731258 \
  --media-id 60c46e87-b959-48b6-8507-3f8226fbf8de \
  --output benchmarks/results/meeting_02/nemo_nemo
```

Это GET существующего MediaAsset вместо повторного upload; preprocess переиспользует
NormalizedAudio при неизменном profile. Если использован другой backend container,
укажите --container с его именем и --base-url с API URL.

## Повтор с Whisper + Pyannote

Только после успешного NeMo baseline и ручной подготовки local models/runtime замените
settings **серверного процесса**, затем перезапустите API. Переменные только у runner
не переключают providers уже работающего backend.

```dotenv
SPEECH_ENABLED=true
ASR_PROVIDER=whisper
DIARIZATION_PROVIDER=pyannote
WHISPER_MODEL=/models/faster-whisper-large-v3
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
PYANNOTE_MODEL=/models/pyannote-community-1
PYANNOTE_DEVICE=cuda
```

Точная команда runner из backend/ для того же исходника:

```sh
.venv/bin/python -m benchmarks.run_meeting \
  --audio "/Users/daniyar/Downloads/Совещание №2.mp3" \
  --meeting-id 30a8b807-f493-498f-ad5d-ece2c8731258 \
  --media-id 60c46e87-b959-48b6-8507-3f8226fbf8de \
  --output benchmarks/results/meeting_02/whisper_pyannote
```

Speech/cache profile меняется по providers/settings; source audio остаётся тем же.
Каждый запуск создаёт новый timestamp directory, старые predictions не перезаписываются.

## Повторяемый integration test

```sh
RUN_MEETING_BENCHMARK=1 \
  MEETING_BENCHMARK_AUDIO="/Users/daniyar/Downloads/Совещание №2.mp3" \
  .venv/bin/pytest -m 'integration and benchmark'
```

Этот test требует полного успешного pipeline, поэтому при текущем speech_disabled упадёт,
а без opt-in пропускается. Это техническая проверка, не оценка WER/DER: не утверждает,
что speakers должно быть ровно N. При успехе проверяет непустые уникальные ID, порядок,
валидные timestamps/text/speaker, а затем полное совпадение metadata и original_text после
canonicalization. Ground truth и человеческая расшифровка нигде не используются.

Full transcript outputs игнорируются Git и Docker build context; MP3 не копируется в repo.
Реальное хранение копии через production upload — штатный volume media-data.
В Git добавляются только runner/test/docs, не benchmark results. Secret values и headers
не входят в metadata. Exit code runner: 0 — полный успех, 2 — blocked/failure с report.
