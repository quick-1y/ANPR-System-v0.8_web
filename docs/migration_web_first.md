# Миграция ANPR-System-v0.8 в web-first архитектуру

## Этап 0. Аудит текущего состояния

### Что найдено
- `anpr/ui/*` + `app.py` — desktop UI слой на PyQt5, содержит orchestration каналов и часть lifecycle-логики.
- `anpr/workers/*` — runtime-слой обработки каналов (источники кадров, детекция, OCR, запись событий).
- `anpr/pipeline/*`, `anpr/detection/*`, `anpr/recognition/*`, `anpr/preprocessing/*`, `anpr/postprocessing/*` — reusable core-логика ANPR.
- `anpr/infrastructure/*` — настройки, хранилище событий, списки номеров, сетевые контроллеры.

### Mapping старых модулей -> новая архитектура
- `anpr/pipeline`, `anpr/detection`, `anpr/recognition`, `anpr/preprocessing`, `anpr/postprocessing` -> `packages/anpr-core` (доменный core).
- `anpr/workers` (частично) -> `apps/worker` / runtime каналов (в MVP: `packages/anpr_core/channel_runtime.py`).
- `anpr/infrastructure/storage.py`, `list_database.py`, `settings_manager.py` -> `apps/api` как data/adapters слой.
- `anpr/ui` + `app.py` -> deprecate; заменить на `apps/web`.

### Узкие места и риски
- Текущий lifecycle каналов жёстко связан с PyQt-сигналами в `ChannelWorker`.
- Инициализация моделей тяжёлая; при большом числе каналов нужен отдельный worker/process isolation.
- Видео-шлюз (WebRTC/HLS) отсутствует, поэтому live preview в браузере пока ограничен событиями.
- Требуется отдельная стратегия retention/rotation для архива медиа.

## Этап 1. Архитектурный план

### Целевая структура
```text
anpr-web/
├── apps/
│   ├── web/          # операторская web-панель
│   ├── api/          # HTTP API + SSE
│   └── worker/       # отдельные runtime workers (следующий этап)
├── packages/
│   └── anpr-core/    # бизнес-логика распознавания
├── infra/
│   ├── docker-compose.yml
│   ├── nginx/
│   └── k8s/
└── README.md
```

### Границы сервисов
- `apps/api`:
  - CRUD каналов;
  - ROI и channel settings;
  - lists API;
  - lifecycle control `start/stop/restart`;
  - health + events stream.
- `packages/anpr_core`:
  - независимая обработка каналов и генерация ANPR-событий.
- `apps/web`:
  - мониторинг каналов и live событий через SSE.

### API-контракты MVP
- `GET/POST/PUT/DELETE /api/channels`
- `POST /api/channels/{id}/start|stop|restart`
- `PUT /api/channels/{id}` (включая ROI)
- `GET/POST /api/lists`
- `GET/POST /api/lists/{id}/entries`
- `GET /api/events`
- `GET /api/events/stream` (SSE)
- `GET /api/health`

### Миграция БД без потери событий
- Используется существующая SQLite-схема `events` (`anpr/infrastructure/storage.py`) без destructive миграций.
- API работает поверх существующей базы (`settings.get_db_path()`), что сохраняет исторические события.
- Следующий шаг: вынести migration scripts для PostgreSQL + dual-write режим.

## Этапы 2-7 (план)
- Этап 2: вынести core в пакет `packages/anpr-core`, исключить зависимости от desktop UI.
- Этап 3: добавить telemetry endpoints + channel metrics.
- Этап 4: расширить web UI до полноценного конфигуратора.
- Этап 5: добавить Video Gateway (WebRTC + HLS + quality profiles).
- Этап 6: retention/rotation/export для событий и медиа.
- Этап 7: удалить desktop UI после достижения parity.

## Статус этапов
- ✅ Этап 0. Аудит проекта — выполнен.
- ✅ Этап 1. Архитектурный план — выполнен.
- ✅ Этап 2. Выделение ANPR Core Service (MVP-уровень) — выполнен.
- ✅ Этап 3. Event & Telemetry (SSE + health + channel metrics) — выполнен.
- ✅ Этап 4. Web UI MVP — выполнен.
- ✅ Этап 5. Video Gateway (HLS + quality profiles + WebRTC discovery-контракт) — выполнен в базовой версии.
- ✅ Этап 6. Data Layer и эксплуатация (retention/rotation/export) — выполнен.
- ✅ Этап 7. Удаление desktop UI и web-only переход — выполнен.

## Следующие этапы (после текущего)
1. Усилить dual-write: retry/backoff/metrics/алерты рассинхронизации.
2. Провести rolling migration SQLite -> PostgreSQL на окружениях.
3. Оптимизировать экспорт архивов: batch/chunk и фоновые задачи.


## Этап 6. Реализация data layer (выполнено)

### Что найдено
- В проекте отсутствовали эксплуатационные механизмы очистки и экспорта событий/медиа.
- Хранение событий уже централизовано в SQLite `events`, а скриншоты хранятся на диске.

### Что изменено
- Добавлен сервис `apps/api/data_lifecycle.py`:
  - retention по событиям БД (`events_retention_days`);
  - retention по медиафайлам (`media_retention_days`);
  - rotation медиа по лимиту размера (`max_screenshots_mb`);
  - экспорт в CSV и ZIP bundle (CSV + media).
- В `apps/api/main.py` добавлены endpoints:
  - `GET/PUT /api/data/policy`;
  - `POST /api/data/retention/run`;
  - `GET /api/data/export/events.csv`;
  - `POST /api/data/export/bundle`.
- Добавлен фоновый retention loop на startup API с интервалом `cleanup_interval_minutes`.
- Расширены storage defaults в `settings_schema.py` и добавлены `get_storage_settings/save_storage_settings` в `settings_manager.py`.
- В web UI добавлен блок Data Layer (ручной запуск retention и экспорт).

### Какие файлы добавлены/изменены
- Создан: `apps/api/data_lifecycle.py`.
- Изменены: `apps/api/main.py`, `apps/web/index.html`, `anpr/infrastructure/settings_schema.py`, `anpr/infrastructure/settings_manager.py`.

### Риски и ограничения
- Экспорт ZIP с media может быть тяжёлым на очень больших объёмах (нужен batch/chunk экспорт в следующей итерации).
- Для многосервисного продакшн-режима требуется вынести retention-задачи в отдельный scheduler/worker.


## Этап 7. Удаление desktop UI и web-only переход (выполнено)

### Что изменено
- Удалены desktop-артефакты: `app.py`, `anpr/ui/*`, `anpr/workers/*`.
- Удалена зависимость `PyQt5` из `requirements.txt`.
- Обновлены точки запуска: API, Video Gateway и отдельный retention worker.
- Retention scheduler вынесен из API в `apps/worker/main.py` (production-friendly separation).
- Подготовлен PostgreSQL-переход:
  - dual-write настройки в storage (`dual_write_enabled`, `postgres_dsn`);
  - dual-write sink `packages/anpr_core/event_sink.py`;
  - схема `infra/postgres/schema.sql`;
  - скрипт one-shot миграции `scripts/sync_sqlite_to_postgres.py`.

### Риски
- Для полноценного production dual-write нужна стратегия повторов/очередей и мониторинг рассинхронизации.
