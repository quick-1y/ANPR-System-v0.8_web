# Kubernetes (план)

Манифесты для web-only архитектуры:
- Deployment/Service для API
- Deployment/Service для Video Gateway
- Deployment/Service для Retention Worker
- StatefulSet/Service для PostgreSQL
- Ingress для web + api + hls
- ConfigMap/Secrets для RTSP, storage policy и PostgreSQL DSN
