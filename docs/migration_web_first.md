# Миграция ANPR-System-v0.8 в web-first standalone архитектуру

## Обновление: встроенный live preview без внешнего media server

### Что было проблемой
- UI зависел от отдельного `video_gateway` и внешнего WebRTC provider path.
- В UI был захардкожен `videoBase=http://localhost:8091`, что ломало preview при любом non-localhost deploy.
- UI при каждом `refreshChannels` вызывал `POST /video/channels/{id}/start`, провоцируя restart loop preview-сессий.
- Snapshot endpoint в API открывал новый `cv2.VideoCapture` на каждый запрос, создавая параллельные RTSP consumers и конфликтуя с ANPR runtime.

### Что изменено
- Preview встроен в основной channel runtime (`packages/anpr_core/channel_runtime.py`):
  - runtime кэширует последний JPEG кадр;
  - добавлены метрики `preview_ready`, `preview_last_frame_at`.
- API теперь отдаёт preview напрямую:
  - `GET /api/channels/{id}/preview.mjpg`;
  - `GET /api/channels/{id}/preview/status`;
  - `GET /api/channels/{id}/snapshot.jpg` берёт кадр из runtime cache (без нового подключения к RTSP).
- Web UI переведён с HLS/video_gateway на встроенный MJPEG (`apps/web/index.html`):
  - удалены hardcoded `videoBase` и внешняя CDN-зависимость `hls.js`;
  - для каждой tile используется `api('/api/channels/{id}/preview.mjpg')`;
  - no-signal показывает реальную причину (`metrics.last_error`) вместо тихого fallback.
- `infra/docker-compose.yml` очищен от `video_gateway` и `mediamtx`.

### Результат
- Standalone deployment без внешнего media/signaling server.
- Single-ingest-per-channel для ANPR и preview.
- Диагностируемый preview state через channel metrics и preview status endpoint.
