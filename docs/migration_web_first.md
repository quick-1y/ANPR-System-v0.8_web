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
