from __future__ import annotations


def looks_like_docx_request(text: str) -> bool:
  value = text.lower()
  if '.docx' in value or 'docx' in value: return True

  document_words = (
    'word',
    'ворд',
    'документ',
    'документа',
    'документом',
  )
  action_words = (
    'создай',
    'сделай',
    'сгенерируй',
    'подготовь',
    'оформи',
    'напиши',
    'нужен',
    'нужна',
    'create',
    'make',
    'generate',
    'prepare',
    'write',
  )
  return any(word in value for word in document_words) and any(word in value for word in action_words)
