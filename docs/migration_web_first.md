# Миграция ANPR-System-v0.8 в web-first архитектуру

## Phase 1 — Аудит оставшихся gap-ов

### Найдено
- WebRTC path был только discovery/placeholder без рабочего SDP offer->answer прокси.
- Web UI оставался базовым MVP без полноценной операторской панели (tiles, детали событий, статусы).
- В API не хватало явных валидируемых контрактов для OCR/filter/controller.
- Dual-write частично присутствовал, но не имел явного API управления.
- Документация содержала устаревшие/противоречивые фрагменты.

### Что изменено
- Проведён рефакторинг API, Video Gateway и Web UI для закрытия перечисленных разрывов.

### Риски
- Для production WebRTC и dual-write всё ещё нужны расширенные контуры надёжности и observability.

---

## Phase 2 — WebRTC implementation path

### Изменения
- В `apps/video_gateway/main.py` добавлен рабочий WebRTC adapter path:
  - конфиг провайдера (`/video/webrtc/config`);
  - endpoint `POST /video/webrtc/{channel_id}/offer` (WHEP offer proxy к внешнему медиасерверу);
  - endpoint `GET /video/webrtc/{channel_id}` с конкретными URL и статусом.
- HLS fallback сохранён полностью.

### Файлы
- Изменён: `apps/video_gateway/main.py`.

### Риски
- Нужен внешний медиасервер (MediaMTX/go2rtc).

---

## Phase 3 — Web UI upgrade

### Изменения
- `apps/web/index.html` обновлён до операторского dashboard:
  - grid live tiles;
  - встроенный live preview (HLS tiles);
  - статусы каналов и ключевые метрики;
  - live events feed + event details panel;
  - controls для video profile;
  - блоки controller management и data lifecycle.

### Файлы
- Изменён: `apps/web/index.html`.

### Риски
- UI intentionally minimalistic, без полноценной role-based auth.

---

## Phase 4 — API completion

### Изменения
- Добавлены явные валидируемые контракты и endpoints:
  - `PUT /api/channels/{id}/ocr`
  - `PUT /api/channels/{id}/filter`
  - controller CRUD + test command
  - `GET /api/channels/{id}/health`
- Сохранена обратная совместимость с базовыми канал-эндпоинтами.

### Файлы
- Изменён: `apps/api/main.py`.

### Риски
- Часть legacy-полей каналов остаётся в mixed-config формате.

---

## Phase 5 — Config & storage hardening

### Изменения
- Добавлены explicit endpoints для dual-write конфигурации:
  - `GET /api/storage/dual-write`
  - `PUT /api/storage/dual-write`
- Обновление dual-write config делает reload runtime processor.
- Dual-write path связан через `settings_schema` -> `settings_manager` -> runtime sink.

### Файлы
- Изменены: `apps/api/main.py`, `anpr/infrastructure/settings_schema.py`, `packages/anpr_core/channel_runtime.py`, `packages/anpr_core/event_sink.py`.

### Риски
- Нужны retry/backoff/queue для production-grade dual-write.

---

## Phase 6 — Documentation and instruction cleanup

### Изменения
- README переписан в консистентное web-first состояние.
- AGENTS.md переписан под текущие цели репозитория.
- Убраны stale desktop-first указания.

### Файлы
- Изменены: `README.md`, `AGENTS.md`.

### Риски
- Требуется периодическая синхронизация docs с фактическими API при следующих итерациях.

---

## Текущий статус этапов
- ✅ Этап 0. Аудит
- ✅ Этап 1. Архитектурный план
- ✅ Этап 2. Выделение ANPR Core Service
- ✅ Этап 3. Event & Telemetry
- ✅ Этап 4. Web UI
- ✅ Этап 5. Video Gateway
- ✅ Этап 6. Data Layer
- ✅ Этап 7. Удаление desktop UI
- ✅ Пост-этапная доработка: WebRTC adapter + API contracts + docs consistency

## Следующие шаги
1. Добавить retry/backoff + метрики/алерты для dual-write.
2. Ввести authN/authZ для API/UI/worker.
3. Добавить полноценный E2E smoke для API+VideoGateway+Worker.
