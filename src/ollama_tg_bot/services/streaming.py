from __future__ import annotations

import logging
import time

from aiogram.enums import ChatType
from aiogram.types import Message

from ..config import Settings
from ..ollama_client import OllamaClient, OllamaError
from ..personas import Persona
from ..sessions import Session, SessionManager
from ..utils import TelegramSender, message_chunks, telegram_html
from .docx_tool import visible_docx_text


logger = logging.getLogger(__name__)


class ResponseStreamer:

  def __init__(
    self,
    settings: Settings,
    ollama: OllamaClient,
    sessions: SessionManager,
    sender: TelegramSender,
  ) -> None:
    self.settings = settings
    self.ollama = ollama
    self.sessions = sessions
    self.sender = sender

  async def stream(
    self,
    message: Message,
    session: Session,
    persona: Persona,
    tool_messages: list[dict] | None = None,
  ) -> str:
    if message.chat.type == ChatType.PRIVATE:
      draft_id = await self.sender.thinking_draft(message)
      if draft_id:
        return await self._stream_with_draft(message, draft_id, session, persona, tool_messages)

    return await self._stream_with_message(message, session, persona, tool_messages)

  async def _stream_with_message(
    self,
    message: Message,
    session: Session,
    persona: Persona,
    tool_messages: list[dict] | None = None,
  ) -> str:
    response = ''
    visible_text = ''
    sent_visible_chars = 0
    sent_message: Message | None = None
    last_edit_at = 0.0
    last_text = ''
    limit = min(self.settings.max_telegram_message_chars, 3900)
    edit_interval = self.settings.telegram_stream_edit_interval_ms / 1000

    messages = self.sessions.ollama_messages(session)
    if tool_messages:
      messages = messages[:1] + tool_messages + messages[1:]

    try:
      async for delta in self.ollama.stream_chat(messages, session.model, persona.options):
        response += delta
        full_visible_text = visible_docx_text(response)
        if sent_visible_chars > len(full_visible_text): sent_visible_chars = len(full_visible_text)
        visible_text = full_visible_text[sent_visible_chars:]

        while len(visible_text) >= limit:
          part, split_at = self.sender.split_for_telegram(visible_text, limit)
          sent_visible_chars += split_at
          visible_text = full_visible_text[sent_visible_chars:]
          if sent_message:
            await self.sender.final_edit(sent_message, part)
          else:
            await self.sender.answer(message, part, parse_mode=self.settings.telegram_parse_mode)
          sent_message = None
          last_edit_at = 0.0
          last_text = ''

        now = time.monotonic()
        text = visible_text.strip()
        if text and text != last_text and now - last_edit_at >= edit_interval:
          if sent_message:
            edited = await self.sender.edit(sent_message, text, parse_mode=self.settings.telegram_parse_mode)
            if edited:
              last_edit_at = now
              last_text = text
          else:
            sent_message = await self.sender.answer(message, text, parse_mode=self.settings.telegram_parse_mode)
            last_edit_at = now
            last_text = text
    except OllamaError as exc:
      if not response.strip(): raise
      final_text = visible_text.strip()
      if final_text:
        if sent_message:
          await self.sender.final_edit(sent_message, final_text)
        else:
          await self.sender.answer(message, final_text, parse_mode=self.settings.telegram_parse_mode)
      await self.sender.answer(message, f'Генерация прервалась: {exc.user_message}', parse_mode=None)
      logger.warning('ollama stream interrupted after partial response: %s', exc)
      return response.strip()

    final_text = visible_text.strip()
    if final_text:
      if sent_message:
        await self.sender.final_edit(sent_message, final_text)
      else:
        await self.sender.answer(message, final_text, parse_mode=self.settings.telegram_parse_mode)
    logger.info('telegram stream completed response_chars=%s final_chunk_chars=%s', len(response), len(final_text))
    return response.strip() or final_text

  async def _stream_with_draft(
    self,
    message: Message,
    draft_id: int,
    session: Session,
    persona: Persona,
    tool_messages: list[dict] | None = None,
  ) -> str:
    response = ''
    visible_text = ''
    last_draft_at = 0.0
    last_text = ''
    edit_interval = self.settings.telegram_stream_edit_interval_ms / 1000

    messages = self.sessions.ollama_messages(session)
    if tool_messages:
      messages = messages[:1] + tool_messages + messages[1:]

    try:
      async for delta in self.ollama.stream_chat(messages, session.model, persona.options):
        response += delta
        visible_text = visible_docx_text(response)

        now = time.monotonic()
        text = visible_text.strip()
        if text and text != last_text and now - last_draft_at >= edit_interval:
          if await self.sender.rich_draft(message, draft_id, telegram_html(text)):
            last_draft_at = now
            last_text = text
    except OllamaError as exc:
      if not response.strip(): raise
      final_text = visible_text.strip()
      if final_text:
        await self._send_final_text(message, final_text)
      await self.sender.answer(message, f'Генерация прервалась: {exc.user_message}', parse_mode=None)
      logger.warning('ollama draft stream interrupted after partial response: %s', exc)
      return response.strip()

    final_text = visible_text.strip()
    if final_text:
      await self._send_final_text(message, final_text)
    logger.info('telegram draft stream completed response_chars=%s final_chunk_chars=%s', len(response), len(final_text))
    return response.strip() or final_text

  async def _send_final_text(self, message: Message, text: str) -> None:
    chunks = message_chunks(text, self.settings.max_telegram_message_chars)
    if not chunks: chunks = [text]
    for chunk in chunks:
      await self.sender.answer(message, chunk, parse_mode=self.settings.telegram_parse_mode)
