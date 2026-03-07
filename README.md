# ANPR System v0.8 Web

![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)
![Web UI](https://img.shields.io/badge/UI-Web--only-4CAF50.svg)
![YOLOv8](https://img.shields.io/badge/Detection-YOLOv8-red.svg)
![CRNN](https://img.shields.io/badge/OCR-CRNN-orange.svg)
![Storage](https://img.shields.io/badge/Data-SQLite%20%2F%20PostgreSQL-lightgrey.svg)

Web-first система автоматического распознавания автомобильных номеров.

Проект выполняет server-side обработку видеопотоков, распознаёт номера, сохраняет события, публикует live-обновления в браузер и отдаёт live preview без отдельного медиасервера.

---

## Что умеет система

- многоканальная обработка видео: отдельный runtime на каждый канал;
- server-side ANPR pipeline: детекция, OCR, агрегация по треку, постобработка, cooldown;
- web UI оператора: наблюдение, журнал, списки, настройки;
- live preview по MJPEG из того же channel runtime;
- live-события через SSE;
- управление каналами через API: создать, изменить, запустить, остановить, перезапустить;
- настройка ROI, размера номера, OCR порогов, cooldown и direction heuristics;
- white/black/custom plate lists;
- управление контроллерами через API;
- retention / cleanup / CSV / ZIP export;
- SQLite по умолчанию и PostgreSQL как primary backend с optional compatibility dual-write.

---

## Как устроен проект

Система разделена на три основных контура:

1. **API service**  
   FastAPI приложение, которое:
   - обслуживает web UI;
   - хранит и отдаёт настройки;
   - управляет каналами;
   - публикует live events;
   - отдаёт snapshot и MJPEG preview.

2. **Channel runtime / ANPR Core**  
   Для каждого канала создаётся отдельный поток обработки, который:
   - открывает источник видео;
   - читает кадры;
   - формирует preview JPEG в памяти;
   - прогоняет кадры через YOLO + OCR pipeline;
   - сохраняет события в storage;
   - отправляет события в EventBus.

3. **Retention worker**  
   Отдельный сервис для:
   - очистки старых событий;
   - удаления старых медиа;
   - контроля размера media storage;
   - экспорта CSV / ZIP.

---

## Важное замечание по текущей реализации

Runtime канала поддерживает два режима обработки:

- `detection_mode="always"` — каждый кадр проходит стандартную ветку `detector.track(frame) -> pipeline.process_frame(...)`.
- `detection_mode="motion"` — перед ANPR используется `MotionDetector`:
  - preview (`latest_jpeg`, `snapshot.jpg`, `preview.mjpg`) продолжает обновляться всегда;
  - ANPR-вычисления запускаются только при активном движении;
  - дополнительно учитывается `detector_frame_stride`, чтобы ограничить частоту вызова detector даже при активном движении.

Если `detection_mode` отсутствует или имеет неизвестное значение, применяется безопасный fallback на `always`.

---

## Диаграмма 1. Общая схема взаимодействия сервисов

```mermaid
flowchart TD
    USER["Оператор / Браузер"] --> UI["Web UI<br/>apps/web/index.html"]

    subgraph API["API service / FastAPI<br/>apps/api/main.py"]
        HTTP["REST API"]
        SSE["SSE stream"]
        PREVIEW["Preview endpoints<br/>snapshot and preview"]
        PROC["ChannelProcessor"]
        BUS["EventBus"]
        SETTINGS["SettingsManager"]
        EVENTS_DB["EventDatabase / PostgresEventDatabase"]
        LISTS_DB["ListDatabase"]
        CTRL["ControllerService"]
        LIFE["DataLifecycleService"]
    end

    subgraph CORE["ANPR Core runtime"]
        SRC["RTSP / HTTP / file / camera"]
        CH["Channel thread"]
        YOLO["YOLODetector"]
        PIPE["ANPRPipeline"]
        SINK["DualEventSink"]
    end

    subgraph WORKER["Retention worker<br/>apps/worker/main.py"]
        SCH["RetentionScheduler"]
        WLIFE["DataLifecycleService"]
    end

    subgraph STORAGE["Storage"]
        SQLITE[("SQLite")]
        PG[("PostgreSQL")]
        MEDIA[("Screenshots / crops / exports")]
    end

    UI --> HTTP
    UI --> SSE
    UI --> PREVIEW

    HTTP --> SETTINGS
    HTTP --> PROC
    HTTP --> EVENTS_DB
    HTTP --> LISTS_DB
    HTTP --> CTRL
    HTTP --> LIFE

    PROC --> CH
    SETTINGS --> CH
    SRC --> CH
    CH --> YOLO
    YOLO --> PIPE
    PIPE --> SINK
    SINK --> EVENTS_DB
    SINK --> BUS

    SSE --> BUS
    PREVIEW --> PROC

    EVENTS_DB --> SQLITE
    EVENTS_DB --> PG
    LIFE --> SQLITE
    LIFE --> PG
    LIFE --> MEDIA
    WLIFE --> SQLITE
    WLIFE --> PG
    WLIFE --> MEDIA
    SCH --> WLIFE
```

---

## Диаграмма 2. Что происходит после подключения видеопотока

Эта схема отвечает на вопрос: как канал получает видео, где рождается preview и куда уходит кадр на распознавание.

```mermaid
flowchart TD
    A["Источник видео<br/>RTSP / HTTP / файл / камера"] --> B["ChannelProcessor.ensure_channel"]
    B --> C["ChannelProcessor.start"]
    C --> D["Отдельный поток channel-CHANNEL_ID"]
    D --> E["cv2.VideoCapture(source)"]
    E --> F["cap.read() to frame"]

    F --> G["Preview ветка"]
    G --> H["cv2.imencode jpg"]
    H --> I["latest_jpeg в памяти<br/>ChannelContext"]
    I --> J["Snapshot endpoint"]
    I --> K["Preview MJPEG endpoint"]
    K --> L["Web UI"]

    F --> M["ANPR ветка"]
    M --> N["YOLODetector.track(frame)"]
    N --> O["ANPRPipeline.process_frame(...)"]
```

---

## Диаграмма 3. Внутренний ANPR pipeline

Это основная процессная диаграмма распознавания номера в текущем проекте.

```mermaid
flowchart TD
    A["Frame"] --> B["YOLODetector.track(frame)"]
    B --> C{"Размер номера подходит?"}
    C -->|Нет| Z["Пропуск detection"]
    C -->|Да| D["TrackDirectionEstimator.update(...)"]
    D --> E["Вырезание bbox из кадра"]
    E --> F["PlatePreprocessor.preprocess(...)"]
    F --> G["CRNNRecognizer.recognize_batch(...)"]

    G --> H{"confidence >= ocr_min_confidence?"}
    H -->|Нет| U["Пометить как unreadable"]
    H -->|Да| I{"Есть track_id?"}

    I -->|Да| J["TrackAggregator<br/>best shots + quorum + weighted majority"]
    I -->|Нет| K["Использовать текущий OCR текст"]

    J --> L["PlatePostProcessor.process(...)"]
    K --> L

    L --> M{"Номер валиден?"}
    M -->|Нет| Z
    M -->|Да| N{"Cooldown прошёл?"}
    N -->|Нет| Z
    N -->|Да| O["Сформировать готовое событие"]
```

---

## Диаграмма 4. Как событие сохраняется и попадает в UI

```mermaid
flowchart TD
    A["Готовое событие"] --> B["DualEventSink.insert_event(...)"]

    B --> C{"Есть postgres_dsn?"}
    C -->|Да| D["PostgresEventDatabase.insert_event(...)"]
    D --> E{"dual_write_enabled?"}
    E -->|Да| F["SQLite compatibility write"]
    E -->|Нет| G["Только PostgreSQL"]
    C -->|Нет| H["SQLite EventDatabase.insert_event(...)"]

    A --> I["event_callback"]
    I --> J["EventBus.publish(...)"]
    J --> K["SSE endpoint for events stream"]
    K --> L["EventSource в Web UI"]

    D --> M["REST endpoint for events list"]
    F --> M
    H --> M
    M --> N["Журнал событий / детали события"]
```

---

## Диаграмма 5. Как работает video preview для UI

Здесь важно, что браузер получает не прямой RTSP, а уже подготовленный сервером MJPEG поток.

```mermaid
flowchart LR
    A["Камера / RTSP"] --> B["Server-side ChannelProcessor"]
    B --> C["cap.read()"]
    C --> D["cv2.imencode jpg"]
    D --> E["latest_jpeg cache"]
    E --> F["Snapshot endpoint"]
    E --> G["Preview MJPEG endpoint"]
    G --> H["img / preview блок в Web UI"]
```

---

## Диаграмма 6. Retention и обслуживание хранения

```mermaid
flowchart TD
    A["Storage policy"] --> B["Retention worker startup"]
    B --> C["RetentionScheduler.start()"]
    C --> D{"auto_cleanup_enabled?"}
    D -->|Да| E["run_retention_cycle()"]
    D -->|Нет| J["Sleep"]

    E --> F["cleanup_old_events()"]
    E --> G["cleanup_old_media()"]
    E --> H["enforce_storage_limit()"]
    E --> I["export and bundle use same lifecycle service"]

    F --> K[("SQLite / PostgreSQL")]
    G --> L[("media dir")]
    H --> L

    J --> C
    E --> C
```

---

## Поток данных по шагам

### 1. Подключение канала

При старте API читает список каналов из `settings.json`.  
Для каждого канала `ChannelProcessor` создаёт `ChannelContext`.  
Если канал `enabled=true`, для него сразу запускается отдельный thread.

### 2. Получение кадров

Поток канала открывает источник через `cv2.VideoCapture(source)` и в цикле вызывает `cap.read()`.

Если чтение кадра не удалось:
- увеличиваются `timeout_count` и `reconnect_count`;
- preview помечается как недоступный;
- источник открывается заново.

### 3. Формирование preview

Примерно раз в `0.2` секунды текущий кадр кодируется в JPEG и сохраняется в память:
- `latest_jpeg`
- `latest_frame_ts`
- `preview_ready`
- `preview_last_frame_at`

Дальше API отдаёт этот же буфер:
- как единичный снимок через `/api/channels/{id}/snapshot.jpg`;
- как multipart MJPEG поток через `/api/channels/{id}/preview.mjpg`.

### 4. Детекция и распознавание

Тот же кадр идёт в:
- `YOLODetector.track(frame)`;
- затем в `ANPRPipeline.process_frame(frame, detections)`.

Внутри pipeline выполняются:
- обновление направления движения по треку;
- кроп bbox номера;
- preprocessing;
- batch OCR;
- агрегация результата по треку;
- постобработка и валидация;
- cooldown-фильтр.

### 5. Сохранение события

Если номер валиден и cooldown прошёл, формируется событие с полями:
- `timestamp`
- `channel`
- `channel_id`
- `plate`
- `country`
- `confidence`
- `source`
- `direction`

Событие записывается в storage через `DualEventSink`.

### 6. Публикация события в UI

После записи событие публикуется в `EventBus`, а затем попадает в браузер через `/api/events/stream`.

UI параллельно:
- держит live stream для новых событий;
- подгружает исторические события через `/api/events`;
- открывает детали события и связанные изображения через `/api/events/item/{id}` и `/api/events/item/{id}/media/{kind}`.

---

## Основные компоненты

### Backend / API

- `apps/api/main.py` — главный FastAPI backend;
- `apps/api/data_lifecycle.py` — retention, cleanup, export;
- `packages/anpr_core/channel_runtime.py` — runtime каналов;
- `packages/anpr_core/event_bus.py` — in-memory pub/sub для live событий;
- `packages/anpr_core/event_sink.py` — запись событий в SQLite/PostgreSQL.

### ANPR

- `anpr/detection/yolo_detector.py` — детектор номерных рамок и tracking fallback logic;
- `anpr/pipeline/anpr_pipeline.py` — OCR pipeline, aggregator, direction estimator, cooldown;
- `anpr/preprocessing/plate_preprocessor.py` — коррекция перспективы / наклона;
- `anpr/recognition/crnn_recognizer.py` — OCR CRNN;
- `anpr/postprocessing/validator.py` — валидация по конфигам стран;
- `anpr/detection/motion_detector.py` — модуль motion detection, пока не включён в основной runtime path.

### Web UI

`apps/web/index.html` — операторская панель с вкладками:
- Наблюдение;
- Журнал;
- Списки;
- Настройки.

### Worker

`apps/worker/main.py` — отдельный retention worker.

---

## REST / streaming endpoints

### Базовые

- `GET /` — web UI;
- `GET /api/health` — health API.

### Каналы

- `GET /api/channels`
- `POST /api/channels`
- `PUT /api/channels/{channel_id}`
- `DELETE /api/channels/{channel_id}`
- `GET /api/channels/{channel_id}/config`
- `PUT /api/channels/{channel_id}/config`
- `PUT /api/channels/{channel_id}/ocr`
- `PUT /api/channels/{channel_id}/filter`
- `POST /api/channels/{channel_id}/start`
- `POST /api/channels/{channel_id}/stop`
- `POST /api/channels/{channel_id}/restart`
- `GET /api/channels/{channel_id}/health`
- `GET /api/channels/{channel_id}/snapshot.jpg`
- `GET /api/channels/{channel_id}/preview/status`
- `GET /api/channels/{channel_id}/preview.mjpg`

### События

- `GET /api/events`
- `GET /api/events/item/{event_id}`
- `GET /api/events/item/{event_id}/media/frame`
- `GET /api/events/item/{event_id}/media/plate`
- `GET /api/events/stream`

### Контроллеры

- `GET /api/controllers`
- `POST /api/controllers`
- `PUT /api/controllers/{controller_id}`
- `DELETE /api/controllers/{controller_id}`
- `POST /api/controllers/{controller_id}/test`

### Списки

- `GET /api/lists`
- `POST /api/lists`
- `GET /api/lists/{list_id}/entries`
- `POST /api/lists/{list_id}/entries`

### Хранение и экспорт

- `GET /api/data/policy`
- `PUT /api/data/policy`
- `POST /api/data/retention/run`
- `GET /api/data/export/events.csv`
- `POST /api/data/export/bundle`
- `GET /api/storage/dual-write`
- `PUT /api/storage/dual-write`

### Глобальные настройки

- `GET /api/settings`
- `PUT /api/settings`

### Worker

- `GET /worker/health`
- `POST /worker/retention/run`

---

## Технологический стек

- **Backend:** FastAPI, Uvicorn
- **Detection:** YOLOv8 (Ultralytics)
- **OCR:** CRNN
- **Видео:** OpenCV
- **ML:** PyTorch 2.8.0, torchvision 0.23.0, torchaudio 2.8.0
- **Live updates:** SSE
- **Preview:** MJPEG
- **Storage:** SQLite / PostgreSQL
- **Worker:** отдельный FastAPI-based retention service

---

## Структура проекта

```text
ANPR-System-v0.8_web/
├── apps/
│   ├── api/                 # backend API, preview, export, settings
│   ├── worker/              # retention worker
│   ├── web/                 # web UI
│   └── video_gateway/       # legacy / optional
├── packages/
│   └── anpr_core/           # channel runtime, event bus, sink
├── anpr/
│   ├── detection/
│   ├── pipeline/
│   ├── preprocessing/
│   ├── recognition/
│   ├── postprocessing/
│   └── infrastructure/
├── infra/
│   ├── docker-compose.yml
│   ├── postgres/
│   ├── nginx/
│   └── k8s/
├── config/
├── models/
├── scripts/
├── data/
├── logs/
├── requirements.txt
└── settings.json
```

---

## Установка

### Предварительные требования

- Python 3.13
- pip
- OpenCV runtime dependencies
- модели YOLO и OCR в каталоге `models/`

### Клонирование

```bash
git clone https://github.com/quick-1y/ANPR-System-v0.8_web.git
cd ANPR-System-v0.8_web
```

### Установка зависимостей

#### CPU

```bash
pip install -r requirements.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
```

#### CUDA 12.8 / PyTorch 2.8.0

```bash
pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt --extra-index-url https://pypi.org/simple
```

---

## Локальный запуск

Откройте два отдельных терминала.

### 1. API + Web UI

```bash
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
```

### 2. Retention worker

```bash
python -m uvicorn apps.worker.main:app --host 0.0.0.0 --port 8092
```

### Точки доступа

- Web UI: `http://localhost:8080`
- API health: `http://localhost:8080/api/health`
- Live preview MJPEG: `http://localhost:8080/api/channels/{id}/preview.mjpg`
- Worker health: `http://localhost:8092/worker/health`

---

## Docker Compose

```bash
cd infra
docker compose up --build
```

Поднимаются сервисы:
- `api`
- `retention_worker`
- `postgres`

Compose передаёт `POSTGRES_DSN=postgresql://anpr:anpr@postgres:5432/anpr` и публикует порты:
- `8080` — API / Web UI
- `8092` — worker
- `5432` — PostgreSQL

---

## Хранение данных

### SQLite

По умолчанию события пишутся в SQLite.

### PostgreSQL

Если указан `postgres_dsn`, PostgreSQL становится primary backend.

### Dual-write

Если включён `dual_write_enabled`, то при записи в PostgreSQL дополнительно выполняется compatibility write в SQLite.

### Медиа и экспорт

- медиа сохраняются в `screenshots_dir`;
- CSV экспорт создаётся в `export_dir`;
- bundle export упаковывает CSV и доступные медиа в ZIP.

---

## PostgreSQL migration path

Если нужен переход с SQLite на PostgreSQL:

### 1. Создать схему

```bash
psql "$POSTGRES_DSN" -f infra/postgres/schema.sql
```

### 2. Перенести исторические данные

```bash
python scripts/sync_sqlite_to_postgres.py \
  --sqlite data/db/anpr.db \
  --postgres-dsn "$POSTGRES_DSN"
```

### 3. Включить primary PostgreSQL / dual-write

Через API или настройки UI задайте:
- `postgres_dsn`
- `dual_write_enabled`

---

## Диагностика preview и live runtime

### Проверка канала

```bash
curl http://localhost:8080/api/channels
```

Полезные поля в `metrics`:
- `state`
- `fps`
- `latency_ms`
- `preview_ready`
- `preview_last_frame_at`
- `last_error`
- `reconnect_count`
- `timeout_count`

### Проверка preview status

```bash
curl http://localhost:8080/api/channels/1/preview/status
```

### Быстрый snapshot

```bash
curl -o snapshot.jpg http://localhost:8080/api/channels/1/snapshot.jpg
```

### MJPEG preview

Откройте в браузере:

```text
http://localhost:8080/api/channels/1/preview.mjpg
```

### Worker health

```bash
curl http://localhost:8092/worker/health
```

---

## Что ещё важно знать

- preview и ANPR используют один и тот же ingest канала;
- браузер не подключается к RTSP напрямую;
- если чтение потока ломается, runtime пытается открыть источник заново;
- live события идут отдельно от preview: preview — через MJPEG, события — через SSE;
- в UI уже есть настройки motion detection, но основной runtime сейчас работает через прямой `YOLODetector.track(frame)` без отдельного motion gate;
- endpoint `/api/events/stream` реализован как короткий SSE stream, а клиентская часть переподключается повторно.

---

## Статус проекта

Текущая версия — **web-only ANPR system**.

Desktop UI больше не является основным способом работы; основной интерфейс — операторская web-панель.

---

## License

MIT
