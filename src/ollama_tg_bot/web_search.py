from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import aiohttp

from .config import Settings


logger = logging.getLogger(__name__)


class WebSearchError(Exception):
  user_message = 'Web-search недоступен. Проверь SearXNG и WEB_SEARCH_BASE_URL.'


@dataclass(frozen=True)
class SearchResult:
  title: str
  url: str
  content: str


class WebSearchClient:

  def __init__(self, settings: Settings) -> None:
    self.settings = settings
    self.timeout = aiohttp.ClientTimeout(total=settings.web_search_timeout_seconds)

  async def search(self, query: str) -> list[SearchResult]:
    if not self.settings.web_search_base_url: return []

    params = dict(q=query, format='json')

    try:
      async with aiohttp.ClientSession(timeout=self.timeout) as session:
        async with session.get(f'{self.settings.web_search_base_url}/search', params=params) as resp:
          data = await resp.json(content_type=None)
          if resp.status >= 400: raise WebSearchError(f'SearXNG HTTP {resp.status}')
    except TimeoutError as exc:
      raise WebSearchError('SearXNG timeout') from exc
    except asyncio.TimeoutError as exc:
      raise WebSearchError('SearXNG timeout') from exc
    except aiohttp.ClientError as exc:
      raise WebSearchError(str(exc)) from exc

    raw_results = data.get('results') if isinstance(data, dict) else None
    if not isinstance(raw_results, list): return []

    results: list[SearchResult] = []
    for item in raw_results:
      if not isinstance(item, dict): continue
      url = str(item.get('url') or '').strip()
      if not url: continue
      title = str(item.get('title') or url).strip()
      content = str(item.get('content') or '').strip()
      results.append(SearchResult(title=title, url=url, content=content))
      if len(results) >= self.settings.web_search_max_results: break

    logger.info('web search query_len=%s results=%s', len(query), len(results))
    return results


def search_context(results: list[SearchResult]) -> str:
  if not results: return ''

  lines = [
    'Ниже результаты web-search. Используй их как справочный контекст для текущего ответа.',
    'Не выдумывай факты сверх результатов. Если данных недостаточно, скажи об этом.',
    '',
  ]
  for index, result in enumerate(results, start=1):
    lines.extend([
      f'[{index}] {result.title}',
      f'URL: {result.url}',
      f'Snippet: {result.content}',
      '',
    ])
  lines.append('В конце ответа добавь короткий список источников с URL.')
  return '\n'.join(lines)
