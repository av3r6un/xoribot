from __future__ import annotations

import tempfile
from pathlib import Path

from aiogram.types import FSInputFile, Message

from ..ollama_client import OllamaClient
from ..personas import Persona
from ..sessions import Session, SessionManager
from .docx_tool import DOCX_DELEGATE_PROMPT, DOCX_TOOL_PROMPT, DocxToolError, build_docx, extract_docx_specs


class DocxService:

  def __init__(self, ollama: OllamaClient, sessions: SessionManager) -> None:
    self.ollama = ollama
    self.sessions = sessions

  async def persona_response(self, session: Session, persona: Persona) -> str:
    messages = self.sessions.ollama_messages(session)
    messages = messages[:1] + [dict(role='system', content=DOCX_TOOL_PROMPT)] + messages[1:]
    return await self.ollama.chat(messages, session.model, persona.options)

  async def delegate_response(self, session: Session, persona: Persona) -> str:
    messages = self.sessions.ollama_messages(session)
    messages = messages[:1] + [dict(role='system', content=DOCX_DELEGATE_PROMPT)] + messages[1:]
    return await self.ollama.chat(messages, session.model, persona.options)

  async def send_response(self, message: Message, response: str) -> None:
    _, docx_specs = extract_docx_specs(response)
    if not docx_specs:
      raise DocxToolError('missing docx json', user_message='Модель не вернула JSON-разметку для .docx.')
    await self.send_documents(message, docx_specs)

  async def send_documents(self, message: Message, specs: list[dict]) -> None:
    with tempfile.TemporaryDirectory(prefix='xoribot-docx-') as temp_dir_name:
      temp_dir = Path(temp_dir_name)
      for spec in specs:
        path = build_docx(spec, temp_dir)
        await message.answer_document(FSInputFile(path), caption=f'Готово: {path.name}')
