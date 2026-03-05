# Этап 6 — Stabilization / Production Readiness

На этапе 6 добавлен инструмент стабильности для pre-production проверок и базовый runbook эксплуатации.

## Что реализовано

1. Новый пакет `anpr/stability/`:
   - `runner.py` — Stability Suite для smoke/load/degradation проверок.
   - `__main__.py` — CLI-запуск набора проверок.

2. Реализованные проверки:
   - **Health probe** сервисов `core`, `video_gateway`, `event_telemetry`.
   - **Load probe** публикации событий и расчёт `avg/p50/p95/max` latency + `error_rate`.
   - **Degradation probe**: имитация reconnect/timeout/latency деградации и проверка алертов.
   - **Soak mode**: длительный прогон (30–60 минут) с поминутными точками `latency/error_rate`.

3. Отчёты:
   - JSON-вывод с секциями `health`, `load`, `degradation` и итоговым `status`.
   - Для soak-режима — серия измерений (`series`) и агрегаты тренда (`trend`).

## Как запускать

### Базовый Stability Suite

```bash
python3 -m anpr.stability \
  --core-url http://127.0.0.1:8080/api/v1 \
  --video-url http://127.0.0.1:8090/api/v1 \
  --events-url http://127.0.0.1:8100/api/v1 \
  --requests 50
```

### Длительный soak-test (30 минут)

```bash
python3 -m anpr.stability \
  --mode soak \
  --soak-minutes 30 \
  --soak-interval-s 60 \
  --soak-requests 30 \
  --output reports/stability/soak_latest.json
```

## CI/CD (обязательный gate перед релизом)

- Workflow `.github/workflows/stability-gate.yml` запускается на `pull_request`, `push` в `main` и событие `release`.
- Gate поднимает `core`, `video_gateway`, `event_telemetry`, прогоняет Stability Suite и **падает**, если:
  - `status != ok`;
  - `load.error_rate >= 0.1`.
- Артефакты (`stability_gate_report.json` + логи сервисов) прикладываются к каждому запуску.

## Персистентные тренды latency/error-rate

- Workflow `.github/workflows/stability-soak-trends.yml` выполняет soak-тест по расписанию (ежедневно) или вручную.
- Скрипт `scripts/update_stability_trend.py`:
  - добавляет новый прогон в `reports/stability/soak_history.jsonl`;
  - пересобирает markdown-отчёт `reports/stability/soak_trends.md`.
- История коммитится обратно в репозиторий, что даёт постоянный historical baseline и удобное сравнение деградаций.

## Мини-runbook

1. Если `health.ok = false`:
   - проверить доступность endpoint-ов `health` каждого сервиса;
   - проверить логи запуска и порты bind (`0.0.0.0`/`127.0.0.1`).
2. Если `load.error_rate >= 0.1`:
   - снизить нагрузку по каналам/частоте polling;
   - проверить timeouts и сетевые лимиты.
3. Если `degradation.ok = false`:
   - проверить генерацию телеметрии с каналов;
   - проверить пороги алертов в Event & Telemetry Service.
4. Если в soak-трендах виден рост `latency_p95` или `error_rate`:
   - сравнить логи сервисов между последними стабильными и текущими прогонами;
   - временно снизить интенсивность потока событий и проверить состояние БД/сети.
