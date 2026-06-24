FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ARG INSTALL_FFMPEG=0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md main.py personas.yaml ./
COPY src ./src

RUN if [ "$INSTALL_FFMPEG" = "1" ]; then \
    apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*; \
  fi

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "main.py"]
