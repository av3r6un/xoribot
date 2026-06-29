from __future__ import annotations

import html
import re


def telegram_html(text: str) -> str:
  parts = re.split(r'(```[\s\S]*?```)', text)
  result = []
  for part in parts:
    if part.startswith('```') and part.endswith('```'):
      result.append(_code_block(part))
    else:
      result.append(_inline_markdown(part))
  return ''.join(result)


def _code_block(text: str) -> str:
  content = text[3:-3]
  lines = content.split('\n', 1)
  if len(lines) == 2 and re.fullmatch(r'[A-Za-z0-9_+.-]+', lines[0].strip()):
    content = lines[1]
  return f'<pre>{html.escape(content.strip())}</pre>'


def _inline_markdown(text: str) -> str:
  escaped = html.escape(text)
  escaped = _headings(escaped)
  escaped = re.sub(r'&lt;(https?://[^&\s]+)&gt;', r'<a href="\1">\1</a>', escaped)
  escaped = re.sub(r'\[([^\]\n]+)\]\((https?://[^)\s]+)\)', _link, escaped)
  escaped = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', escaped)
  escaped = re.sub(r'\*\*([^*\n]+)\*\*', r'<b>\1</b>', escaped)
  escaped = re.sub(r'__([^_\n]+)__', r'<b>\1</b>', escaped)
  escaped = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<i>\1</i>', escaped)
  return escaped


def _headings(text: str) -> str:
  lines = []
  for line in text.split('\n'):
    match = re.match(r'^\s{0,3}#{1,6}\s+(.+)$', line)
    if match:
      lines.append(f'<b>{match.group(1).strip()}</b>')
    else:
      lines.append(line)
  return '\n'.join(lines)


def _link(match: re.Match) -> str:
  title = match.group(1)
  url = match.group(2).replace('&amp;', '&')
  return f'<a href="{html.escape(url, quote=True)}">{title}</a>'
