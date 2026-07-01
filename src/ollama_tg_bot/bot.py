from __future__ import annotations

import hashlib
import logging
import tempfile
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import Settings
from .docx_service import DocxService
from .docx_tool import DocxToolError, extract_docx_specs
from .filters import AudioAttachment, audio_attachment, looks_like_docx_request
from .ollama_client import OllamaClient, OllamaError
from .personas import Persona, PersonaManager
from .security import is_allowed
from .sessions import Session, SessionManager
from .streaming import ResponseStreamer
from .telegram_utils import (
  command_name,
  is_reply_to_bot,
  message_chunks,
  should_answer_message,
  strip_bot_mention,
)
from .transcription import TranscriptionService
from .utils import TelegramSender, TypingLoop
from .web_search import WebSearchClient, WebSearchError, search_context
from .whisper_client import WhisperClient, WhisperError


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
    self.bot = Bot(token=settings.telegram_bot_token, session=session)
    self.dp = Dispatcher()
    self.router = Router()
    self.ollama = OllamaClient(settings)
    self.whisper = WhisperClient(settings)
    self.transcription = TranscriptionService(settings)
    self.web_search = WebSearchClient(settings)
    self.sender = TelegramSender(self.bot, settings)
    self.personas = PersonaManager(settings.personas_config_path)
    default_persona = self.personas.default()
    self.sessions = SessionManager(
      default_model=default_persona.model,
      max_history_messages=settings.max_history_messages,
      max_context_chars=settings.max_context_chars,
    )
    self.streamer = ResponseStreamer(settings, self.ollama, self.sessions, self.sender)
    self.docx = DocxService(self.ollama, self.sessions)
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

    @self.router.message()
    async def handle_message(message: Message) -> None:
      await self._handle_message(message)

    @self.router.callback_query(F.data.startswith('model:'))
    async def handle_model_callback(callback: CallbackQuery) -> None:
      await self._handle_model_callback(callback)

  async def _handle_message(self, message: Message) -> None:
    if message.text:
      await self._handle_text(message)
      return

    if audio_attachment(message):
      await self._handle_audio_message(message)

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

  async def _handle_audio_message(self, message: Message) -> None:
    attachment = audio_attachment(message)
    if not attachment: return

    text = message.caption or ''
    persona_match = self.personas.match(text)
    persona = persona_match.persona

    if not is_allowed(self.settings, message):
      logger.warning('access denied chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      return

    if not self._should_transcribe_audio_message(message, bool(persona_match.matched_tag), text): return

    routed_text = strip_bot_mention(persona_match.text, self.bot_username)
    command = command_name(routed_text)
    if message.chat.type == ChatType.PRIVATE and command and command[0] in COMMANDS:
      await self._handle_command(message, command[0], command[1], persona)
      return

    logger.info(
      'incoming audio chat_id=%s thread_id=%s user_id=%s file_name=%s media_kind=%s caption_len=%s',
      message.chat.id,
      message.message_thread_id,
      self._user_id(message),
      attachment.file_name,
      attachment.media_kind,
      len(routed_text),
    )

    try:
      transcript = await self._transcribe_audio_message(message, attachment)
    except WhisperError as exc:
      logger.exception(
        'whisper error chat_id=%s user_id=%s file_name=%s',
        message.chat.id,
        self._user_id(message),
        attachment.file_name,
      )
      await self._safe_answer(message, exc.user_message, parse_mode=None)
      return

    if routed_text:
      await self._handle_chat_message(
        message,
        f'{routed_text}\n\n{self._transcription_prompt(attachment, transcript)}',
        persona,
      )
      return

    session = self._session(message, persona)
    self.sessions.add_user_message(session, self._transcription_prompt(attachment, transcript))

  async def _handle_command(self, message: Message, name: str, username: str | None, persona: Persona) -> None:
    source_text = message.text or message.caption
    if message.chat.type != ChatType.PRIVATE:
      if username and self.bot_username and username != self.bot_username.lower(): return
      if not username and not is_reply_to_bot(message, self.bot_id) and not self.personas.has_tag(source_text): return

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
      if 'docx' in persona.tools:
        response = await self.docx.persona_response(session, persona)
        await self.docx.send_response(message, response)
        self.sessions.add_assistant_message(session, response)
        return

      if looks_like_docx_request(text):
        response = await self.docx.delegate_response(session, persona)
        await self.docx.send_response(message, response)
        self.sessions.add_assistant_message(session, response)
        return

      async with self._typing(message):
        tool_messages = await self._tool_messages(persona, text)
        response = await self.streamer.stream(message, session, persona, tool_messages)
        visible_response, docx_specs = extract_docx_specs(response)
        if docx_specs:
          await self.docx.send_documents(message, docx_specs)
          response = visible_response or 'Документ готов.'
    except WebSearchError as exc:
      logger.warning('web-search error chat_id=%s user_id=%s error=%s', message.chat.id, self._user_id(message), exc)
      await self._safe_answer(message, exc.user_message, parse_mode=None)
      return
    except DocxToolError as exc:
      logger.warning('docx tool error chat_id=%s user_id=%s error=%s', message.chat.id, self._user_id(message), exc)
      await self._safe_answer(message, exc.user_message, parse_mode=None)
      return
    except OllamaError as exc:
      logger.exception('ollama error chat_id=%s user_id=%s', message.chat.id, self._user_id(message))
      await self._safe_answer(message, exc.user_message, parse_mode=None)
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
      lines.append(f'{persona.tag_text} — {persona.name}; модель: {persona.model}; {tools}')
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

  async def _tool_messages(self, persona: Persona, text: str) -> list[dict]:
    messages: list[dict] = []
    if 'web_search' in persona.tools:
      if not self.settings.web_search_base_url:
        raise WebSearchError(
          'WEB_SEARCH_BASE_URL is not configured',
          user_message='Web-search не настроен. Добавь WEB_SEARCH_BASE_URL в .env и перезапусти контейнер.',
        )

      results = await self.web_search.search(text)
      context = search_context(results)
      if context: messages.append(dict(role='system', content=context))

    return messages

  async def _safe_answer(self, message: Message, text: str, parse_mode: str | None = None) -> Message:
    return await self.sender.answer(message, text, parse_mode=parse_mode)

  async def _safe_final_edit(self, message: Message, text: str) -> bool:
    return await self.sender.final_edit(message, text)

  async def _safe_edit(
    self,
    message: Message,
    text: str,
    parse_mode: str | None = None,
    wait_retry: bool = False,
  ) -> bool:
    return await self.sender.edit(message, text, parse_mode=parse_mode, wait_retry=wait_retry)

  async def _send_startup_notification(self) -> None:
    if not self.settings.service_message_id: return

    ollama_ok, ollama_status = await self.ollama.status()
    search_ok, search_status = await self.web_search.status()
    whisper_ok, whisper_status = await self.whisper.status()
    ollama_icon = 'ok' if ollama_ok else 'fail'
    search_icon = 'ok' if search_ok else 'fail'
    whisper_icon = 'ok' if whisper_ok else 'fail'

    text = (
      f'{self.settings.bot_name} запущен.\n'
      f'Версия: {self.settings.app_version}\n'
      f'Модель по умолчанию: {self.personas.default().model}\n'
      f'Ollama: {ollama_icon} {ollama_status}\n'
      f'Whisper: {whisper_icon} {whisper_status}\n'
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

  async def _transcribe_audio_message(self, message: Message, attachment: AudioAttachment) -> str:
    progress = await self._safe_answer(message, self._transcription_status_text(attachment), parse_mode=None)
    preview_limit = max(min(self.settings.max_telegram_message_chars, 3900) - 200, 1000)
    transcript_parts: list[str] = []

    async with self._typing(message):
      with tempfile.TemporaryDirectory(prefix='xoribot-upload-') as temp_dir_name:
        source_path = Path(temp_dir_name) / attachment.file_name
        await self._download_file(attachment.file_id, source_path)

        async for chunk in self.transcription.transcribe(source_path):
          if not chunk.text: continue
          transcript_parts.append(chunk.text.strip())
          preview = self._transcription_preview(
            attachment,
            '\n\n'.join(transcript_parts).strip(),
            chunk.index,
            chunk.total,
            preview_limit,
          )
          await self._safe_edit(progress, preview, parse_mode=None, wait_retry=True)

    transcript = '\n\n'.join(part for part in transcript_parts if part).strip()
    if not transcript:
      raise WhisperError('Whisper returned empty transcript', user_message='Whisper вернул пустую расшифровку.')

    await self._send_transcript(message, progress, attachment, transcript)
    return transcript

  async def _download_file(self, file_id: str, destination: Path) -> None:
    file = await self.bot.get_file(file_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    await self.bot.download(file, destination=destination)

  async def _send_transcript(
    self,
    message: Message,
    progress: Message,
    attachment: AudioAttachment,
    transcript: str,
  ) -> None:
    full_text = self._transcription_result_text(attachment, transcript)
    chunks = message_chunks(full_text, self.settings.max_telegram_message_chars)
    if not chunks:
      chunks = [full_text]

    await self._safe_final_edit(progress, chunks[0])
    for chunk in chunks[1:]:
      await self._safe_answer(message, chunk, parse_mode=None)

  @staticmethod
  def _transcription_prompt(attachment: AudioAttachment, transcript: str) -> str:
    return f'Расшифровка аудио "{attachment.file_name}":\n{transcript}'.strip()

  @staticmethod
  def _transcription_status_text(attachment: AudioAttachment) -> str:
    return f'Распознаю аудио: {attachment.file_name}'

  @classmethod
  def _transcription_result_text(cls, attachment: AudioAttachment, transcript: str) -> str:
    return f'Расшифровка аудио: {attachment.file_name}\n\n{transcript}'.strip()

  @classmethod
  def _transcription_preview(
    cls,
    attachment: AudioAttachment,
    transcript: str,
    index: int,
    total: int,
    preview_limit: int,
  ) -> str:
    header = f'Расшифровка аудио: {attachment.file_name}\nЧасть {index}/{total}'
    body = transcript.strip()
    if len(body) > preview_limit:
      body = f'...{body[-preview_limit:]}'
    return f'{header}\n\n{body}'.strip()

  def _should_transcribe_audio_message(self, message: Message, has_persona_tag: bool, text: str | None) -> bool:
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}: return True
    return should_answer_message(
      message,
      self.bot_id,
      self.bot_username,
      self.settings.require_mention_in_groups,
      has_persona_tag=has_persona_tag,
      text=text,
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

  def _typing(self, message: Message) -> TypingLoop:
    return self.sender.typing(message)


async def run_bot(settings: Settings) -> None:
  app = BotApp(settings)
  await app.run()
