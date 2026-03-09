# ANPR System v0.8 Web

![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)
![Web UI](https://img.shields.io/badge/UI-Web--only-4CAF50.svg)
![YOLOv8](https://img.shields.io/badge/Detection-YOLOv8-red.svg)
![CRNN](https://img.shields.io/badge/OCR-CRNN-orange.svg)
![Storage](https://img.shields.io/badge/Data-PostgreSQL-blue.svg)

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
- PostgreSQL как единственный supported storage backend.

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

## Быстрый старт

Поддерживаемая модель runtime: Docker Compose.

### Предварительные требования

- Docker Engine 24+
- Docker Compose v2+
- Файлы моделей в `anpr/models/`

### Подготовка конфигурации

```bash
cp .env.example .env
cp settings.example.yaml settings.yaml
```

### Рекомендуемый запуск

```bash
docker compose up -d --build
```

### Что поднимается

- `nginx` — единственная опубликованная точка входа с хоста;
- `api` — FastAPI + Web UI + channel runtime orchestration;
- `retention_worker` — фоновый retention/cleanup;
- `postgres` — PostgreSQL c инициализацией схемы.

### Порты и доступ

- `HTTP_PORT` (по умолчанию `8080`) публикуется наружу сервисом `nginx`.
- `postgres` наружу не публикуется и доступен только внутри docker-сети.
- `api` и `retention_worker` доступны по внутренним DNS-именам контейнерной сети (`api:8080`, `retention_worker:8092`).

Точки доступа:
- Web UI: `http://localhost:${HTTP_PORT}`
- API health: `http://localhost:${HTTP_PORT}/api/health`
- Worker health: `http://localhost:${HTTP_PORT}/worker/health`

### Volumes

- `pgdata` — данные PostgreSQL;
- `media_data` — `data/screenshots` и `data/exports` для API/worker;
- `logs_data` — `logs` для API/worker.

### Логи и диагностика

```bash
docker compose logs -f nginx api retention_worker postgres
```

Проверки:

```bash
curl http://localhost:${HTTP_PORT}/api/health
curl http://localhost:${HTTP_PORT}/worker/health
curl http://localhost:${HTTP_PORT}/api/channels
curl -o snapshot.jpg http://localhost:${HTTP_PORT}/api/channels/1/snapshot.jpg
```

### Обновление / пересборка

```bash
docker compose pull
docker compose build --no-cache
docker compose up -d
```

### Остановка

```bash
docker compose down
```

### Полный сброс данных (осторожно)

```bash
docker compose down -v
```

---

## Схема конфигурации

- `.env` — единственный слой переменных окружения для контейнеров (`POSTGRES_*`, `POSTGRES_DSN`, `HTTP_PORT`, `LOG_LEVEL`, `SETTINGS_PATH`).
- `settings.yaml` — прикладные настройки ANPR runtime (каналы, ROI, OCR/детекция, retention, контроллеры).
- PostgreSQL — единственный backend runtime-данных (события, списки, записи).

Важно: значения по умолчанию в конфигурации ориентированы на docker-сеть (`postgres` как hostname БД).

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
        EVENTS_DB["PostgresEventDatabase"]
        LISTS_DB["ListDatabase"]
        CTRL["ControllerService"]
        LIFE["DataLifecycleService"]
    end

    subgraph CORE["ANPR Core runtime"]
        SRC["RTSP / HTTP / file / camera"]
        CH["Channel thread"]
        YOLO["YOLODetector"]
        PIPE["ANPRPipeline"]
        SINK["EventSink"]
    end

    subgraph WORKER["Retention worker<br/>apps/worker/main.py"]
        SCH["RetentionScheduler"]
        WLIFE["DataLifecycleService"]
    end

    subgraph STORAGE["Storage"]
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

    EVENTS_DB --> PG
    LIFE --> PG
    LIFE --> MEDIA
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
    A["Готовое событие"] --> B["EventSink.insert_event(...)"]
    B --> D["PostgresEventDatabase.insert_event(...)"]

    A --> I["event_callback"]
    I --> J["EventBus.publish(...)"]
    J --> K["SSE endpoint for events stream"]
    K --> L["EventSource в Web UI"]

    D --> M["REST endpoint for events list"]
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

    F --> K[("PostgreSQL")]
    G --> L[("media dir")]
    H --> L

    J --> C
    E --> C
```

---

## Поток данных по шагам

### 1. Подключение канала

При старте API читает список каналов из `settings.yaml`.  
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

Событие записывается в storage через `EventSink`.

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
- `packages/anpr_core/event_sink.py` — запись событий в PostgreSQL.

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

Отображение направления движения в UI использует подписи **«Приближение»** и **«Отдаление»**.
Эти значения показываются в журнале и в блоке последних событий.

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
- **Storage:** PostgreSQL
- **Worker:** отдельный FastAPI-based retention service

---

## Структура проекта

```text
ANPR-System-v0.8_web/
├── apps/
│   ├── api/                 # backend API, preview, export, settings
│   ├── worker/              # retention worker
│   ├── web/                 # web UI (включая статические флаги: web/images/flags)
│   └── video_gateway/       # legacy / optional
├── packages/
│   └── anpr_core/           # channel runtime, event bus, sink
├── anpr/
│   ├── detection/
│   ├── pipeline/
│   ├── preprocessing/
│   ├── recognition/
│   ├── postprocessing/
│   ├── infrastructure/
│   ├── models/
│   └── countries/
├── database/
│   ├── postgres/           # SQL-схема и init-артефакты PostgreSQL
│   └── README.md
├── docker-compose.yml
├── nginx/
├── scripts/
├── data/
├── logs/
├── requirements.txt
├── .env
├── .env.example
├── settings.yaml
└── settings.example.yaml
```

---

## Хранение данных

### PostgreSQL (обязательно)

События и списки номеров хранятся только в PostgreSQL через `POSTGRES_DSN`.

### Медиа и экспорт

- медиа сохраняются в `screenshots_dir`;
- CSV экспорт создаётся в `export_dir`;
- bundle export упаковывает CSV и доступные медиа в ZIP.

---

## Что ещё важно знать

- preview и ANPR используют один и тот же ingest канала;
- браузер не подключается к RTSP напрямую;
- если чтение потока ломается, runtime пытается открыть источник заново;
- live события идут отдельно от preview: preview — через MJPEG, события — через SSE;
- endpoint `/api/events/stream` реализован как короткий SSE stream, а клиентская часть переподключается повторно.

---

## Статус проекта

Текущая версия — **web-only ANPR system с Docker-only deployment model**.

---

## License

MIT
