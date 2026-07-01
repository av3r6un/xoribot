from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiogram.types import Audio, Document, Message, Voice


TRANSCRIBABLE_AUDIO_EXTENSIONS = {
  '.3gp',
  '.aac',
  '.amr',
  '.caf',
  '.flac',
  '.m4a',
  '.mp3',
  '.mp4',
  '.mpga',
  '.oga',
  '.ogg',
  '.opus',
  '.wav',
  '.weba',
  '.webm',
}


@dataclass(frozen=True)
class AudioAttachment:
  file_id: str
  file_name: str
  media_kind: str


def audio_attachment(message: Message) -> AudioAttachment | None:
  voice = message.voice
  if isinstance(voice, Voice):
    return AudioAttachment(
      file_id=voice.file_id,
      file_name=f'voice_{voice.file_unique_id}.ogg',
      media_kind='voice',
    )

  audio = message.audio
  if isinstance(audio, Audio):
    file_name = audio.file_name or f'audio_{audio.file_unique_id}.mp3'
    return AudioAttachment(file_id=audio.file_id, file_name=file_name, media_kind='audio')

  document = message.document
  if isinstance(document, Document) and is_audio_document(document):
    file_name = document.file_name or f'document_{document.file_unique_id}'
    return AudioAttachment(file_id=document.file_id, file_name=file_name, media_kind='document')

  return None


def is_audio_document(document: Document) -> bool:
  mime_type = (document.mime_type or '').lower()
  if mime_type.startswith('audio/'): return True
  file_name = document.file_name or ''
  return Path(file_name).suffix.lower() in TRANSCRIBABLE_AUDIO_EXTENSIONS
