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

# PLAYWRIGHT_BROWSERS_PATH moves the browser out of the installing user's home.
# Without it the download lands in /root/.cache and the unprivileged "app" user
# cannot read it. The same variable is what makes the browser findable at run
# time, so it has to stay set, not just exist during the build.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# The virtual environment built in stage 1
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Chromium and its system libraries for the kleinanzeigen.de publishing tool.
#
# Deliberately placed before the application code: this layer is several hundred
# megabytes and must not be rebuilt every time a source file changes.
#
# --with-deps runs apt-get itself, which is why this needs to happen while we
# are still root. The playwright CLI comes from the venv copied above, so the
# browser version always matches the locked python package.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /ms-playwright

# Application code, prompt templates, the Streamlit UI and the sample images
COPY --chown=app:app pyproject.toml README.md frontend.py ./
COPY --chown=app:app src/ ./src/
COPY --chown=app:app test/ ./test/

# Directories the application writes to:
#   test/images/uploads — where the frontend puts the uploaded photo
#   .state              — the saved kleinanzeigen.de login (mounted volume)
#   screenshots         — evidence of what the publishing tool did
#
# Created with the right owner already here. Docker seeds a fresh named volume
# from the image directory it is mounted over, so this is what gives the
# unprivileged user write access to the mounted .state volume.
RUN mkdir -p /app/test/images/uploads /app/.state /app/screenshots \
    && chown -R app:app /app/test/images /app/.state /app/screenshots

USER app

EXPOSE 8000 8501

# One image, two roles — docker-compose.yml overrides the command for the
# frontend service. Default is the API (W6: prediction service, W11: /health).
CMD ["uvicorn", "src.app:api", "--host", "0.0.0.0", "--port", "8000"]
