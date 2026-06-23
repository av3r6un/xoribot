from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import SYSTEM_PROMPT


logger = logging.getLogger(__name__)
DEFAULT_MODEL = 'qwen25-7b'


@dataclass(frozen=True)
class Persona:
  uid: str
  name: str
  tags: tuple[str, ...]
  system_prompt: str
  model: str
  options: dict
  tools: tuple[str, ...]

  @property
  def tag_text(self) -> str:
    return ', '.join(self.tags)


@dataclass(frozen=True)
class PersonaMatch:
  persona: Persona
  text: str
  matched_tag: str | None


class PersonaManager:

  def __init__(self, path: str) -> None:
    self.path = Path(path)
    self.default_uid = 'main'
    self.personas: dict[str, Persona] = {}
    self.tag_index: dict[str, str] = {}
    self.mtime_ns: int | None = None
    self.reload(force=True)

  def reload(self, force: bool = False) -> None:
    try:
      stat = self.path.stat()
    except FileNotFoundError:
      if force or not self.personas:
        self._set_fallback()
      return

    if not force and self.mtime_ns == stat.st_mtime_ns: return

    try:
      data = yaml.safe_load(self.path.read_text()) or {}
      self._load_data(data)
      self.mtime_ns = stat.st_mtime_ns
      logger.info('personas loaded path=%s count=%s default=%s', self.path, len(self.personas), self.default_uid)
    except Exception:
      logger.exception('personas reload failed path=%s, keeping previous config', self.path)
      if not self.personas: self._set_fallback()

  def default(self) -> Persona:
    self.reload()
    return self.personas.get(self.default_uid) or next(iter(self.personas.values()))

  def all(self) -> list[Persona]:
    self.reload()
    return list(self.personas.values())

  def get(self, uid: str | None) -> Persona:
    self.reload()
    if uid and uid in self.personas: return self.personas[uid]
    return self.default()

  def match(self, text: str) -> PersonaMatch:
    self.reload()
    words = text.split()
    for word in words:
      tag = self._normalize_tag(word)
      persona_uid = self.tag_index.get(tag)
      if persona_uid:
        persona = self.get(persona_uid)
        return PersonaMatch(persona=persona, text=self._strip_tag(text, tag), matched_tag=tag)
    persona = self.default()
    return PersonaMatch(persona=persona, text=text.strip(), matched_tag=None)

  def has_tag(self, text: str | None) -> bool:
    if not text: return False
    self.reload()
    for word in text.split():
      if self._normalize_tag(word) in self.tag_index: return True
    return False

  def _load_data(self, data: dict) -> None:
    raw_personas = data.get('personas')
    if not isinstance(raw_personas, dict): raise ValueError('personas must be a mapping')

    personas: dict[str, Persona] = {}
    tag_index: dict[str, str] = {}

    for uid, payload in raw_personas.items():
      if not isinstance(payload, dict): continue
      persona = self._build_persona(str(uid), payload)
      personas[persona.uid] = persona
      for tag in persona.tags:
        tag_index[tag.lower()] = persona.uid

    if not personas: raise ValueError('personas list is empty')

    default_uid = str(data.get('default_persona') or 'main')
    if default_uid not in personas: default_uid = next(iter(personas))

    self.personas = personas
    self.tag_index = tag_index
    self.default_uid = default_uid

  def _build_persona(self, uid: str, payload: dict) -> Persona:
    tags = payload.get('tags') or []
    if isinstance(tags, str): tags = [tags]
    clean_tags = tuple(self._normalize_tag(str(tag)) for tag in tags if str(tag).strip())
    if not clean_tags: clean_tags = (f'@{uid}',)

    tools = payload.get('tools') or []
    if isinstance(tools, str): tools = [tools]

    system_prompt = str(payload.get('system_prompt') or SYSTEM_PROMPT).strip()
    model = payload.get('model')
    model = str(model).strip() if model else DEFAULT_MODEL
    options = payload.get('options') or {}
    if not isinstance(options, dict): options = {}

    return Persona(
      uid=uid,
      name=str(payload.get('name') or uid),
      tags=clean_tags,
      system_prompt=system_prompt,
      model=model,
      options=dict(options),
      tools=tuple(str(tool) for tool in tools),
    )

  def _set_fallback(self) -> None:
    persona = Persona(
      uid='main',
      name='Xori',
      tags=('@xori',),
      system_prompt=SYSTEM_PROMPT,
      model=DEFAULT_MODEL,
      options={},
      tools=(),
    )
    self.personas = {persona.uid: persona}
    self.tag_index = {'@xori': persona.uid}
    self.default_uid = persona.uid
    self.mtime_ns = None

  @staticmethod
  def _normalize_tag(value: str) -> str:
    tag = value.strip().rstrip('.,:;!?)]}')
    if not tag.startswith('@'): tag = f'@{tag}'
    return tag.lower()

  @staticmethod
  def _strip_tag(text: str, tag: str) -> str:
    parts = []
    for word in text.split():
      if PersonaManager._normalize_tag(word) == tag: continue
      parts.append(word)
    return ' '.join(parts).strip()
