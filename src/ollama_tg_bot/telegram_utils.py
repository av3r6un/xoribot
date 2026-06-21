from __future__ import annotations

from aiogram.enums import ChatType
from aiogram.types import Message


def command_name(text: str | None) -> tuple[str, str | None] | None:
  if not text or not text.startswith('/'): return None
  first = text.split(maxsplit=1)[0][1:]
  if not first: return None
  if '@' in first:
    name, username = first.split('@', 1)
    return name.lower(), username.lower()
  return first.lower(), None


def is_addressed_command(text: str | None, bot_username: str | None) -> bool:
  command = command_name(text)
  if not command: return False
  _, username = command
  if not username: return False
  return bool(bot_username and username == bot_username.lower())


def strip_bot_mention(text: str, bot_username: str | None) -> str:
  if not bot_username: return text.strip()
  mention = f'@{bot_username}'
  return text.replace(mention, '').strip()


def is_reply_to_bot(message: Message, bot_id: int | None) -> bool:
  if not bot_id or not message.reply_to_message: return False
  user = message.reply_to_message.from_user
  return bool(user and user.id == bot_id)


def has_bot_mention(text: str | None, bot_username: str | None) -> bool:
  if not text or not bot_username: return False
  return f'@{bot_username.lower()}' in text.lower()


def should_answer_message(
  message: Message,
  bot_id: int | None,
  bot_username: str | None,
  require_mention_in_groups: bool,
  has_persona_tag: bool = False,
) -> bool:
  if message.chat.type == ChatType.PRIVATE: return True
  if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}: return False
  if is_addressed_command(message.text, bot_username): return True
  if is_reply_to_bot(message, bot_id): return True
  if has_bot_mention(message.text, bot_username): return True
  if has_persona_tag: return True
  return not require_mention_in_groups


def message_chunks(text: str, limit: int) -> list[str]:
  if len(text) <= limit: return [text]

  chunks: list[str] = []
  remaining = text
  while remaining:
    part = remaining[:limit]
    split_at = max(part.rfind('\n'), part.rfind(' '))
    if split_at < limit // 2: split_at = limit
    chunks.append(remaining[:split_at].strip())
    remaining = remaining[split_at:].strip()
  return [chunk for chunk in chunks if chunk]
