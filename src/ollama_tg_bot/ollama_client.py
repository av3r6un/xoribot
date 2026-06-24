from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

import aiohttp

from .config import Settings
from .personas import DEFAULT_MODEL


logger = logging.getLogger(__name__)


class OllamaError(Exception):
  user_message = 'Ollama недоступна. Проверь сервис и OLLAMA_BASE_URL.'


class OllamaModelNotFound(OllamaError):
  user_message = 'Модель не найдена в Ollama. Проверь model в personas.yaml.'


class OllamaTimeout(OllamaError):
  user_message = 'Модель отвечает слишком долго. Попробуй короче запрос или уменьши контекст.'


class OllamaClient:

  def __init__(self, settings: Settings) -> None:
    self.settings = settings
    self.timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
    self.stream_timeout = aiohttp.ClientTimeout(
      total=None,
      sock_connect=30,
      sock_read=settings.request_timeout_seconds,
    )

  async def models(self) -> list[str]:
    try:
      async with aiohttp.ClientSession(timeout=self.timeout) as session:
        async with session.get(f'{self.settings.ollama_base_url}/api/tags') as resp:
          text = await resp.text()
          try:
            data = json.loads(text)
          except json.JSONDecodeError:
            data = {}
          if resp.status >= 400: raise OllamaError(text or f'Ollama HTTP {resp.status}')
    except TimeoutError as exc:
      raise OllamaTimeout() from exc
    except asyncio.TimeoutError as exc:
      raise OllamaTimeout() from exc
    except aiohttp.ClientError as exc:
      raise OllamaError(str(exc)) from exc

    models = data.get('models') if isinstance(data, dict) else None
    if not isinstance(models, list): return []

    result: list[str] = []
    for model in models:
      if not isinstance(model, dict): continue
      name = model.get('name') or model.get('model')
      if name: result.append(str(name))
    return sorted(result)

  async def status(self) -> tuple[bool, str]:
    try:
      models = await self.models()
    except OllamaTimeout:
      return False, 'timeout'
    except OllamaError as exc:
      return False, str(exc)

    if not models:
      return True, f'available: {self.settings.ollama_base_url}, no models'
    return True, f'available: {self.settings.ollama_base_url}'

  async def chat(self, messages: list[dict], model: str | None = None, options: dict | None = None) -> str:
    payload = dict(
      model=model or DEFAULT_MODEL,
      messages=messages,
      stream=False,
    )
    if options: payload['options'] = options
    context_chars = sum(len(message.get('content', '')) for message in messages)
    started_at = time.monotonic()

    try:
      async with aiohttp.ClientSession(timeout=self.timeout) as session:
        async with session.post(f'{self.settings.ollama_base_url}/api/chat', json=payload) as resp:
          if resp.status == 404: raise OllamaModelNotFound()
          text = await resp.text()
          try:
            data = json.loads(text)
          except json.JSONDecodeError:
            data = {}
          if resp.status >= 400:
            error = data.get('error') if isinstance(data, dict) else None
            error = error or text
            if error and 'model' in error.lower() and 'not found' in error.lower():
              raise OllamaModelNotFound()
            raise OllamaError(error or f'Ollama HTTP {resp.status}')
    except TimeoutError as exc:
      raise OllamaTimeout() from exc
    except asyncio.TimeoutError as exc:
      raise OllamaTimeout() from exc
    except aiohttp.ClientError as exc:
      raise OllamaError(str(exc)) from exc

    elapsed = time.monotonic() - started_at
    logger.info(
      'ollama request model=%s context_chars=%s elapsed=%.2fs',
      payload['model'],
      context_chars,
      elapsed,
    )

    message = data.get('message') if isinstance(data, dict) else None
    content = message.get('content') if isinstance(message, dict) else None
    if not content: raise OllamaError('Ollama returned empty response')
    return content.strip()

  async def stream_chat(
    self,
    messages: list[dict],
    model: str | None = None,
    options: dict | None = None,
  ) -> AsyncIterator[str]:
    payload = dict(
      model=model or DEFAULT_MODEL,
      messages=messages,
      stream=True,
    )
    if options: payload['options'] = options
    context_chars = sum(len(message.get('content', '')) for message in messages)
    started_at = time.monotonic()

    try:
      async with aiohttp.ClientSession(timeout=self.stream_timeout) as session:
        async with session.post(f'{self.settings.ollama_base_url}/api/chat', json=payload) as resp:
          if resp.status == 404: raise OllamaModelNotFound()
          if resp.status >= 400:
            text = await resp.text()
            try:
              data = json.loads(text)
            except json.JSONDecodeError:
              data = {}
            error = data.get('error') if isinstance(data, dict) else None
            error = error or text
            if error and 'model' in error.lower() and 'not found' in error.lower():
              raise OllamaModelNotFound()
            raise OllamaError(error or f'Ollama HTTP {resp.status}')

          async for raw_line in resp.content:
            line = raw_line.decode('utf-8').strip()
            if not line: continue
            try:
              data = json.loads(line)
            except json.JSONDecodeError:
              logger.warning('invalid ollama stream line: %s', line)
              continue

            if data.get('error'):
              error = str(data['error'])
              if 'model' in error.lower() and 'not found' in error.lower():
                raise OllamaModelNotFound()
              raise OllamaError(error)

            message = data.get('message')
            if isinstance(message, dict):
              content = message.get('content')
              if content: yield str(content)

            if data.get('done'): break
    except TimeoutError as exc:
      raise OllamaTimeout() from exc
    except asyncio.TimeoutError as exc:
      raise OllamaTimeout() from exc
    except aiohttp.ClientError as exc:
      raise OllamaError(str(exc)) from exc

    elapsed = time.monotonic() - started_at
    logger.info(
      'ollama stream model=%s context_chars=%s elapsed=%.2fs',
      payload['model'],
      context_chars,
      elapsed,
    )
