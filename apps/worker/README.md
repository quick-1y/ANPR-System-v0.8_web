# Retention Worker Service

Отдельный сервис для production-режима, выполняющий циклы retention/rotation вне API-процесса.

## Запуск
```bash
uvicorn apps.worker.main:app --host 0.0.0.0 --port 8092
```

## Endpoints
- `GET /worker/health`
- `POST /worker/retention/run`
