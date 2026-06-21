# SearXNG Tool

Отдельный Docker Compose для локального SearXNG, который позже можно подключить к XoriBot как web-search backend.

## Запуск

```bash
cd tools/searxng
cp .env.example .env
docker compose up -d
```

Открыть в браузере:

```text
http://127.0.0.1:8081
```

Проверить JSON API:

```bash
curl -fsS 'http://127.0.0.1:8081/search?q=ollama&format=json'
```

`settings.yml` монтируется в контейнер как `/etc/searxng/settings.yml` и включает:

```yaml
search:
  formats:
    - html
    - json
```

Это нужно, чтобы SearXNG не отдавал `403` на `format=json`.

## URL для бота

Если бот запущен локально без Docker:

```env
WEB_SEARCH_BASE_URL=http://127.0.0.1:8081
```

Если бот запущен в Docker Compose на той же машине:

```env
WEB_SEARCH_BASE_URL=http://host.docker.internal:8081
```

## Переменные

`SEARXNG_HOST=0.0.0.0` нужен, если XoriBot запущен в Docker и ходит в SearXNG через `host.docker.internal`.

Если XoriBot запущен локально без Docker и внешний доступ к SearXNG не нужен, можно поставить:

```env
SEARXNG_HOST=127.0.0.1
```

`SEARXNG_PORT=8081` наружный порт. Внутри контейнера SearXNG слушает `8080`.

`server.secret_key` и `server.limiter` настраиваются в `settings.yml`. Перед публичным доступом замени `secret_key`, включи limiter и поставь reverse proxy.

Если раньше уже запускался старый compose с volume `searxng-config`, он больше не используется. Его можно удалить после остановки SearXNG:

```bash
docker volume rm xoribot-searxng_searxng-config
```

## Остановка

```bash
cd tools/searxng
docker compose down
```
