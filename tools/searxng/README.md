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
curl 'http://127.0.0.1:8081/search?q=ollama&format=json'
```

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

`SEARXNG_HOST=127.0.0.1` оставляет SearXNG доступным только с host machine.

`SEARXNG_PORT=8081` наружный порт. Внутри контейнера SearXNG слушает `8080`.

`SEARXNG_SECRET` лучше заменить перед публичным доступом.

`SEARXNG_LIMITER=false` нормально для локального закрытого инструмента. Если будешь открывать наружу, включай limiter и reverse proxy.

## Остановка

```bash
cd tools/searxng
docker compose down
```
