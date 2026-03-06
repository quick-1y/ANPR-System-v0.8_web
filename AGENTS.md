# ANPR Web-First Platform Instructions

Проект находится в состоянии **web-first сервисной архитектуры**.
Desktop UI удалён из продуктового пути.

## Цели текущей архитектуры
- Server-side обработка видео, CV, OCR и постобработки.
- Независимый lifecycle каждого канала.
- Web API + Web UI для операторов.
- Video Gateway: WebRTC (через адаптер к медиасерверу) + HLS.
- Data lifecycle: retention / rotation / export.

## Обязательные правила
1. Не переносить decode/CV/OCR/inference в браузер.
2. Сохранять независимую обработку каналов (изоляция lifecycle/очередей).
3. Не возвращать desktop-продуктовый путь.
4. Любые изменения архитектуры документировать в `README.md` (на русском).
5. Поддерживать консистентность конфигов между:
   - `anpr/infrastructure/settings_schema.py`
   - `anpr/infrastructure/settings_manager.py`
   - сервисами `apps/api`, `apps/worker`, `apps/video_gateway`.
6. Для WebRTC использовать реалистичный интеграционный путь (адаптер/прокси к внешнему SFU/медиасерверу), не discovery-заглушку.
7. Сохранять HLS путь как fallback для массового/архивного просмотра.

## PR и документация
- Все Pull Request сообщения — на русском.
- При добавлении/изменении алгоритмов и API обновлять `README.md` (на русском).
- Обновлять структуру проекта в `README.md` при изменении директорий/сервисов.

## Ключевые сервисы (текущие)
- `apps/api/main.py` — основной API (каналы, события, настройки, контроллеры, data lifecycle).
- `apps/video_gateway/main.py` — HLS + WebRTC adapter path.
- `apps/worker/main.py` — retention worker.
- `packages/anpr_core/*` — runtime каналов и доменные компоненты.

## Предпочтения реализации
- Небольшие инкрементальные изменения с проверкой работоспособности.
- Явные Pydantic-контракты API вместо невалидируемых payload where practical.
- Назад-совместимость существующих endpoint-ов по возможности.
