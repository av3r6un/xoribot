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


@dataclass(frozen=True)
class Settings:
  telegram_bot_token: str
  telegram_proxy_url: str | None
  ollama_base_url: str
  ollama_model: str
  bot_name: str
  bot_username: str | None
  allowed_user_ids: set[int]
  allowed_group_ids: set[int]
  allow_all: bool
  require_mention_in_groups: bool
  log_message_text: bool
  max_history_messages: int
  max_input_chars: int
  max_context_chars: int
  max_telegram_message_chars: int
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
      ollama_base_url=self.ollama_base_url,
      ollama_model=self.ollama_model,
      telegram_proxy_enabled=bool(self.telegram_proxy_url),
      bot_name=self.bot_name,
      bot_username=self.bot_username,
      allowed_users=len(self.allowed_user_ids),
      allowed_groups=len(self.allowed_group_ids),
      allow_all=self.allow_all,
      require_mention_in_groups=self.require_mention_in_groups,
      max_history_messages=self.max_history_messages,
      max_context_chars=self.max_context_chars,
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
    telegram_bot_token=token,
    telegram_proxy_url=os.getenv('TELEGRAM_PROXY_URL', '').strip() or None,
    ollama_base_url=os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/'),
    ollama_model=os.getenv('OLLAMA_MODEL', 'qwen-25-7b'),
    bot_name=os.getenv('BOT_NAME', 'Xori'),
    bot_username=bot_username or None,
    allowed_user_ids=_int_set('ALLOWED_USER_IDS'),
    allowed_group_ids=_int_set('ALLOWED_GROUP_IDS'),
    allow_all=_bool('ALLOW_ALL', False),
    require_mention_in_groups=_bool('REQUIRE_MENTION_IN_GROUPS', True),
    log_message_text=_bool('LOG_MESSAGE_TEXT', False),
    max_history_messages=_int('MAX_HISTORY_MESSAGES', 12),
    max_input_chars=_int('MAX_INPUT_CHARS', 4000),
    max_context_chars=_int('MAX_CONTEXT_CHARS', 12000),
    max_telegram_message_chars=_int('MAX_TELEGRAM_MESSAGE_CHARS', 3900),
    ollama_num_ctx=_int('OLLAMA_NUM_CTX', 4096),
    ollama_num_predict=_int('OLLAMA_NUM_PREDICT', 512),
    ollama_temperature=_float('OLLAMA_TEMPERATURE', 0.2),
    ollama_top_p=_float('OLLAMA_TOP_P', 0.95),
    ollama_top_k=_int('OLLAMA_TOP_K', 20),
    ollama_num_thread=_int('OLLAMA_NUM_THREAD', 12),
    request_timeout_seconds=_int('REQUEST_TIMEOUT_SECONDS', 300),
  )
