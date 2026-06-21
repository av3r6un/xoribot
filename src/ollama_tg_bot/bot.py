from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatAction, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import Settings
from .ollama_client import OllamaClient, OllamaError
from .security import is_allowed
from .sessions import Session, SessionManager
from .telegram_utils import (
  command_name,
  is_reply_to_bot,
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
  'models',
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
      default_model=settings.ollama_model,
      max_history_messages=settings.max_history_messages,
      max_context_chars=settings.max_context_chars,
    )
    self.model_choices: dict[str, str] = {}
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

    @self.router.callback_query(F.data.startswith('model:'))
    async def handle_model_callback(callback: CallbackQuery) -> None:
      await self._handle_model_callback(callback)

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
      await message.answer('Бот активен. Напиши сообщение, чтобы начать диалог.\nКоманды: /reset, /new, /status, /models, /help')
      return
    if name == 'help':
      await message.answer(
        'Команды:\n'
        '/reset — сбросить контекст текущего чата\n'
        '/new — создать новую сессию\n'
        '/status — показать состояние текущей сессии\n'
        '/model — показать текущую модель\n'
        '/models — выбрать модель Ollama\n'
        '/ping — проверить доступность бота'
      )
      return
    if name == 'ping':
      await message.answer('pong')
      return
    if name == 'model':
      await message.answer(f'Текущая модель: {session.model}')
      return
    if name == 'models':
      logger.info('/models chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      await self._send_models(message, session)
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
        response = await self._stream_response(message, session)
    except OllamaError as exc:
      logger.exception('ollama error chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      await message.answer(exc.user_message)
      return

    self.sessions.add_assistant_message(session, response)
  async def _send_models(self, message: Message, session: Session) -> None:
    try:
      models = await self.ollama.models()
    except OllamaError as exc:
      logger.exception('ollama models error chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      await message.answer(exc.user_message)
      return

    if not models:
      await message.answer('В Ollama не найдено моделей.')
      return

    buttons: list[list[InlineKeyboardButton]] = []
    self.model_choices = {}
    for model in models:
      key = hashlib.sha1(model.encode('utf-8')).hexdigest()[:12]
      self.model_choices[key] = model
      label = f'✓ {model}' if model == session.model else model
      buttons.append([InlineKeyboardButton(text=label, callback_data=f'model:{key}')])

    await message.answer(
      f'Текущая модель: {session.model}\nВыбери модель:',
      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )

  async def _handle_model_callback(self, callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message):
      await callback.answer()
      return

    if not self._is_callback_allowed(callback):
      await callback.answer('Нет доступа.', show_alert=True)
      return

    key = (callback.data or '').removeprefix('model:')
    model = self.model_choices.get(key)
    if not model:
      await callback.answer('Список моделей устарел. Вызови /models ещё раз.', show_alert=True)
      return

    session = self.sessions.get(message.chat.id, self._session_user_id(message, callback.from_user.id))
    self.sessions.set_model(session, model)
    await callback.answer(f'Модель выбрана: {model}')
    await self._safe_edit(message, f'Текущая модель: {model}')

  async def _stream_response(self, message: Message, session: Session) -> str:
    response = ''
    current_chunk = ''
    sent_message = await message.answer('...')
    last_edit_at = 0.0
    last_text = ''
    limit = self.settings.max_telegram_message_chars

    async for delta in self.ollama.stream_chat(self.sessions.ollama_messages(session), session.model):
      response += delta
      current_chunk += delta

      while len(current_chunk) >= limit:
        part = current_chunk[:limit].strip()
        await self._safe_edit(sent_message, part)
        sent_message = await message.answer('...')
        current_chunk = current_chunk[limit:]
        last_edit_at = 0.0
        last_text = ''

      now = time.monotonic()
      text = current_chunk.strip()
      if text and text != last_text and now - last_edit_at >= 1:
        await self._safe_edit(sent_message, text)
        last_edit_at = now
        last_text = text

    final_text = current_chunk.strip() or 'Нет ответа.'
    await self._safe_edit(sent_message, final_text)
    return response.strip() or final_text

  async def _safe_edit(self, message: Message, text: str) -> None:
    try:
      await message.edit_text(text)
    except TelegramBadRequest as exc:
      if 'message is not modified' in str(exc).lower(): return
      raise

  def _status_text(self, session: Session) -> str:
    uptime = int(time.monotonic() - self.started_at)
    return (
      f'session_id: {session.session_id}\n'
      f'модель: {session.model}\n'
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
  def _session_user_id(cls, message: Message, user_id: int | None = None) -> int | None:
    if message.chat.type == ChatType.PRIVATE: return user_id or cls._user_id(message)
    return None

  def _is_callback_allowed(self, callback: CallbackQuery) -> bool:
    message = callback.message
    if not isinstance(message, Message): return False
    if self.settings.allow_all: return True
    if message.chat.type == ChatType.PRIVATE:
      return callback.from_user.id in self.settings.allowed_user_ids
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
      return message.chat.id in self.settings.allowed_group_ids
    return False

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
