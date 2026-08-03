# syntax=docker/dockerfile:1
#
# SmartSellerAgent — container image (W7: Containerisation)
#
# Multi-stage build:
#   1. builder  — resolves and installs dependencies with uv into /app/.venv
#   2. runtime  — slim image that only carries the venv and the application code
#
# Build & run via docker compose (see docker-compose.yml):
#   docker compose up --build

# --------------------------------------------------------------------------
# Stage 1: builder
# --------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer is cached as long as pyproject.toml/uv.lock
# do not change, so code edits do not trigger a full dependency re-install.
# --frozen fails the build if uv.lock is out of sync with pyproject.toml,
# which guarantees the image uses exactly the locked versions.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now the project itself (README.md is referenced by pyproject.toml -> readme)
COPY README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --------------------------------------------------------------------------
# Stage 2: runtime
# --------------------------------------------------------------------------
FROM python:3.10-slim-bookworm AS runtime

# Run as an unprivileged user instead of root
RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The virtual environment built in stage 1
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Application code, prompt templates and the sample images used by the demo task
COPY --chown=app:app pyproject.toml README.md ./
COPY --chown=app:app src/ ./src/
COPY --chown=app:app test/ ./test/

USER app

# Reserved for W6 (FastAPI prediction service) / W11 (/health endpoint).
# Documented here so switching to service mode only requires swapping CMD
# and publishing the port in docker-compose.yml.
EXPOSE 8000

# Default: run the agent workflow once (current CLI entrypoint of src/app.py).
CMD ["python", "-m", "src.app"]

# --- API mode (once W6 is merged) ---------------------------------------
# Replace the CMD above with:
#   CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
# and add to the app service in docker-compose.yml:
#   ports:
#     - "8000:8000"
#   healthcheck:
#     test: ["CMD", "python", "-c",
#            "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
#     interval: 15s
#     timeout: 5s
#     retries: 5
#     start_period: 20s
