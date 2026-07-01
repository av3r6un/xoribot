from __future__ import annotations

from aiogram.types import Message


def register_message_routes(app) -> None:

  @app.router.message()
  async def handle_message(message: Message) -> None:
    await app.handle_message(message)
