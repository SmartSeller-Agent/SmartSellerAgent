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

# Application code, prompt templates, the Streamlit UI and the sample images
COPY --chown=app:app pyproject.toml README.md frontend.py ./
COPY --chown=app:app src/ ./src/
COPY --chown=app:app test/ ./test/

# Upload target of the Streamlit frontend. Created here so it exists and is
# writable for the unprivileged user even before the shared volume is mounted.
RUN mkdir -p /app/test/images/uploads && chown -R app:app /app/test/images

USER app

EXPOSE 8000 8501

# One image, two roles — docker-compose.yml overrides the command for the
# frontend service. Default is the API (W6: prediction service, W11: /health).
CMD ["uvicorn", "src.app:api", "--host", "0.0.0.0", "--port", "8000"]
