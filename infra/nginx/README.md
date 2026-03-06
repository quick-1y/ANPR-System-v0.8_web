# Nginx (план)

Reverse-proxy маршрутизация:
- `/` -> `apps/web` + `apps/api`
- `/hls` -> `apps/video_gateway`
- `/worker/*` -> `apps/worker` (ограничить доступ в prod)
- `/webrtc/*` -> upstream медиасервер (MediaMTX/go2rtc) при необходимости
- SSE/WebSocket проксирование для live событий
