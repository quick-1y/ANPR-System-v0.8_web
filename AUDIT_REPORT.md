# Executive summary

Проект имеет рабочий web-only каркас (API + channel runtime + retention worker), но в кодовой базе есть подтверждённые артефакты незавершённой эволюции: «мертвый» path записи событий, частично неэкспонированные возможности слоя списков и перегруженный API entrypoint.

Критические для следующего цикла рефакторинга зоны:
1. Декомпозиция `app/api/main.py` (слишком много ответственности в одном модуле).
2. Удаление/деактивация старого event-writer path, уже заменённого активным runtime path.
3. Синхронизация README с фактической матрицей endpoint-ов и семантикой SSE.

---

# Confirmed issues

## 1) Тип: legacy
- **Статус:** CONFIRMED
- **Объект:** `anpr/infrastructure/event_writer.py::EventWriter`, `anpr/infrastructure/storage.py::AsyncEventDatabase`
- **Доказательство:**
  - Активный runtime path записывает события через `ChannelProcessor._sink: EventSink` → `EventSink.insert_event` → `PostgresEventDatabase.insert_event`.
    - Файлы/символы: `packages/anpr_core/channel_runtime.py::ChannelProcessor.__init__`, `packages/anpr_core/channel_runtime.py::_run_channel`, `packages/anpr_core/event_sink.py::EventSink.insert_event`.
  - `EventWriter` и `AsyncEventDatabase` не подключены к runtime/API/worker import-path (кроме self-contained ссылок внутри infra).
    - Файлы/символы: `anpr/infrastructure/event_writer.py`, `anpr/infrastructure/storage.py::AsyncEventDatabase`, результаты глобального поиска `rg`.
- **Почему это проблема:** поддерживаются два концептуально разных пути записи, но один фактически не участвует в runtime, создавая технический шум.
- **Что делать:** удалить `EventWriter` и `AsyncEventDatabase` после финальной grep-валидации и smoke-теста запуска API/worker.

## 2) Тип: unused
- **Статус:** CONFIRMED
- **Объект:** методы `ListDatabase`: `get_list`, `update_list`, `delete_list`, `delete_entry`, `export_lists`
- **Доказательство:**
  - Определены в `anpr/infrastructure/list_database.py`.
  - Поиск usages по репозиторию показывает только их определения, без вызовов.
  - API роуты для списков ограничены: `GET/POST /api/lists`, `GET/POST /api/lists/{list_id}/entries`.
    - Файлы/символы: `app/api/main.py` route registrations.
- **Почему это проблема:** слой инфраструктуры декларирует функционал, который не входит в текущий runtime/API path; повышает когнитивную сложность.
- **Что делать:** либо добавить недостающие API/UX сценарии, либо удалить эти методы как неиспользуемые внутри проекта.

## 3) Тип: architecture
- **Статус:** CONFIRMED
- **Объект:** `app/api/main.py` (god-file)
- **Доказательство:**
  - В одном модуле сосредоточены: Pydantic payloads, глобальная инициализация зависимостей, lifecycle hooks, роуты каналов/событий/debug/controllers/lists/settings/export, SSE генераторы, runtime orchestration.
  - Количество route registrations высокое и охватывает почти весь backend контракт.
- **Почему это проблема:** высокий blast radius изменений, слабая модульность, сложность точечного тестирования/ревью.
- **Что делать:** разделить на роутеры + сервисный слой + composition root.

## 4) Тип: architecture
- **Статус:** CONFIRMED
- **Объект:** import-time инициализация в `app/api/main.py` и `app/worker/main.py`
- **Доказательство:**
  - На уровне модуля создаются `SettingsManager`, DB клиенты, `ChannelProcessor`, `DataLifecycleService`, `RetentionScheduler`.
  - Это происходит до startup hooks FastAPI.
- **Почему это проблема:** ухудшает управляемость bootstrap/failure handling и тестируемость (особенно при недоступной БД/конфиге).
- **Что делать:** перенести создание зависимостей в startup-factory (или DI-контейнер), оставить минимальный import-time.

## 5) Тип: readme
- **Статус:** CONFIRMED
- **Объект:** описание SSE в README
- **Доказательство:**
  - README утверждает: `/api/events/stream` как «короткий SSE stream» с повторным подключением клиента.
  - Реализация: long-lived stream с keepalive ping (`while`, timeout ping, `text/event-stream`), пока нет disconnect/shutdown.
    - Файлы/символы: `README.md` (раздел «Что ещё важно знать»), `app/api/main.py::stream_events`.
- **Почему это проблема:** документация вводит в заблуждение по runtime-поведению.
- **Что делать:** заменить формулировку на long-lived SSE с keepalive и клиентским reconnect как fallback.

---

# Likely issues

## 1) Тип: structure
- **Статус:** LIKELY
- **Объект:** неполная матрица API в README
- **Доказательство:**
  - Есть роуты в API, которых нет в endpoint-списке README: `/api/storage/status`, `/api/telemetry/channels`, `/api/channels/last-plates`, единый роут `/api/events/item/{event_id}/media/{kind}`.
  - Автоматическое сравнение endpoint-строк API vs README подтверждает расхождения.
- **Почему это проблема:** документация не покрывает полный фактический контракт.
- **Что делать:** явно пометить endpoint-ы как `ui`, `external`, `ops/internal` и синхронизировать список.

## 2) Тип: architecture
- **Статус:** LIKELY
- **Объект:** shared OCR singleton в `anpr/pipeline/factory.py`
- **Доказательство:**
  - `build_components` использует `_get_shared_recognizer()` с глобальными `_RECOGNIZER_*`.
  - Каналы создают независимые pipeline/detector, но recognizer общий.
- **Почему это проблема:** потенциально ослабляет отказоизоляцию каналов (shared state/resource).
- **Что делать:** оценить переход к controlled pool/per-channel recognizer или добавить health/circuit-breaker вокруг singleton.

## 3) Тип: unused
- **Статус:** LIKELY
- **Объект:** `SettingsManager._settings_lock`
- **Доказательство:** одно вхождение — инициализация поля, без дальнейшего использования.
- **Почему это проблема:** ложный сигнал о дополнительном lock-механизме.
- **Что делать:** удалить поле после короткой валидации отсутствия side effects.

---

# Hypotheses requiring manual verification

## 1) Тип: architecture
- **Статус:** HYPOTHESIS
- **Объект:** поддержка camera source как числового индекса
- **Файлы/символы:** `README.md` (декларирует camera), `packages/anpr_core/channel_runtime.py::_open_capture`.
- **Чем доказано:** runtime передаёт `source` в `cv2.VideoCapture(source)` после `str(...)`; для части backend-ов OpenCV строка `'0'` и int `0` ведут себя по-разному.
- **Почему сомнение:** поведение зависит от платформы/сборки OpenCV.
- **Что делать:** вручную проверить на целевой ОС с USB-камерой; при необходимости нормализовать digit-string -> int.

## 2) Тип: structure
- **Статус:** HYPOTHESIS
- **Объект:** реально ли endpoint-ы `/api/storage/status`, `/api/telemetry/channels` используются внешними ops-инструментами
- **Файлы/символы:** `app/api/main.py` route registrations, `app/web/app.js` (нет usage `/api/telemetry/channels`).
- **Чем доказано:** внутри web UI usage не найден, но это не доказывает отсутствие внешних потребителей.
- **Почему сомнение:** возможны внешние мониторинги/интеграции вне репозитория.
- **Что делать:** проверить access-логи/контракт с операторами перед удалением или изменением.

---

# README mismatches

1) **Section:** `## REST / streaming endpoints`
- **Claim:** список endpoint-ов отражает API.
- **Actual code:** есть дополнительные API роуты, отсутствующие в README (`/api/storage/status`, `/api/system/resources`, `/api/channels/last-plates`, `/api/telemetry/channels`, а также различие в `media/{kind}` vs `media/frame|plate`).
- **Verdict:** **incomplete**.

2) **Section:** `## Что ещё важно знать`
- **Claim:** `/api/events/stream` — «короткий SSE stream».
- **Actual code:** long-lived SSE с ping keepalive и отключением по disconnect/shutdown.
- **Verdict:** **outdated**.

3) **Section:** диаграммы 1/2/4/5/6
- **Claim:** сервисные и runtime потоки.
- **Actual code:** ключевые контуры (API↔runtime↔PostgreSQL, preview MJPEG, worker retention, EventBus/SSE) соответствуют коду.
- **Verdict:** **не выявлено устаревания по основному потоку**.

4) **Section:** источники видеопотока (в т.ч. camera)
- **Claim:** поддержка camera source.
- **Actual code:** общая строковая передача источника в OpenCV; нет отдельной ветки/нормализации для camera index.
- **Verdict:** **unconfirmed** (нужно ручное runtime-тестирование).

---

# Deletion candidates

## safe to remove
- `anpr/infrastructure/event_writer.py::EventWriter` (если проект не имеет внешних импортёров вне текущего репозитория).
- `anpr/infrastructure/storage.py::AsyncEventDatabase` (вместе с удалением `EventWriter`).

## remove only after grep validation
- `SettingsManager._settings_lock` (проверка отражения/патчей внешних monkey-patch сценариев).
- Методы `ListDatabase`: `get_list`, `update_list`, `delete_list`, `delete_entry`, `export_lists` (убедиться, что нет внешних вызовов вне репозитория).

## do not remove, refactor first
- `app/api/main.py` (декомпозиция по модулям до чистки).
- Shared recognizer path в `anpr/pipeline/factory.py` (нужна архитектурная замена, не просто удаление).
- Ops/external endpoint-ы API без подтверждения отсутствия внешних клиентов.

---

# Evidence appendix

## Обязательные проверки (выполнено)

### 1) Repo tree
```bash
find . -maxdepth 3 -type d | sed 's#^./##' | sort
```
Подтверждена фактическая структура слоёв: `app/*`, `packages/anpr_core`, `anpr/*`, `controllers`, `database`, `nginx`.

### 2) Entry points и runtime paths
```bash
rg -n "uvicorn|FastAPI\(|@app\.on_event\(\"startup\"|RetentionScheduler|ChannelProcessor\(|threading.Thread\(" docker-compose.yml app/api/main.py app/worker/main.py packages/anpr_core/channel_runtime.py
```
- Entrypoints: `uvicorn app.api.main:app`, `uvicorn app.worker.main:app`.
- API startup: bootstrap channels.
- Worker startup: scheduler start.
- Channel runtime: отдельный `threading.Thread(name="channel-{id}")` на канал.

### 3) Все FastAPI routes
```bash
rg -n "@app\.(get|post|put|delete)\(" app/api/main.py app/worker/main.py
```
Получены полные route registrations API и worker.

### 4) Frontend fetch/EventSource
```bash
rg -n "fetch\(|EventSource\(" app/web/app.js
```
Подтверждены client-side вызовы (`/api/system/resources`, `/api/channels`, `/api/channels/last-plates`, `/api/events/stream`, `/api/debug/logs/stream`, и др.).

### 5) Imports/uses для suspect modules
```bash
rg -n "EventWriter|event_writer|AsyncEventDatabase|PostgresEventDatabase\(|EventSink\(" -g '*.py'
```
Показал активный path `ChannelProcessor -> EventSink -> PostgresEventDatabase` и изолированность `EventWriter/AsyncEventDatabase` от runtime.

### 6) Usages для suspect methods
```bash
rg -n "\.get_list\(|\.update_list\(|\.delete_list\(|\.delete_entry\(|\.export_lists\(|def get_list\(|def update_list\(|def delete_list\(|def delete_entry\(|def export_lists\(" -g '*.py'
```
Для `ListDatabase` методов найдены только определения, без вызовов.

### 7) Worker/scheduler entrypoints
```bash
rg -n "class RetentionScheduler|def start\(|def _loop\(|@app\.on_event\(\"startup\"\)|scheduler\.start\(|/worker/retention/run" app/worker/main.py README.md
```
Подтверждены scheduler loop, запуск на startup и ручной endpoint.

### 8) README vs code endpoint diff
```bash
python - <<'PY'
import re, pathlib
api=pathlib.Path('app/api/main.py').read_text()
readme=pathlib.Path('README.md').read_text()
routes=sorted(set(re.findall(r'@app\.(?:get|post|put|delete)\("([^"]+)"\)',api)))
md_eps=sorted(set(re.findall(r'`(?:GET|POST|PUT|DELETE)\s+([^`]+)`',readme)))
print('API routes count',len(routes))
print('README endpoints count',len(md_eps))
print('In API not in README:')
for m in [r for r in routes if r.startswith('/api/') and r not in md_eps]: print('-',m)
print('In README not in API:')
for e in [e for e in md_eps if e.startswith('/api/') and e not in routes]: print('-',e)
PY
```
Результат:
- API routes count: `37`
- README endpoints count: `36`
- In API not in README: `/api/channels/last-plates`, `/api/events/item/{event_id}/media/{kind}`, `/api/storage/status`, `/api/system/resources`, `/api/telemetry/channels`
- In README not in API: `/api/events/item/{event_id}/media/frame`, `/api/events/item/{event_id}/media/plate`
