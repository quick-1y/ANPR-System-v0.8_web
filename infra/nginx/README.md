# Nginx (план)

Reverse-proxy маршрутизация:
- `/` -> `apps/web` + `apps/api`
- `/api/channels/*/preview.mjpg` -> `apps/api` (multipart MJPEG preview)
- `/worker/*` -> `apps/worker` (ограничить доступ в prod)
- SSE/WebSocket проксирование для live событий

Важно: standalone-режим не требует внешнего media/signaling server.
