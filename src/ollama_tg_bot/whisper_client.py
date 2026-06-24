from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp

from .config import Settings


class WhisperError(Exception):
  user_message = 'Whisper недоступен. Проверь сервис и WHISPER_BASE_URL.'

  def __init__(self, message: str | None = None, user_message: str | None = None) -> None:
    super().__init__(message or self.user_message)
    if user_message: self.user_message = user_message


class WhisperTimeout(WhisperError):
  user_message = 'Whisper отвечает слишком долго. Попробуй файл короче или проверь сервер.'


class WhisperClient:

  def __init__(self, settings: Settings) -> None:
    self.settings = settings
    self.timeout = aiohttp.ClientTimeout(total=settings.whisper_timeout_seconds)

  async def transcribe(self, audio_path: Path) -> str:
    if not self.settings.whisper_base_url:
      raise WhisperError(
        'WHISPER_BASE_URL is not configured',
        user_message='Whisper не настроен. Добавь WHISPER_BASE_URL в .env и перезапусти контейнер.',
      )

    data = aiohttp.FormData()
    data.add_field('model', self.settings.whisper_model)
    data.add_field('response_format', 'verbose_json')
    with audio_path.open('rb') as stream:
      data.add_field('file', stream, filename=audio_path.name, content_type='audio/flac')
      try:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
          async with session.post(f'{self.settings.whisper_base_url}{self.settings.whisper_transcribe_path}', data=data) as resp:
            text = await resp.text()
      except TimeoutError as exc:
        raise WhisperTimeout() from exc
      except asyncio.TimeoutError as exc:
        raise WhisperTimeout() from exc
      except aiohttp.ClientError as exc:
        raise WhisperError(str(exc)) from exc

    try:
      payload = json.loads(text)
    except json.JSONDecodeError:
      payload = text

    if isinstance(payload, dict) and payload.get('error'):
      raise WhisperError(str(payload['error']))
    if isinstance(payload, dict) and 'detail' in payload and resp.status >= 400:
      raise WhisperError(str(payload['detail']))
    if resp.status >= 400:
      raise WhisperError(text or f'Whisper HTTP {resp.status}')

    transcript = self._extract_text(payload)
    if not transcript:
      raise WhisperError('Whisper returned empty transcript')
    return transcript

  async def status(self) -> tuple[bool, str]:
    if not self.settings.whisper_base_url:
      return False, 'disabled: WHISPER_BASE_URL is not set'

    try:
      async with aiohttp.ClientSession(timeout=self.timeout) as session:
        async with session.get(self.settings.whisper_base_url) as resp:
          await resp.read()
    except TimeoutError:
      return False, 'timeout'
    except asyncio.TimeoutError:
      return False, 'timeout'
    except aiohttp.ClientError as exc:
      return False, str(exc)

    if resp.status >= 400:
      return False, f'HTTP {resp.status}'
    return True, f'available: {self.settings.whisper_base_url}'

  @staticmethod
  def _extract_text(payload: object) -> str:
    if isinstance(payload, str): return payload.strip()
    if not isinstance(payload, dict): return ''

    text = payload.get('text')
    if isinstance(text, str) and text.strip(): return text.strip()

    segments = payload.get('segments')
    if isinstance(segments, list):
      parts = []
      for segment in segments:
        if not isinstance(segment, dict): continue
        segment_text = segment.get('text')
        if isinstance(segment_text, str) and segment_text.strip():
          parts.append(segment_text.strip())
      return ' '.join(parts).strip()

    result = payload.get('result')
    if isinstance(result, str): return result.strip()
    return ''
