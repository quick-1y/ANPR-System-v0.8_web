# Retention Worker Service

Retention worker запускается только внутри Docker Compose как сервис `retention_worker`.

## Запуск

```bash
docker compose up -d --build retention_worker
```

## Endpoints

- Внутри docker-сети: `http://retention_worker:8092/worker/health`
- Через nginx на хосте: `http://localhost:${HTTP_PORT:-8080}/worker/health`
- `POST /worker/retention/run`
