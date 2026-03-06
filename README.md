# ANPR-System-v0.8 (Web-first)

![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)
![Web UI](https://img.shields.io/badge/UI-Web--only-4CAF50.svg)
![YOLOv8](https://img.shields.io/badge/Detection-YOLOv8-red.svg)
![CRNN](https://img.shields.io/badge/OCR-CRNN-orange.svg)
![SQLite/PostgreSQL](https://img.shields.io/badge/Data-SQLite%20%2B%20PostgreSQL-lightgrey.svg)

Web-first сервис для автоматического распознавания номерных знаков.
Инференс, OCR, декодинг и обработка видео выполняются **на сервере**.

---

## Что уже реализовано

- ✅ API сервис `apps/api/main.py` (каналы, lifecycle, ROI, списки, контроллеры, telemetry, data layer).
- ✅ SSE live events: `GET /api/events/stream`.
- ✅ Операторская web-панель `apps/web/index.html` с live-tiles и event details.
- ✅ Runtime независимых каналов `packages/anpr_core/channel_runtime.py`.
- ✅ Video Gateway `apps/video_gateway/main.py`:
  - HLS live preview;
  - профили качества `low/medium/high`;
  - WebRTC adapter path через WHEP offer proxy к внешнему медиасерверу.
- ✅ Data lifecycle:
  - retention / rotation / export;
  - отдельный retention worker `apps/worker/main.py`.
- ✅ Подготовка PostgreSQL миграции:
  - dual-write sink;
  - схема `infra/postgres/schema.sql`;
  - one-shot sync скрипт `scripts/sync_sqlite_to_postgres.py`.

---

## Быстрый запуск

### 1) Локально (три сервиса)

```bash
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
python -m uvicorn apps.video_gateway.main:app --host 0.0.0.0 --port 8091
python -m uvicorn apps.worker.main:app --host 0.0.0.0 --port 8092
```

- Web UI / API: `http://localhost:8080`
- Video Gateway health: `http://localhost:8091/video/health`
- Worker health: `http://localhost:8092/worker/health`

### 2) Docker Compose

```bash
cd infra
docker compose up --build
```

---

## Архитектура (текущая)

```text
ANPR-System-v0.8/
├── AGENTS.md
├── README.md
├── requirements.txt
├── settings.json
│
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   └── data_lifecycle.py
│   ├── video_gateway/
│   │   └── main.py
│   ├── web/
│   │   └── index.html
│   └── worker/
│       ├── main.py
│       └── README.md
│
├── packages/
│   └── anpr_core/
│       ├── channel_runtime.py
│       ├── event_bus.py
│       └── event_sink.py
│
├── anpr/
│   ├── detection/
│   ├── pipeline/
│   ├── recognition/
│   ├── preprocessing/
│   ├── postprocessing/
│   └── infrastructure/
│
├── infra/
│   ├── docker-compose.yml
│   ├── postgres/
│   │   └── schema.sql
│   ├── nginx/
│   └── k8s/
│
└── scripts/
    └── sync_sqlite_to_postgres.py
```

---

## API (основное)

### Каналы
- `GET /api/channels`
- `POST /api/channels`
- `PUT /api/channels/{id}`
- `DELETE /api/channels/{id}`
- `POST /api/channels/{id}/start|stop|restart`
- `PUT /api/channels/{id}/ocr` (валидируемый контракт OCR)
- `PUT /api/channels/{id}/filter` (валидируемый контракт фильтрации)
- `GET /api/channels/{id}/health`
- `GET /api/telemetry/channels`

### События
- `GET /api/events`
- `GET /api/events/stream` (SSE)

### Контроллеры
- `GET /api/controllers`
- `POST /api/controllers`
- `PUT /api/controllers/{id}`
- `DELETE /api/controllers/{id}`
- `POST /api/controllers/{id}/test`

### Data lifecycle
- `GET /api/data/policy`
- `PUT /api/data/policy`
- `POST /api/data/retention/run`
- `GET /api/data/export/events.csv`
- `POST /api/data/export/bundle`

### Storage / Dual-write
- `GET /api/storage/dual-write`
- `PUT /api/storage/dual-write`

### Video Gateway
- `GET /video/health`
- `GET /video/channels`
- `POST /video/channels/{id}/start|stop`
- `POST /video/channels/{id}/profile`
- `GET /video/webrtc/config`
- `PUT /video/webrtc/config`
- `POST /video/webrtc/{id}/offer` (WHEP adapter path, body: SDP `application/sdp`)
- `GET /video/webrtc/{id}`

---

## Конфигурация хранения

`settings.json -> storage`:

- `db_dir`, `database_file`
- `screenshots_dir`
- `auto_cleanup_enabled`
- `cleanup_interval_minutes`
- `events_retention_days`
- `media_retention_days`
- `max_screenshots_mb`
- `export_dir`
- `dual_write_enabled`
- `postgres_dsn`

---

## PostgreSQL migration path

1. Применить схему:
```bash
psql "$POSTGRES_DSN" -f infra/postgres/schema.sql
```

2. Синхронизировать исторические данные из SQLite:
```bash
python scripts/sync_sqlite_to_postgres.py --sqlite data/db/anpr.db --postgres-dsn "$POSTGRES_DSN"
```

3. Включить dual-write:
- `PUT /api/storage/dual-write`
- payload: `{ "dual_write_enabled": true, "postgres_dsn": "..." }`

---

## Ограничения и следующие шаги

- WebRTC реализован как адаптер-прокси (WHEP offer proxy) и требует внешнего медиасервера (например MediaMTX/go2rtc).
- Для production dual-write нужны retry/backoff, метрики и алерты рассинхронизации.
- Rolling migration SQLite -> PostgreSQL выполняется по окружениям с контролем консистентности.

---

## Статус этапов миграции

- ✅ Этап 0: аудит
- ✅ Этап 1: архитектурный план
- ✅ Этап 2: extraction core service
- ✅ Этап 3: event & telemetry
- ✅ Этап 4: web UI MVP -> upgraded dashboard
- ✅ Этап 5: video gateway (HLS + profiles + WebRTC adapter)
- ✅ Этап 6: data lifecycle (retention/rotation/export)
- ✅ Этап 7: web-only переход (desktop UI удалён)



## Troubleshooting: web страница не открывается

1. Проверьте, что API реально запущен в том же Python окружении:
```bash
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8080
```

2. Быстрая проверка доступности:
```bash
curl -i http://127.0.0.1:8080/
curl -i http://127.0.0.1:8080/api/health
```
Оба запроса должны вернуть `200 OK`.

3. Если `uvicorn` не найден, установите зависимости:
```bash
pip install -r requirements.txt
```

4. Если root URL открывается, но live tiles пустые — проверьте Video Gateway:
```bash
python -m uvicorn apps.video_gateway.main:app --host 127.0.0.1 --port 8091
curl -i http://127.0.0.1:8091/video/health
```

5. Для запуска WebRTC path нужен внешний медиасервер (MediaMTX/go2rtc) и доступный `ffmpeg`.

6. PowerShell важно: команды запуска сервисов нужно выполнять в **отдельных терминалах** (или через `Start-Process`), иначе первая команда блокирует выполнение следующих.
Пример:
```powershell
Start-Process python -ArgumentList "-m uvicorn apps.api.main:app --host 0.0.0.0 --port 8080"
Start-Process python -ArgumentList "-m uvicorn apps.video_gateway.main:app --host 0.0.0.0 --port 8091"
Start-Process python -ArgumentList "-m uvicorn apps.worker.main:app --host 0.0.0.0 --port 8092"
```

7. `GET /` на порту 8092 (worker) теперь возвращает сервисную информацию; рабочий health endpoint: `GET /worker/health`.
