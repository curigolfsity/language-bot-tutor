# One image for both services (API and Telegram bot); docker-compose.yml picks the command.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

# Dependencies first (cached until uv.lock or a pyproject changes).
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/telegram_bot/pyproject.toml apps/telegram_bot/
COPY packages/contracts/pyproject.toml packages/contracts/
RUN uv sync --frozen --no-dev --no-install-workspace

# Then the code. Workspace packages are installed in place, so paths match the repo layout.
COPY . .
RUN uv sync --frozen --no-dev

# Unprivileged user; /data holds the speech model and the bot's state (volumes).
RUN useradd --create-home --uid 1000 tutor \
    && mkdir -p /data/models /data/bot \
    && chown -R tutor:tutor /data
USER tutor
