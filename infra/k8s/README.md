# Kubernetes (план)

Манифесты для web-only standalone архитектуры:
- Deployment/Service для API (включая встроенный live preview)
- Deployment/Service для Retention Worker
- StatefulSet/Service для PostgreSQL
- Ingress для web + api (+ SSE и MJPEG endpoints)
- ConfigMap/Secrets для RTSP, storage policy и PostgreSQL DSN

Важно: отдельный media server (MediaMTX/go2rtc и т.п.) не обязателен и не требуется базовой архитектурой.
