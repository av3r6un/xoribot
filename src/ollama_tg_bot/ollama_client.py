from __future__ import annotations

import asyncio
import json
import logging
import time

import aiohttp

from .config import Settings


logger = logging.getLogger(__name__)


class OllamaError(Exception):
  user_message = 'Ollama недоступна. Проверь сервис и OLLAMA_BASE_URL.'


class OllamaModelNotFound(OllamaError):
  user_message = 'Модель не найдена в Ollama. Проверь OLLAMA_MODEL.'


class OllamaTimeout(OllamaError):
  user_message = 'Модель отвечает слишком долго. Попробуй короче запрос или уменьши контекст.'


class OllamaClient:

  def __init__(self, settings: Settings) -> None:
    self.settings = settings
    self.timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)

  async def chat(self, messages: list[dict]) -> str:
    payload = dict(
      model=self.settings.ollama_model,
      messages=messages,
      stream=False,
      options=self.settings.ollama_options,
    )
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
      self.settings.ollama_model,
      context_chars,
      elapsed,
    )

    message = data.get('message') if isinstance(data, dict) else None
    content = message.get('content') if isinstance(message, dict) else None
    if not content: raise OllamaError('Ollama returned empty response')
    return content.strip()
