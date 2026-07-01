from __future__ import annotations

import asyncio
import logging
import re

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InputRichMessage, Message

from ..config import Settings
from .telegram_format import telegram_html


logger = logging.getLogger(__name__)


class TelegramSender:

  def __init__(self, bot: Bot, settings: Settings) -> None:
    self.bot = bot
    self.settings = settings

  async def answer(self, message: Message, text: str, parse_mode: str | None = None) -> Message:
    formatted_text, formatted_parse_mode = self.format_text(text, parse_mode)
    try:
      return await message.answer(formatted_text, parse_mode=formatted_parse_mode)
    except TelegramBadRequest as exc:
      if self.is_parse_error(exc):
        return await message.answer(text, parse_mode=None)
      raise
    except TelegramRetryAfter as exc:
      logger.warning('telegram send flood control chat_id=%s retry_after=%s', message.chat.id, exc.retry_after)
      await asyncio.sleep(exc.retry_after)
      return await message.answer(formatted_text, parse_mode=formatted_parse_mode)

  async def final_edit(self, message: Message, text: str) -> bool:
    parse_mode = self.settings.telegram_parse_mode if self.markdown_looks_complete(text) else None
    return await self.edit(message, text, parse_mode=parse_mode, wait_retry=True)

  async def edit(
    self,
    message: Message,
    text: str,
    parse_mode: str | None = None,
    wait_retry: bool = False,
  ) -> bool:
    formatted_text, formatted_parse_mode = self.format_text(text, parse_mode)
    if not self.has_telegram_text(formatted_text): return False
    try:
      await message.edit_text(formatted_text, parse_mode=formatted_parse_mode)
      return True
    except TelegramBadRequest as exc:
      if 'message is not modified' in str(exc).lower(): return False
      if self.is_parse_error(exc):
        return await self.edit(message, text, parse_mode=None, wait_retry=wait_retry)
      raise
    except TelegramRetryAfter as exc:
      logger.warning('telegram edit flood control chat_id=%s retry_after=%s', message.chat.id, exc.retry_after)
      if not wait_retry: return False
      await asyncio.sleep(exc.retry_after)
      return await self.edit(message, text, parse_mode=parse_mode, wait_retry=False)

  async def thinking_draft(self, message: Message) -> int | None:
    draft_id = id(message) % 2147483647 or 1
    if await self.rich_draft(message, draft_id, '<tg-thinking>Thinking...</tg-thinking>'):
      return draft_id
    return None

  async def rich_draft(self, message: Message, draft_id: int, html: str) -> bool:
    if not self.has_telegram_text(html): return False
    try:
      await self.bot.send_rich_message_draft(
        chat_id=message.chat.id,
        message_thread_id=message.message_thread_id,
        draft_id=draft_id,
        rich_message=InputRichMessage(html=html, skip_entity_detection=True),
      )
      return True
    except TelegramBadRequest as exc:
      logger.warning('telegram rich draft failed chat_id=%s error=%s', message.chat.id, exc)
      return False
    except TelegramRetryAfter as exc:
      logger.warning('telegram rich draft flood control chat_id=%s retry_after=%s', message.chat.id, exc.retry_after)
      await asyncio.sleep(exc.retry_after)
      return False

  def typing(self, message: Message) -> 'TypingLoop':
    return TypingLoop(self.bot, message.chat.id)

  @staticmethod
  def format_text(text: str, parse_mode: str | None) -> tuple[str, str | None]:
    if parse_mode != 'HTML': return text, parse_mode
    return telegram_html(text), parse_mode

  @staticmethod
  def has_telegram_text(text: str) -> bool:
    if not text.strip(): return False
    without_tags = re.sub(r'<[^>]*>', '', text)
    return bool(without_tags.strip())

  @staticmethod
  def split_for_telegram(text: str, limit: int) -> tuple[str, int]:
    part = text[:limit]
    split_at = max(part.rfind('\n'), part.rfind(' '))
    if split_at < limit // 2: split_at = limit
    return text[:split_at].strip(), split_at

  @staticmethod
  def is_parse_error(exc: TelegramBadRequest) -> bool:
    text = str(exc).lower()
    return (
      'parse entities' in text
      or "can't parse" in text
      or 'entity' in text
      or 'markdown' in text
    )

  @staticmethod
  def markdown_looks_complete(text: str) -> bool:
    if text.count('```') % 2: return False
    without_fences = re.sub(r'```.*?```', '', text, flags=re.S)
    if without_fences.count('`') % 2: return False
    if text.count('**') % 2: return False
    if text.count('__') % 2: return False

    balance = 0
    escaped = False
    for char in text:
      if escaped:
        escaped = False
        continue
      if char == '\\':
        escaped = True
        continue
      if char == '[':
        balance += 1
      elif char == ']':
        if balance <= 0: return False
        balance -= 1
    if balance: return False

    return True


class TypingLoop:

  def __init__(self, bot: Bot, chat_id: int) -> None:
    self.bot = bot
    self.chat_id = chat_id
    self.task: asyncio.Task | None = None

  async def __aenter__(self) -> 'TypingLoop':
    self.task = asyncio.create_task(self._run())
    return self

  async def __aexit__(self, exc_type, exc, tb) -> None:
    if self.task:
      self.task.cancel()
      try:
        await self.task
      except asyncio.CancelledError:
        pass

  async def _run(self) -> None:
    while True:
      await self.bot.send_chat_action(self.chat_id, ChatAction.TYPING)
      await asyncio.sleep(4)
