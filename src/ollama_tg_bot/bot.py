from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatAction, ChatType
from aiogram.types import Message

from .config import Settings
from .ollama_client import OllamaClient, OllamaError
from .security import is_allowed
from .sessions import Session, SessionManager
from .telegram_utils import (
  command_name,
  is_reply_to_bot,
  message_chunks,
  should_answer_message,
  strip_bot_mention,
)


logger = logging.getLogger(__name__)


COMMANDS = {
  'start',
  'help',
  'reset',
  'new',
  'status',
  'model',
  'ping',
}


class BotApp:

  def __init__(self, settings: Settings) -> None:
    self.settings = settings
    self.started_at = time.monotonic()
    session = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    self.bot = Bot(token=settings.telegram_bot_token, session=session)
    self.dp = Dispatcher()
    self.router = Router()
    self.ollama = OllamaClient(settings)
    self.sessions = SessionManager(
      system_prompt=settings.system_prompt,
      max_history_messages=settings.max_history_messages,
      max_context_chars=settings.max_context_chars,
    )
    self.bot_id: int | None = None
    self.bot_username: str | None = settings.bot_username
    self._register_handlers()
    self.dp.include_router(self.router)

  async def run(self) -> None:
    me = await self.bot.get_me()
    self.bot_id = me.id
    self.bot_username = self.bot_username or me.username
    logger.info('bot started id=%s username=%s config=%s', self.bot_id, self.bot_username, self.settings.safe_summary)
    await self.dp.start_polling(self.bot)

  def _register_handlers(self) -> None:

    @self.router.message(F.text)
    async def handle_text(message: Message) -> None:
      await self._handle_text(message)

  async def _handle_text(self, message: Message) -> None:
    text = message.text or ''

    if not is_allowed(self.settings, message):
      logger.warning('access denied chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      return

    if not should_answer_message(
      message,
      self.bot_id,
      self.bot_username,
      self.settings.require_mention_in_groups,
    ):
      return

    logger.info(
      'incoming message chat_id=%s user_id=%s length=%s',
      message.chat.id,
      self._user_id(message),
      len(text),
    )
    if self.settings.log_message_text: logger.info('incoming text=%s', text)

    command = command_name(text)
    if command and command[0] in COMMANDS:
      await self._handle_command(message, command[0], command[1])
      return

    await self._handle_chat_message(message, text)

  async def _handle_command(self, message: Message, name: str, username: str | None) -> None:
    if message.chat.type != ChatType.PRIVATE:
      if username and self.bot_username and username != self.bot_username.lower(): return
      if not username and not is_reply_to_bot(message, self.bot_id): return

    session = self._session(message)

    if name == 'start':
      await message.answer('Бот активен. Напиши сообщение, чтобы начать диалог.\nКоманды: /reset, /new, /status, /help')
      return
    if name == 'help':
      await message.answer(
        'Команды:\n'
        '/reset — сбросить контекст текущего чата\n'
        '/new — создать новую сессию\n'
        '/status — показать состояние текущей сессии\n'
        '/model — показать текущую модель\n'
        '/ping — проверить доступность бота'
      )
      return
    if name == 'ping':
      await message.answer('pong')
      return
    if name == 'model':
      await message.answer(f'Текущая модель: {self.settings.ollama_model}')
      return
    if name == 'reset':
      logger.info('/reset chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      self.sessions.reset(session.chat_id, session.user_id)
      await message.answer('Контекст очищен.')
      return
    if name == 'new':
      logger.info('/new chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      self.sessions.new(session.chat_id, session.user_id)
      await message.answer('Создана новая сессия.')
      return
    if name == 'status':
      logger.info('/status chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      await message.answer(self._status_text(session))

  async def _handle_chat_message(self, message: Message, text: str) -> None:
    text = strip_bot_mention(text, self.bot_username)
    if not text and not is_reply_to_bot(message, self.bot_id): return

    if len(text) > self.settings.max_input_chars:
      text = text[:self.settings.max_input_chars]

    session = self._session(message)
    self.sessions.add_user_message(session, text)

    try:
      async with self._typing(message):
        response = await self.ollama.chat(self.sessions.ollama_messages(session))
    except OllamaError as exc:
      logger.exception('ollama error chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      await message.answer(exc.user_message)
      return

    self.sessions.add_assistant_message(session, response)
    for chunk in message_chunks(response, self.settings.max_telegram_message_chars):
      await message.answer(chunk)

  def _status_text(self, session: Session) -> str:
    uptime = int(time.monotonic() - self.started_at)
    return (
      f'session_id: {session.session_id}\n'
      f'модель: {self.settings.ollama_model}\n'
      f'сообщений в истории: {len(session.messages)}\n'
      f'размер контекста: {session.context_chars} символов\n'
      f'Ollama: {self.settings.ollama_base_url}\n'
      f'uptime: {uptime} сек.'
    )

  def _session(self, message: Message) -> Session:
    user_id = self._session_user_id(message)
    return self.sessions.get(message.chat.id, user_id)

  @staticmethod
  def _user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None

  @classmethod
  def _session_user_id(cls, message: Message) -> int | None:
    if message.chat.type == ChatType.PRIVATE: return cls._user_id(message)
    return None

  def _typing(self, message: Message) -> '_TypingLoop':
    return _TypingLoop(self.bot, message.chat.id)


class _TypingLoop:

  def __init__(self, bot: Bot, chat_id: int) -> None:
    self.bot = bot
    self.chat_id = chat_id
    self.task: asyncio.Task | None = None

  async def __aenter__(self) -> '_TypingLoop':
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


async def run_bot(settings: Settings) -> None:
  app = BotApp(settings)
  await app.run()
