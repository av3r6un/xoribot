from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatAction, ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import Settings
from .ollama_client import OllamaClient, OllamaError
from .personas import Persona, PersonaManager
from .security import is_allowed
from .sessions import Session, SessionManager
from .telegram_utils import (
  command_name,
  is_reply_to_bot,
  should_answer_message,
  strip_bot_mention,
)
from .web_search import WebSearchClient, WebSearchError, search_context


logger = logging.getLogger(__name__)


COMMANDS = {
  'start',
  'help',
  'reset',
  'new',
  'status',
  'model',
  'models',
  'agents',
  'ping',
}


class BotApp:

  def __init__(self, settings: Settings) -> None:
    self.settings = settings
    self.started_at = time.monotonic()
    session = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    default = DefaultBotProperties(parse_mode=settings.telegram_parse_mode)
    self.bot = Bot(token=settings.telegram_bot_token, session=session, default=default)
    self.dp = Dispatcher()
    self.router = Router()
    self.ollama = OllamaClient(settings)
    self.web_search = WebSearchClient(settings)
    self.sessions = SessionManager(
      default_model=settings.ollama_model,
      max_history_messages=settings.max_history_messages,
      max_context_chars=settings.max_context_chars,
    )
    self.personas = PersonaManager(settings.personas_config_path, settings.ollama_model)
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
    await self._send_startup_notification()
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
    persona_match = self.personas.match(text)
    persona = persona_match.persona

    if not is_allowed(self.settings, message):
      logger.warning('access denied chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      return

    if not should_answer_message(
      message,
      self.bot_id,
      self.bot_username,
      self.settings.require_mention_in_groups,
      has_persona_tag=bool(persona_match.matched_tag),
    ):
      return

    logger.info(
      'incoming message chat_id=%s thread_id=%s user_id=%s length=%s',
      message.chat.id,
      message.message_thread_id,
      self._user_id(message),
      len(text),
    )
    if self.settings.log_message_text: logger.info('incoming text=%s', text)

    routed_text = strip_bot_mention(persona_match.text, self.bot_username)
    command = command_name(routed_text)
    if command and command[0] in COMMANDS:
      await self._handle_command(message, command[0], command[1], persona)
      return

    await self._handle_chat_message(message, routed_text, persona)

  async def _handle_command(self, message: Message, name: str, username: str | None, persona: Persona) -> None:
    if message.chat.type != ChatType.PRIVATE:
      if username and self.bot_username and username != self.bot_username.lower(): return
      if not username and not is_reply_to_bot(message, self.bot_id) and not self.personas.has_tag(message.text): return

    session = self._session(message, persona)

    if name == 'start':
      await message.answer('Бот активен. Напиши сообщение, чтобы начать диалог.\nКоманды: /reset, /new, /status, /models, /agents, /help')
      return
    if name == 'help':
      await message.answer(
        'Команды:\n'
        '/reset — сбросить контекст текущего чата\n'
        '/new — создать новую сессию\n'
        '/status — показать состояние текущей сессии\n'
        '/model — показать текущую модель\n'
        '/models — выбрать модель Ollama\n'
        '/agents — показать доступные персоны\n'
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
    if name == 'agents':
      await self._send_agents(message)
      return
    if name == 'reset':
      logger.info('/reset chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      self.sessions.reset(session.chat_id, session.user_id, persona.uid, persona.system_prompt, persona.model)
      await message.answer('Контекст очищен.')
      return
    if name == 'new':
      logger.info('/new chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      self.sessions.new(session.chat_id, session.user_id, persona.uid, persona.system_prompt, persona.model)
      await message.answer('Создана новая сессия.')
      return
    if name == 'status':
      logger.info('/status chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      await message.answer(self._status_text(session))

  async def _handle_chat_message(self, message: Message, text: str, persona: Persona) -> None:
    if not text and not is_reply_to_bot(message, self.bot_id): return

    if len(text) > self.settings.max_input_chars:
      text = text[:self.settings.max_input_chars]

    session = self._session(message, persona)
    self.sessions.add_user_message(session, text)

    try:
      async with self._typing(message):
        tool_messages = await self._tool_messages(persona, text)
        response = await self._stream_response(message, session, tool_messages)
    except WebSearchError as exc:
      logger.warning('web-search error chat_id=%s user_id=%s error=%s', message.chat.id, self._user_id(message), exc)
      await message.answer(exc.user_message)
      return
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
      key = hashlib.sha1(f'{session.persona_id}:{model}'.encode('utf-8')).hexdigest()[:12]
      self.model_choices[key] = model
      label = f'✓ {model}' if model == session.model else model
      buttons.append([InlineKeyboardButton(text=label, callback_data=f'model:{session.persona_id}:{key}')])

    await message.answer(
      f'Персона: {session.persona_id}\nТекущая модель: {session.model}\nВыбери модель:',
      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )

  async def _send_agents(self, message: Message) -> None:
    lines = ['Персоны:']
    for persona in self.personas.all():
      tools = ', '.join(persona.tools) if persona.tools else 'без tools'
      model = persona.model or self.settings.ollama_model
      lines.append(f'{persona.tag_text} — {persona.name}; модель: {model}; {tools}')
    await message.answer('\n'.join(lines))

  async def _handle_model_callback(self, callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message):
      await callback.answer()
      return

    if not self._is_callback_allowed(callback):
      await callback.answer('Нет доступа.', show_alert=True)
      return

    parts = (callback.data or '').split(':', 2)
    if len(parts) != 3:
      await callback.answer()
      return
    _, persona_uid, key = parts
    model = self.model_choices.get(key)
    if not model:
      await callback.answer('Список моделей устарел. Вызови /models ещё раз.', show_alert=True)
      return

    persona = self.personas.get(persona_uid)
    session = self.sessions.get(
      message.chat.id,
      self._session_user_id(message, callback.from_user.id),
      persona.uid,
      persona.system_prompt,
      persona.model,
    )
    self.sessions.set_model(session, model)
    await callback.answer(f'Модель выбрана: {model}')
    await self._safe_edit(message, f'Персона: {session.persona_id}\nТекущая модель: {model}')

  async def _stream_response(self, message: Message, session: Session, tool_messages: list[dict] | None = None) -> str:
    response = ''
    visible_text = ''
    sent_message = await self._safe_answer(message, '...')
    last_edit_at = 0.0
    last_text = ''
    limit = min(self.settings.max_telegram_message_chars, 3900)

    messages = self.sessions.ollama_messages(session)
    if tool_messages:
      messages = messages[:1] + tool_messages + messages[1:]

    try:
      async for delta in self.ollama.stream_chat(messages, session.model):
        response += delta
        visible_text += delta

        while len(visible_text) >= limit:
          part, visible_text = self._split_for_telegram(visible_text, limit)
          await self._safe_edit(sent_message, part)
          sent_message = await self._safe_answer(message, '...')
          last_edit_at = 0.0
          last_text = ''

        now = time.monotonic()
        text = visible_text.strip()
        if text and text != last_text and now - last_edit_at >= 1:
          await self._safe_edit(sent_message, text)
          last_edit_at = now
          last_text = text
    except OllamaError as exc:
      if not response.strip(): raise
      final_text = visible_text.strip()
      if final_text:
        await self._safe_edit(sent_message, final_text)
      await self._safe_answer(message, f'Генерация прервалась: {exc.user_message}')
      logger.warning('ollama stream interrupted after partial response: %s', exc)
      return response.strip()

    final_text = visible_text.strip() or 'Нет ответа.'
    await self._safe_edit(sent_message, final_text)
    return response.strip() or final_text

  async def _tool_messages(self, persona: Persona, text: str) -> list[dict]:
    if 'web_search' not in persona.tools: return []
    if not self.settings.web_search_base_url:
      raise WebSearchError(
        'WEB_SEARCH_BASE_URL is not configured',
        user_message='Web-search не настроен. Добавь WEB_SEARCH_BASE_URL в .env и перезапусти контейнер.',
      )

    results = await self.web_search.search(text)
    context = search_context(results)
    if not context: return []
    return [dict(role='system', content=context)]

  async def _safe_answer(self, message: Message, text: str) -> Message:
    try:
      return await message.answer(text)
    except TelegramBadRequest as exc:
      if self._is_parse_error(exc):
        return await message.answer(text, parse_mode=None)
      raise

  async def _safe_edit(self, message: Message, text: str) -> None:
    try:
      await message.edit_text(text)
    except TelegramBadRequest as exc:
      if 'message is not modified' in str(exc).lower(): return
      if self._is_parse_error(exc):
        await message.edit_text(text, parse_mode=None)
        return
      raise

  @staticmethod
  def _split_for_telegram(text: str, limit: int) -> tuple[str, str]:
    part = text[:limit]
    split_at = max(part.rfind('\n'), part.rfind(' '))
    if split_at < limit // 2: split_at = limit
    return text[:split_at].strip(), text[split_at:].lstrip()

  @staticmethod
  def _is_parse_error(exc: TelegramBadRequest) -> bool:
    text = str(exc).lower()
    return (
      'parse entities' in text
      or "can't parse" in text
      or 'entity' in text
      or 'markdown' in text
    )

  async def _send_startup_notification(self) -> None:
    if not self.settings.service_message_id: return

    search_ok, search_status = await self.web_search.status()
    search_icon = 'ok' if search_ok else 'fail'

    text = (
      f'{self.settings.bot_name} запущен.\n'
      f'Версия: {self.settings.app_version}\n'
      f'Модель по умолчанию: {self.settings.ollama_model}\n'
      f'Ollama: {self.settings.ollama_base_url}\n'
      f'Web-search: {search_icon} {search_status}'
    )

    try:
      await self.bot.send_message(
        chat_id=self.settings.service_message_id,
        message_thread_id=self.settings.service_message_thread_id,
        text=text,
      )
      logger.info(
        'startup notification sent chat_id=%s thread_id=%s',
        self.settings.service_message_id,
        self.settings.service_message_thread_id,
      )
    except TelegramBadRequest as exc:
      if self.settings.service_message_thread_id and 'message thread not found' in str(exc).lower():
        logger.warning(
          'startup notification thread not found chat_id=%s thread_id=%s, retrying without thread',
          self.settings.service_message_id,
          self.settings.service_message_thread_id,
        )
        try:
          await self.bot.send_message(
            chat_id=self.settings.service_message_id,
            text=text,
          )
          logger.info('startup notification sent chat_id=%s without thread', self.settings.service_message_id)
          return
        except TelegramAPIError:
          logger.exception('startup notification fallback failed chat_id=%s', self.settings.service_message_id)
          return
      logger.exception(
        'startup notification failed chat_id=%s thread_id=%s',
        self.settings.service_message_id,
        self.settings.service_message_thread_id,
      )
    except TelegramAPIError:
      logger.exception(
        'startup notification failed chat_id=%s thread_id=%s',
        self.settings.service_message_id,
        self.settings.service_message_thread_id,
      )

  def _status_text(self, session: Session) -> str:
    uptime = int(time.monotonic() - self.started_at)
    return (
      f'session_id: {session.session_id}\n'
      f'персона: {session.persona_id}\n'
      f'модель: {session.model}\n'
      f'сообщений в истории: {len(session.messages)}\n'
      f'размер контекста: {session.context_chars} символов\n'
      f'Ollama: {self.settings.ollama_base_url}\n'
      f'uptime: {uptime} сек.'
    )

  def _session(self, message: Message, persona: Persona) -> Session:
    user_id = self._session_user_id(message)
    return self.sessions.get(message.chat.id, user_id, persona.uid, persona.system_prompt, persona.model)

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
