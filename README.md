# ANPR-System-v0.8 (Web-first, standalone streaming refactor)

![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)
![Web UI](https://img.shields.io/badge/UI-Web--only-4CAF50.svg)
![Streaming](https://img.shields.io/badge/Streaming-Standalone%20HLS-orange.svg)
![Detection](https://img.shields.io/badge/Detection-YOLOv8-red.svg)
![OCR](https://img.shields.io/badge/OCR-CRNN-orange.svg)
![Data](https://img.shields.io/badge/Data-SQLite%20%2B%20PostgreSQL-lightgrey.svg)

Web-first сервис для автоматического распознавания номерных знаков.
Инференс, OCR, декодинг, постобработка и live preview выполняются **на сервере**.

---

## Текущий статус репозитория

Проект находится в переходном состоянии.

Что уже работает:
- API сервис `apps/api/main.py`.
- Web UI `apps/web/index.html`.
- Runtime независимых ANPR-каналов.
- SSE-поток событий `GET /api/events/stream`.
- Retention / export / data lifecycle.
- Video Gateway с HLS preview.

Что требует рефакторинга:
- из продуктовой архитектуры должен быть удалён внешний медиасервер;
- WebRTC adapter path не должен быть обязательной частью live preview;
- lifecycle распознавания и lifecycle видеопревью должны быть связаны;
- UI не должен зависеть от ручного `localhost:8091`;
- ошибки video pipeline должны быть видимыми и диагностируемыми.

> Важный принцип: проект должен работать как **самостоятельная система**, без обязательного внешнего video/SFU/media server.

---

## Целевая архитектура

### Основная идея

В системе остаются только собственные сервисы проекта:
- `apps/api` — основной API, бизнес-логика, lifecycle каналов;
- `apps/video_gateway` — встроенный сервер live preview на базе FFmpeg + HLS;
- `apps/worker` — retention / export / фоновое обслуживание;
- `apps/web` — операторская панель;
- `packages/anpr_core` и `anpr/*` — runtime, CV/OCR и доменная логика.

### Целевой video path

```text
Camera / RTSP / file source
        │
        ├──> ANPR runtime (decode / detect / OCR / postprocess)
        │
        └──> Built-in Video Gateway (FFmpeg -> HLS)
                      │
                      └──> Web UI (hls.js / native HLS)
```

### Что исключается из продуктового пути

- внешний MediaMTX / go2rtc / SFU как обязательный компонент;
- WebRTC adapter через внешний WHEP endpoint как обязательный live path;
- ручное управление превью отдельно от канала, если канал уже запущен через API.

---

## Архитектурные правила

1. В браузер не переносить decode, inference, OCR или CV.
2. Каналы должны обрабатываться независимо друг от друга.
3. Live preview должен собираться только внутри проекта.
4. При старте канала ANPR live preview должен стартовать автоматически, если preview включён.
5. При остановке канала должны корректно останавливаться и ANPR runtime, и video session.
6. UI должен по умолчанию использовать тот же origin или конфиг, полученный от API, а не жёстко прошитый localhost.
7. Ошибки FFmpeg и video gateway не должны проглатываться молча.
8. HLS является основным и обязательным live transport.
9. WebRTC может существовать только как будущая необязательная внутренняя возможность, но не как зависимость от внешнего сервера.
10. Любые изменения API и структуры проекта должны документироваться в этом README и в `AGENTS.md`.

---

## Цели текущего этапа рефакторинга

### 1. Сделать streaming полностью standalone
- убрать зависимость от `mediamtx` и внешнего signaling/media path;
- убрать обязательные WebRTC-конфиги из compose и runtime;
- оставить встроенный HLS как основной live preview.

### 2. Связать lifecycle канала и lifecycle превью
- `POST /api/channels/{id}/start` должен запускать не только ANPR runtime, но и video preview;
- `POST /api/channels/{id}/stop` должен останавливать оба процесса;
- `POST /api/channels/{id}/restart` должен согласованно перезапускать оба контура.

### 3. Исправить UX и конфигурацию UI
- не использовать жёсткий `http://localhost:8091` как дефолт для production path;
- показывать статус превью и явные ошибки;
- не скрывать проблемы video gateway пустыми `catch`.

### 4. Улучшить наблюдаемость
- health/status endpoints должны показывать реальное состояние превью;
- должны появиться причины ошибок: source open failed, ffmpeg missing, playlist timeout, unsupported source и т.д.;
- при старте стрима должна быть проверка фактического появления HLS playlist.

---

## Ожидаемое состояние после рефакторинга

### Live preview
- встроенный HLS preview работает без внешнего медиасервера;
- UI показывает видео по каждому активному каналу;
- для тайлов доступны профили качества `low / medium / high`;
- профили переключаются через API video gateway или единый API слой.

### API / lifecycle
- API канала остаётся главным входом управления;
- video gateway может остаться отдельным сервисом, но не отдельной бизнес-сущностью для оператора;
- оператор не должен вручную инициировать старт превью вне обычного старта канала.

### Развёртывание
- Docker Compose поднимает только сервисы проекта и PostgreSQL;
- внешний video server не нужен;
- локальный запуск остаётся простым и воспроизводимым.

---

## Рекомендуемая структура ответственности

### `apps/api`
Отвечает за:
- CRUD каналов;
- start / stop / restart каналов;
- настройки OCR / filter / ROI / controllers;
- health / telemetry / events;
- координацию video preview lifecycle.

### `apps/video_gateway`
Отвечает за:
- запуск и остановку FFmpeg-процессов для preview;
- генерацию HLS playlist и segment-файлов;
- переключение профилей качества;
- health и diagnostics preview-процессов.

### `apps/web`
Отвечает за:
- отображение состояния каналов;
- отображение HLS live tiles;
- показ ошибок preview;
- переключение профилей качества;
- отсутствие хардкода на `localhost` в production path.

### `apps/worker`
Отвечает за:
- retention / cleanup / export;
- обработку фоновых задач жизненного цикла данных.

---

## Требования к реализации video preview

### Источники
Поддерживаемые источники должны быть явно определены.
Минимально допустимо:
- RTSP;
- локальные/сетевые файлы, если они уже поддерживаются проектом.

Если какие-то типы источников не поддерживаются preview-контуром, это должно быть:
- валидировано заранее;
- явно отражено в ошибке API/UI.

### FFmpeg
- запуск FFmpeg должен логироваться;
- stderr не должен полностью теряться;
- при неудачном старте должен возвращаться диагностируемый статус;
- при остановке процессы должны корректно завершаться и не оставлять мусорных сессий.

### HLS
- preview считается успешным только после появления валидного `index.m3u8`;
- URL preview должен быть пригоден для браузера без ручного редактирования;
- относительные URL предпочтительнее абсолютных, если сервисы находятся за одним reverse proxy.

---

## Целевой Docker Compose

В целевом состоянии compose должен содержать только:
- `api`
- `video_gateway`
- `retention_worker`
- `postgres`

`mediamtx` и иные внешние video-компоненты должны быть удалены из основного пути.

---

## Целевые API-правила

### Основное
Существующие endpoint-ы по возможности сохраняются:
- `GET /api/channels`
- `POST /api/channels`
- `PUT /api/channels/{id}`
- `DELETE /api/channels/{id}`
- `POST /api/channels/{id}/start`
- `POST /api/channels/{id}/stop`
- `POST /api/channels/{id}/restart`
- `GET /api/events`
- `GET /api/events/stream`

### Preview / diagnostics
Допустимо добавить или улучшить:
- `GET /video/health`
- `GET /video/channels`
- `POST /video/channels/{id}/start`
- `POST /video/channels/{id}/stop`
- `POST /video/channels/{id}/profile`
- `GET /video/channels/{id}/status`
- `GET /video/channels/{id}/diagnostics`

WebRTC-specific endpoints должны быть либо удалены из продуктового пути, либо помечены как deprecated/optional.

---

## Минимальные критерии приёмки

Задача считается выполненной, если:
1. Запущенный канал показывает live video в UI.
2. Для работы live video не нужен MediaMTX или иной внешний видеосервер.
3. `docker compose up --build` поднимает рабочую standalone-схему.
4. `POST /api/channels/{id}/start` запускает и распознавание, и preview.
5. `POST /api/channels/{id}/stop` останавливает и распознавание, и preview.
6. UI не зависит от ручного `localhost:8091`.
7. Ошибки video preview видны в API/UI и пригодны для диагностики.
8. README и `AGENTS.md` соответствуют новой архитектуре.

---

## Быстрый запуск после завершения рефакторинга

### Локально
```bash
uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
uvicorn apps.video_gateway.main:app --host 0.0.0.0 --port 8091
uvicorn apps.worker.main:app --host 0.0.0.0 --port 8092
```

### Docker Compose
```bash
cd infra
docker compose up --build
```

Ожидаемые точки входа:
- Web UI / API: `http://localhost:8080`
- Video Gateway health: `http://localhost:8091/video/health`
- Worker health: `http://localhost:8092/worker/health`

---

## Ограничения и дальнейшие шаги

- На текущем этапе приоритет — **надёжный standalone HLS preview**.
- Сначала нужно устранить архитектурную зависимость от внешнего медиасервера.
- Только после этого имеет смысл обсуждать внутренний low-latency path, если он действительно нужен продукту.
- PostgreSQL migration path и data lifecycle остаются отдельной задачей и не должны ломаться этим рефакторингом.

---

## Статус этапов

- ✅ Web-only продуктовый путь
- ✅ Server-side ANPR runtime
- ✅ SSE events
- ✅ Data lifecycle / retention / export
- ✅ HLS preview как база
- 🔄 Рефакторинг в standalone streaming architecture без внешнего медиасервера
- 🔄 Сцепление API lifecycle и video lifecycle
- 🔄 Диагностика и UX ошибок preview
