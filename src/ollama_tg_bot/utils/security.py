from __future__ import annotations

from aiogram.enums import ChatType
from aiogram.types import Message

from ..config import Settings


def is_allowed(settings: Settings, message: Message) -> bool:
  if settings.allow_all: return True

  chat = message.chat
  user = message.from_user

  if chat.type == ChatType.PRIVATE:
    return bool(user and user.id in settings.allowed_user_ids)

  if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
    return chat.id in settings.allowed_group_ids

  return False
