# XoriBot

Лёгкий Telegram-бот-собеседник, который напрямую обращается к локальной Ollama API через `/api/chat`, поддерживает персоны и отдельный web-search через SearXNG.

## Возможности

- личные сообщения от разрешённых пользователей;
- групповые текстовые сообщения только из разрешённых групп и только по mention, reply на бота или адресной команде;
- короткий in-memory контекст по чату;
- ограничение истории и размера контекста;
- команды `/start`, `/help`, `/reset`, `/new`, `/status`, `/model`, `/models`, `/agents`, `/ping`;
- персоны через псевдо-теги из `personas.yaml`, например `@xori` и `@web`;
- streaming-ответы через Ollama `/api/chat`;
- создание Word `.docx` по JSON-разметке, которую сразу генерирует модель;
- безопасные сообщения об ошибках Ollama без stack trace пользователю.
- автоматическая расшифровка аудио в разрешённых группах, супергруппах и топиках.

## Настройка

Скопируй `.env.example` в `.env` и заполни значения:

```env
TELEGRAM_BOT_TOKEN=123456:telegram-token
TELEGRAM_PROXY_URL=socks5://127.0.0.1:1080
SERVICE_MESSAGE_ID=1039572834
SERVICE_MESSAGE_THREAD_ID=
PERSONAS_CONFIG_PATH=personas.yaml
OLLAMA_BASE_URL=http://localhost:11434
WEB_SEARCH_BASE_URL=http://searxng:8080
WHISPER_BASE_URL=http://whisper:8000
BOT_USERNAME=your_bot_username
ALLOWED_USER_IDS=1039572834
ALLOWED_GROUP_IDS=-1003991214476
```

`ALLOWED_USER_IDS` и `ALLOWED_GROUP_IDS` задаются через запятую. По умолчанию бот не отвечает никому вне allowlist.

`TELEGRAM_PROXY_URL` нужен только для доступа к Telegram Bot API через прокси. Поддерживаются URL в формате `http://user:pass@host:port`, `socks4://host:port` и `socks5://host:port`. В Docker для прокси на host machine обычно указывай `host.docker.internal` вместо `127.0.0.1`.

`TELEGRAM_PARSE_MODE` по умолчанию равен `HTML`. Бот конвертирует обычный Markdown модели (`**bold**`, `### title`, ссылки и code blocks) в Telegram HTML. Если Telegram не примет разметку, бот автоматически повторяет отправку/редактирование этого сообщения без parse mode, чтобы ответ не обрывался.

`TELEGRAM_STREAM_EDIT_INTERVAL_MS` ограничивает частоту обновления streaming-сообщения. Минимум в коде — `5000` мс, потому меньшие значения легко приводят к Telegram flood control на `editMessageText`.

`ALLOW_ALL`, `REQUIRE_MENTION_IN_GROUPS`, `LOG_MESSAGE_TEXT`, `MAX_HISTORY_MESSAGES`, `MAX_INPUT_CHARS`, `MAX_CONTEXT_CHARS`, `MAX_TELEGRAM_MESSAGE_CHARS`, `WEB_SEARCH_MAX_RESULTS`, `WEB_SEARCH_TIMEOUT_SECONDS`, `REQUEST_TIMEOUT_SECONDS`, `TELEGRAM_PARSE_MODE` и `TELEGRAM_STREAM_EDIT_INTERVAL_MS` можно задать через env, если нужно переопределить дефолты. В `.env.example` они не вынесены специально, чтобы рабочий `.env` оставался коротким.

`tg-thinking` сейчас не используется: Telegram возвращал `RICH_MESSAGE_BLOCK_UNSUPPORTED` для такого блока в обычном rich-message вызове, поэтому бот отправляет простой placeholder `...` и потом редактирует его.

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
    model: qwen25-7b
    options: {}
    tools:
      - docx
    system_prompt: >
      Ты лаконичный и полезный Telegram-собеседник.

  web-research:
    name: Web Research
    tags:
      - "@web"
    model: qwen25-7b
    options:
      num_ctx: 4096
      num_predict: 2048
      temperature: 0.2
      top_p: 0.95
      top_k: 20
      num_thread: 12
    tools:
      - web_search
    system_prompt: >
      Ты web-research ассистент.
```

Бот перечитывает `personas.yaml` на лету при изменении файла. Можно менять вложенные поля вроде `system_prompt`, `model`, `options`, `tools`, `tags` без рестарта.

`options` передаётся напрямую в Ollama `/api/chat` для конкретной персоны. Если `options: {}`, бот не отправляет sampling/контекстные overrides и использует параметры самой Ollama-модели.

Маршрутизация идёт только через `@`-теги:

```text
@xori объясни проще
@web найди актуальную информацию
```

`@xori` и `@web` — это псевдо-теги в тексте, а не настоящие Telegram usernames. В группах бот должен получать такие сообщения: либо отключи BotFather privacy mode, либо пиши тег в reply на сообщение бота, либо используй настоящий mention бота вместе с псевдо-тегом.

У каждой персоны отдельная история диалога. `/status @web`, `/model @web`, `/models @web`, `/reset @web` работают с web-research сессией.

Если у персоны есть `tools: [web_search]`, бот делает запрос в SearXNG и добавляет результаты в prompt только для текущего ответа. Эти snippets не сохраняются в историю.

Если у персоны есть `tools: [docx]`, бот добавляет в prompt контракт для Word-документа. Когда пользователь просит `.docx`, модель должна вернуть короткий обычный ответ и fenced-блок `xoridocx` с JSON-разметкой: `filename`, `title`, `properties`, `blocks`. Поддерживаются блоки `heading`, `paragraph`, `list`, `table`, `page_break`; inline-разметка идёт через `runs` с `bold`, `italic`, `underline`. Бот не придумывает структуру документа сам, а только валидирует JSON и отправляет готовый `.docx`.

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

Для распознавания аудио bot использует ffmpeg внутри контейнера и Whisper backend по `WHISPER_BASE_URL`.
Поддерживаются Telegram `voice`, `audio` и `document`, если документ выглядит как аудиофайл по mime-type или расширению.
Длинные записи режутся на части по `WHISPER_SEGMENT_SECONDS` (по умолчанию 600 секунд), и бот показывает промежуточный текст по мере обработки сегментов.
В разрешённых группах, супергруппах и топиках аудио расшифровывается без mention бота. Текстовые сообщения в группах по-прежнему требуют mention, reply, адресную команду или persona-tag.

Whisper-модели хранятся на хосте в `tools/whisper/models/hf-hub-cache` и примонтированы в контейнер Speaches как `/home/ubuntu/.cache/huggingface/hub`. Создай эту папку сам на deploy-сервере внутри project/deploy directory.

Пример:

```bash
mkdir -p tools/whisper/models/hf-hub-cache
chmod 0777 tools/whisper/models/hf-hub-cache
```

Если Speaches пишет `Model ... is not installed locally`, скачай модель один раз:

```bash
curl -X POST http://127.0.0.1:8000/v1/models/Systran/faster-whisper-small
```

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
    "model": "qwen25-7b",
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

## Ограничения

- контекст хранится только в памяти процесса;
- нет RAG или долгосрочной памяти;
- prompt содержит только короткий system prompt и ограниченную историю диалога.
