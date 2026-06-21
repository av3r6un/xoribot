# XoriBot

Лёгкий Telegram-бот-собеседник, который напрямую обращается к локальной Ollama API через `/api/chat`. Первый этап намеренно простой: без tools, web search, browser automation, subagents и тяжёлых agent frameworks.

## Возможности

- личные сообщения от разрешённых пользователей;
- групповые сообщения только из разрешённых групп и только по mention, reply на бота или адресной команде;
- короткий in-memory контекст по чату;
- ограничение истории и размера контекста;
- команды `/start`, `/help`, `/reset`, `/new`, `/status`, `/model`, `/ping`;
- безопасные сообщения об ошибках Ollama без stack trace пользователю.

## Настройка

Скопируй `.env.example` в `.env` и заполни значения:

```env
TELEGRAM_BOT_TOKEN=123456:telegram-token
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen-25-7b
BOT_USERNAME=your_bot_username
ALLOWED_USER_IDS=1039572834
ALLOWED_GROUP_IDS=-1003991214476
ALLOW_ALL=false
```

`ALLOWED_USER_IDS` и `ALLOWED_GROUP_IDS` задаются через запятую. Если `ALLOW_ALL=false` и allowlist пустой, бот будет игнорировать сообщения.

## Локальный запуск

```bash
uv sync
uv run python -m ollama_tg_bot.main
```

Если используешь `pip`:

```bash
python -m venv .venv
. .venv/bin/activate
pip install .
python -m ollama_tg_bot.main
```

## Docker Compose

Для запуска в контейнере:

```bash
docker compose up --build
```

В Docker обычно удобно указывать:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

`docker-compose.yml` уже содержит `extra_hosts` для Linux.

## Проверка Ollama

```bash
curl -s http://localhost:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen-25-7b",
    "messages": [
      {
        "role": "user",
        "content": "Ответь одним коротким предложением: что такое Docker?"
      }
    ],
    "stream": false,
    "options": {
      "num_ctx": 4096,
      "num_predict": 128,
      "temperature": 0.2,
      "num_thread": 12
    }
  }'
```

## Команды

`/start` — проверить, что бот активен.

`/help` — показать список команд.

`/reset` — очистить историю текущей сессии.

`/new` — создать новую сессию.

`/status` — показать session_id, модель, размер истории, размер контекста, Ollama URL и uptime.

`/model` — показать текущую модель.

`/ping` — быстрый ответ без обращения к Ollama.

В группах используй адресные команды, например `/status@your_bot_username`, или reply на сообщение бота.

## Ограничения первого этапа

- контекст хранится только в памяти процесса;
- streaming отключён;
- нет tools/function calling;
- нет web search;
- нет RAG или долгосрочной памяти;
- prompt содержит только короткий system prompt и ограниченную историю диалога.
