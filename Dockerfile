FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md main.py personas.yaml ./
COPY src ./src

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "main.py"]
