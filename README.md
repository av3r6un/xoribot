# XoriBot

Лёгкий Telegram-бот-собеседник, который напрямую обращается к локальной Ollama API через `/api/chat`. Первый этап намеренно простой: без tools, web search, browser automation, subagents и тяжёлых agent frameworks.

## Возможности

- личные сообщения от разрешённых пользователей;
- групповые сообщения только из разрешённых групп и только по mention, reply на бота или адресной команде;
- короткий in-memory контекст по чату;
- ограничение истории и размера контекста;
- команды `/start`, `/help`, `/reset`, `/new`, `/status`, `/model`, `/models`, `/agents`, `/ping`;
- персоны через псевдо-теги из `personas.yaml`, например `@xori` и `@web`;
- streaming-ответы через Ollama `/api/chat`;
- безопасные сообщения об ошибках Ollama без stack trace пользователю.

## Настройка

Скопируй `.env.example` в `.env` и заполни значения:

```env
TELEGRAM_BOT_TOKEN=123456:telegram-token
TELEGRAM_PROXY_URL=socks5://127.0.0.1:1080
SERVICE_MESSAGE_ID=1039572834
SERVICE_MESSAGE_THREAD_ID=
PERSONAS_CONFIG_PATH=personas.yaml
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen-25-7b
WEB_SEARCH_BASE_URL=http://searxng:8080
BOT_USERNAME=your_bot_username
ALLOWED_USER_IDS=1039572834
ALLOWED_GROUP_IDS=-1003991214476
ALLOW_ALL=false
TELEGRAM_PARSE_MODE=Markdown
TELEGRAM_RICH_MESSAGES_ENABLED=true
TELEGRAM_THINKING_MARKDOWN=<tg-thinking>Думаю...</tg-thinking>
TELEGRAM_STREAM_EDIT_INTERVAL_SECONDS=5
```

`ALLOWED_USER_IDS` и `ALLOWED_GROUP_IDS` задаются через запятую. Если `ALLOW_ALL=false` и allowlist пустой, бот будет игнорировать сообщения.

`TELEGRAM_PROXY_URL` нужен только для доступа к Telegram Bot API через прокси. Поддерживаются URL в формате `http://user:pass@host:port`, `socks4://host:port` и `socks5://host:port`. В Docker для прокси на host machine обычно указывай `host.docker.internal` вместо `127.0.0.1`.

`TELEGRAM_PARSE_MODE=Markdown` включает базовое Telegram-форматирование ответов модели. Если модель часто отдаёт несовместимую Markdown-разметку, бот автоматически повторяет отправку/редактирование этого сообщения без parse mode, чтобы ответ не обрывался.

`TELEGRAM_RICH_MESSAGES_ENABLED=true` включает пробное использование Telegram Rich Messages: thinking-сообщение перед генерацией и финальный rich edit ответа. Если Telegram API или клиент не принимает rich message, бот откатывается на обычный text/Markdown.

`TELEGRAM_THINKING_MARKDOWN` задаёт rich-разметку для thinking-сообщения.

`TELEGRAM_STREAM_EDIT_INTERVAL_SECONDS` ограничивает частоту обновления streaming-сообщения. Если поставить слишком мало, Telegram может вернуть flood control.

`SERVICE_MESSAGE_ID` включает уведомление при каждом запуске бота. Это может быть Telegram user id, group id, channel id или публичный канал в формате `@channel_username`. Для канала бот должен быть админом, для пользователя пользователь должен сначала написать боту.

Для отправки в топик forum-группы укажи дополнительно:

```env
SERVICE_MESSAGE_ID=-1001234567890
SERVICE_MESSAGE_THREAD_ID=42
```

`SERVICE_MESSAGE_ID` — id самой группы, `SERVICE_MESSAGE_THREAD_ID` — id ветки/топика внутри группы.

Как узнать id топика:

1. Открой нужный топик в Telegram-группе.
2. Напиши туда любое сообщение боту или reply на сообщение бота.
3. В логах бота найди строку `incoming message chat_id=... thread_id=...`.
4. Значение `chat_id` положи в `SERVICE_MESSAGE_ID`, значение `thread_id` — в `SERVICE_MESSAGE_THREAD_ID`.

Если берёшь id из ссылки Telegram вида `https://t.me/c/1234567890/42/100`, то `42` обычно и есть id топика, а id группы для Bot API будет `-1001234567890`.

## Персоны

Персоны настраиваются в `personas.yaml`:

```yaml
default_persona: main

personas:
  main:
    name: Xori
    tags:
      - "@xori"
    model:
    tools: []
    system_prompt: >
      Ты лаконичный и полезный Telegram-собеседник.

  web-research:
    name: Web Research
    tags:
      - "@web"
    model:
    tools:
      - web_search
    system_prompt: >
      Ты web-research ассистент.
```

Бот перечитывает `personas.yaml` на лету при изменении файла. Можно менять вложенные поля вроде `system_prompt`, `model`, `tools`, `tags` без рестарта.

Маршрутизация идёт только через `@`-теги:

```text
@xori объясни проще
@web найди актуальную информацию
```

`@xori` и `@web` — это псевдо-теги в тексте, а не настоящие Telegram usernames. В группах бот должен получать такие сообщения: либо отключи BotFather privacy mode, либо пиши тег в reply на сообщение бота, либо используй настоящий mention бота вместе с псевдо-тегом.

У каждой персоны отдельная история диалога. `/status @web`, `/model @web`, `/models @web`, `/reset @web` работают с web-research сессией.

Если у персоны есть `tools: [web_search]`, бот делает запрос в SearXNG и добавляет результаты в prompt только для текущего ответа. Эти snippets не сохраняются в историю.

## Локальный запуск

```bash
uv sync
uv run main.py
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

## Tools

SearXNG для будущего web-search живёт отдельно:

```bash
cd tools/searxng
cp .env.example .env
docker network create xoribot-tools
docker compose up -d
```

После запуска JSON API будет доступен на `http://127.0.0.1:8081/search?q=test&format=json`.

Чтобы `@web` использовал этот SearXNG из локального запуска без Docker:

```env
WEB_SEARCH_BASE_URL=http://127.0.0.1:8081
```

Если XoriBot запущен в Docker:

```env
WEB_SEARCH_BASE_URL=http://searxng:8080
```

Оба compose-файла подключаются к external network `xoribot-tools`, поэтому её нужно создать один раз.

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
    "stream": true,
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

`/models` — получить список моделей из Ollama и выбрать модель для текущей сессии.

`/agents` — показать доступные персоны.

`/ping` — быстрый ответ без обращения к Ollama.

В группах используй адресные команды, например `/status@your_bot_username`, или reply на сообщение бота.

## Ограничения первого этапа

- контекст хранится только в памяти процесса;
- нет tools/function calling;
- нет web search;
- нет RAG или долгосрочной памяти;
- prompt содержит только короткий system prompt и ограниченную историю диалога.
