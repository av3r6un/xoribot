from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


MessageRole = str


@dataclass
class Message:
  role: MessageRole
  content: str
  created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

  @property
  def ollama_json(self) -> dict:
    return dict(role=self.role, content=self.content)


@dataclass
class Session:
  session_id: str
  chat_id: int
  user_id: int | None
  model: str
  messages: list[Message]
  created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
  updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

  @property
  def context_chars(self) -> int:
    return sum(len(message.content) for message in self.messages)


class SessionManager:

  def __init__(self, system_prompt: str, default_model: str, max_history_messages: int, max_context_chars: int) -> None:
    self.system_prompt = system_prompt
    self.default_model = default_model
    self.max_history_messages = max_history_messages
    self.max_context_chars = max_context_chars
    self.sessions: dict[tuple[int, int | None], Session] = {}

  def get(self, chat_id: int, user_id: int | None = None) -> Session:
    key = self._key(chat_id, user_id)
    session = self.sessions.get(key)
    if session: return session
    session = self._create(chat_id, user_id)
    self.sessions[key] = session
    return session

  def reset(self, chat_id: int, user_id: int | None = None) -> Session:
    session = self.get(chat_id, user_id)
    session.messages = [Message(role='system', content=self.system_prompt)]
    session.updated_at = datetime.now(UTC)
    return session

  def new(self, chat_id: int, user_id: int | None = None) -> Session:
    key = self._key(chat_id, user_id)
    session = self._create(chat_id, user_id)
    self.sessions[key] = session
    return session

  def add_user_message(self, session: Session, content: str) -> None:
    session.messages.append(Message(role='user', content=content))
    self._trim(session)

  def add_assistant_message(self, session: Session, content: str) -> None:
    session.messages.append(Message(role='assistant', content=content))
    self._trim(session)

  def set_model(self, session: Session, model: str) -> None:
    session.model = model
    session.updated_at = datetime.now(UTC)

  def ollama_messages(self, session: Session) -> list[dict]:
    self._trim(session)
    return [message.ollama_json for message in session.messages]

  def _create(self, chat_id: int, user_id: int | None) -> Session:
    return Session(
      session_id=uuid4().hex,
      chat_id=chat_id,
      user_id=user_id,
      model=self.default_model,
      messages=[Message(role='system', content=self.system_prompt)],
    )

  def _trim(self, session: Session) -> None:
    system = session.messages[:1]
    history = session.messages[1:]
    if len(history) > self.max_history_messages:
      history = history[-self.max_history_messages:]
    session.messages = system + history

    while len(session.messages) > 1 and session.context_chars > self.max_context_chars:
      session.messages.pop(1)

    session.updated_at = datetime.now(UTC)

  @staticmethod
  def _key(chat_id: int, user_id: int | None) -> tuple[int, int | None]:
    return (chat_id, user_id)
