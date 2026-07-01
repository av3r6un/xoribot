from .callbacks import register_callback_routes
from .messages import register_message_routes


def register_routes(app) -> None:
  register_message_routes(app)
  register_callback_routes(app)


__all__ = [
  'register_routes',
]
