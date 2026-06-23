from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


SYSTEM_PROMPT = (
  'Ты лаконичный и полезный Telegram-собеседник. Отвечай по существу, '
  'без лишних рассуждений. Если вопрос технический, давай практичный ответ.'
)


def _bool(name: str, default: bool = False) -> bool:
  value = os.getenv(name)
  if value is None: return default
  return value.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _int(name: str, default: int) -> int:
  value = os.getenv(name)
  if not value: return default
  return int(value)


def _float(name: str, default: float) -> float:
  value = os.getenv(name)
  if not value: return default
  return float(value)


def _int_set(name: str) -> set[int]:
  value = os.getenv(name, '')
  result: set[int] = set()
  for item in value.split(','):
    item = item.strip()
    if item: result.add(int(item))
  return result


def _chat_id(name: str) -> int | str | None:
  value = os.getenv(name, '').strip()
  if not value: return None
  try:
    return int(value)
  except ValueError:
    return value


def _optional_int(name: str) -> int | None:
  value = os.getenv(name, '').strip()
  if not value: return None
  return int(value)


@dataclass(frozen=True)
class Settings:
  app_version: str
  app_build_time: str | None
  app_git_sha: str | None
  telegram_bot_token: str
  telegram_proxy_url: str | None
  service_message_id: int | str | None
  service_message_thread_id: int | None
  personas_config_path: str
  ollama_base_url: str
  ollama_model: str
  bot_name: str
  bot_username: str | None
  allowed_user_ids: set[int]
  allowed_group_ids: set[int]
  allow_all: bool
  require_mention_in_groups: bool
  log_message_text: bool
  telegram_parse_mode: str | None
  telegram_rich_messages_enabled: bool
  telegram_thinking_markdown: str
  telegram_stream_edit_interval_seconds: float
  max_history_messages: int
  max_input_chars: int
  max_context_chars: int
  max_telegram_message_chars: int
  web_search_base_url: str | None
  web_search_max_results: int
  web_search_timeout_seconds: int
  ollama_num_ctx: int
  ollama_num_predict: int
  ollama_temperature: float
  ollama_top_p: float
  ollama_top_k: int
  ollama_num_thread: int
  request_timeout_seconds: int
  system_prompt: str = SYSTEM_PROMPT

  @property
  def safe_summary(self) -> dict:
    return dict(
      app_version=self.app_version,
      app_git_sha=self.app_git_sha,
      ollama_base_url=self.ollama_base_url,
      ollama_model=self.ollama_model,
      telegram_proxy_enabled=bool(self.telegram_proxy_url),
      service_messages_enabled=bool(self.service_message_id),
      service_message_thread_id=self.service_message_thread_id,
      personas_config_path=self.personas_config_path,
      bot_name=self.bot_name,
      bot_username=self.bot_username,
      allowed_users=len(self.allowed_user_ids),
      allowed_groups=len(self.allowed_group_ids),
      allow_all=self.allow_all,
      require_mention_in_groups=self.require_mention_in_groups,
      telegram_parse_mode=self.telegram_parse_mode,
      telegram_rich_messages_enabled=self.telegram_rich_messages_enabled,
      telegram_stream_edit_interval_seconds=self.telegram_stream_edit_interval_seconds,
      max_history_messages=self.max_history_messages,
      max_context_chars=self.max_context_chars,
      web_search_enabled=bool(self.web_search_base_url),
    )

  @property
  def ollama_options(self) -> dict:
    return dict(
      num_ctx=self.ollama_num_ctx,
      num_predict=self.ollama_num_predict,
      temperature=self.ollama_temperature,
      top_p=self.ollama_top_p,
      top_k=self.ollama_top_k,
      num_thread=self.ollama_num_thread,
    )


def load_settings() -> Settings:
  load_dotenv()

  token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
  if not token: raise RuntimeError('TELEGRAM_BOT_TOKEN is required')

  bot_username = os.getenv('BOT_USERNAME', '').strip()
  if bot_username.startswith('@'): bot_username = bot_username[1:]

  return Settings(
    app_version=os.getenv('APP_VERSION', 'local'),
    app_build_time=os.getenv('APP_BUILD_TIME', '').strip() or None,
    app_git_sha=os.getenv('APP_GIT_SHA', '').strip() or None,
    telegram_bot_token=token,
    telegram_proxy_url=os.getenv('TELEGRAM_PROXY_URL', '').strip() or None,
    service_message_id=_chat_id('SERVICE_MESSAGE_ID'),
    service_message_thread_id=_optional_int('SERVICE_MESSAGE_THREAD_ID'),
    personas_config_path=os.getenv('PERSONAS_CONFIG_PATH', 'personas.yaml'),
    ollama_base_url=os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/'),
    ollama_model=os.getenv('OLLAMA_MODEL', 'qwen-25-7b'),
    bot_name=os.getenv('BOT_NAME', 'Xori'),
    bot_username=bot_username or None,
    allowed_user_ids=_int_set('ALLOWED_USER_IDS'),
    allowed_group_ids=_int_set('ALLOWED_GROUP_IDS'),
    allow_all=_bool('ALLOW_ALL', False),
    require_mention_in_groups=_bool('REQUIRE_MENTION_IN_GROUPS', True),
    log_message_text=_bool('LOG_MESSAGE_TEXT', False),
    telegram_parse_mode=_parse_mode(os.getenv('TELEGRAM_PARSE_MODE', 'Markdown')),
    telegram_rich_messages_enabled=_bool('TELEGRAM_RICH_MESSAGES_ENABLED', True),
    telegram_thinking_markdown=os.getenv('TELEGRAM_THINKING_MARKDOWN', '<tg-thinking>Думаю...</tg-thinking>'),
    telegram_stream_edit_interval_seconds=_float('TELEGRAM_STREAM_EDIT_INTERVAL_SECONDS', 5),
    max_history_messages=_int('MAX_HISTORY_MESSAGES', 12),
    max_input_chars=_int('MAX_INPUT_CHARS', 4000),
    max_context_chars=_int('MAX_CONTEXT_CHARS', 12000),
    max_telegram_message_chars=_int('MAX_TELEGRAM_MESSAGE_CHARS', 3900),
    web_search_base_url=os.getenv('WEB_SEARCH_BASE_URL', '').strip().rstrip('/') or None,
    web_search_max_results=_int('WEB_SEARCH_MAX_RESULTS', 5),
    web_search_timeout_seconds=_int('WEB_SEARCH_TIMEOUT_SECONDS', 30),
    ollama_num_ctx=_int('OLLAMA_NUM_CTX', 4096),
    ollama_num_predict=_int('OLLAMA_NUM_PREDICT', 512),
    ollama_temperature=_float('OLLAMA_TEMPERATURE', 0.2),
    ollama_top_p=_float('OLLAMA_TOP_P', 0.95),
    ollama_top_k=_int('OLLAMA_TOP_K', 20),
    ollama_num_thread=_int('OLLAMA_NUM_THREAD', 12),
    request_timeout_seconds=_int('REQUEST_TIMEOUT_SECONDS', 300),
  )


def _parse_mode(value: str | None) -> str | None:
  value = (value or '').strip()
  if not value: return None
  if value.lower() == 'none': return None
  if value.lower() == 'markdownv2': return 'Markdown'
  return value
