# ANPR System - Automatic Number Plate Recognition

![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)
![Web UI](https://img.shields.io/badge/UI-Web--only-4CAF50.svg)
![YOLOv8](https://img.shields.io/badge/Detection-YOLOv8-red.svg)
![CRNN](https://img.shields.io/badge/OCR-CRNN-orange.svg)
![SQLite/PostgreSQL](https://img.shields.io/badge/Data-SQLite%20%2B%20PostgreSQL-lightgrey.svg)

Web-first система автоматического распознавания автомобильных номеров с server-side обработкой многоканального видео, backend API и операторской web-панелью.

## Основные возможности

- **Многоканальная обработка** — независимый runtime для каждого канала
- **Server-side ANPR pipeline** — детекция, OCR, постобработка и сохранение событий выполняются на сервере
- **Web-интерфейс оператора** — просмотр каналов, статусов, событий, ROI и списков
- **Live-события** — поток обновлений через SSE
- **Video Gateway** — HLS preview, профили качества `low / medium / high`
- **Управление каналами** — запуск, остановка, перезапуск и изменение параметров через API
- **ROI и фильтрация** — настройка зоны распознавания и рабочих параметров канала
- **Списки номеров** — белые/черные списки и логика принятия решений
- **Data lifecycle** — retention, очистка, экспорт CSV/ZIP
- **Подготовка к PostgreSQL** — dual-write и миграция из SQLite

## Архитектура

Проект разделён на несколько сервисов:

- **API service** — основной backend и web UI
- **Video Gateway** — live preview и управление видеопотоками
- **Worker** — фоновые задачи хранения и retention
- **ANPR Core** — распознавание, OCR, трекинг и обработка событий

Схема на уровне компонентов:

```text
Web UI
  │
  ▼
API Service (FastAPI)
  │
  ├── Channel lifecycle / ROI / lists / events
  ├── SSE stream
  ├── Data lifecycle
  │
  ├── ANPR Core
  │     ├── Detection
  │     ├── OCR
  │     ├── Postprocessing
  │     └── Channel runtime
  │
  └── Video Gateway
        ├── HLS preview
        └── Quality profiles / WebRTC adapter
```

## Технологический стек

- **Backend:** FastAPI, Uvicorn
- **Детекция:** YOLOv8
- **OCR:** CRNN
- **Видео:** OpenCV, HLS, WebRTC adapter path
- **Хранение:** SQLite по умолчанию, PostgreSQL для migration path / dual-write
- **ML stack:** PyTorch 2.8.0, torchvision 0.23.0, torchaudio 2.8.0, ultralytics 8.3.20

## Установка

### Предварительные требования

- Python 3.13
- pip
- ffmpeg

### Установка зависимостей

```bash
git clone https://github.com/quick-1y/ANPR-System-v0.8_web.git
cd ANPR-System-v0.8_web
```

# Установка зависимостей (выберите вариант под ваше железо)

# Для CPU:
```bash
pip install -r requirements.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
```
# Для CUDA 2.8.0:
```bash
pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
```
## Быстрый старт

### Локальный запуск

Откройте три отдельных терминала.

**1. API + Web UI**
```bash
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
```

**2. Video Gateway**
```bash
python -m uvicorn apps.video_gateway.main:app --host 0.0.0.0 --port 8091
```

**3. Worker**
```bash
python -m uvicorn apps.worker.main:app --host 0.0.0.0 --port 8092
```

### Точки доступа

- **Web UI / API:** `http://localhost:8080`
- **Video Gateway health:** `http://localhost:8091/video/health`
- **Worker health:** `http://localhost:8092/worker/health`

## Docker Compose

```bash
cd infra
docker compose up --build
```

Compose поднимает:

- `api`
- `video_gateway`
- `retention_worker`
- `mediamtx`
- `postgres`

## Хранение данных

- **По умолчанию:** SQLite
- **События:** база событий распознавания, метаданные, пути к кадрам и кропам номеров
- **Медиа:** скриншоты и кропы сохраняются на диск
- **Экспорт:** CSV / ZIP через data lifecycle API
- **PostgreSQL:** поддерживается как путь миграции и dual-write, но не является обязательным storage по умолчанию

## Структура проекта

```text
ANPR-System-v0.8_web/
├── apps/
│   ├── api/              # backend API и web entrypoint
│   ├── video_gateway/    # HLS / video service
│   ├── worker/           # retention и фоновые задачи
│   └── web/              # операторский web UI
├── packages/
│   └── anpr_core/        # channel runtime, event bus, sinks
├── anpr/                 # detection, OCR, preprocessing, postprocessing, infrastructure
├── infra/
│   ├── docker-compose.yml
│   ├── postgres/
│   ├── nginx/
│   └── k8s/
├── scripts/
│   └── sync_sqlite_to_postgres.py
├── config/
├── models/
├── requirements.txt
└── settings.json
```

## PostgreSQL migration

Если нужен переход на PostgreSQL:

1. Примените схему из `infra/postgres/schema.sql`
2. Синхронизируйте исторические данные через `scripts/sync_sqlite_to_postgres.py`
3. Включите dual-write в настройках storage

## Статус проекта

Текущая версия — **web-only ANPR system**. Desktop UI удалён, основной интерфейс работы теперь веб-панель.

## License

MIT
