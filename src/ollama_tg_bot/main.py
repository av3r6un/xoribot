from __future__ import annotations

import asyncio
import logging

from .bot import run_bot
from .config import load_settings, setup_logging


logger = logging.getLogger(__name__)


async def async_main() -> None:
  setup_logging()
  settings = load_settings()
  await run_bot(settings)


def main() -> None:
  try:
    asyncio.run(async_main())
  except KeyboardInterrupt:
    logger.info('bot stopped')


if __name__ == '__main__':
  main()
