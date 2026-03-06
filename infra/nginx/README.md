# Nginx (план)

Здесь будут конфиги reverse-proxy для маршрутизации:
- `/` -> `apps/web` + `apps/api`
- `/hls` -> `apps/video_gateway`
- WebSocket/SSE проксирование для live событий
