from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery


def register_callback_routes(app) -> None:

  @app.router.callback_query(F.data.startswith('model:'))
  async def handle_model_callback(callback: CallbackQuery) -> None:
    await app.handle_model_callback(callback)
