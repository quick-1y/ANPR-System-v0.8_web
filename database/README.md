# database/

Каталог `database/` содержит артефакты PostgreSQL для Docker-only развёртывания.

## Содержимое

- `postgres/schema.sql` — SQL-схема и индексы для таблиц ANPR.

## Важно

- Схема подключается автоматически через `docker-compose.yml` в контейнере `postgres`.
- Здесь **не** размещается Python-код приложения и бизнес-логика.
- Runtime-код доступа к БД остаётся в пакетах приложения (`anpr/`, `app/`, `packages/`).
