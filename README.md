# SmartSellerAgent

## Description
@TODO: Add a brief description of the project.

## Requirements
- Python (Version see `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) as a package and environment manager (see [Install `uv`](#install-uv))

### Install `uv`
If not already installed, you can install `uv` using the following commands:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Alternatively, via pip
pip install uv
```

## Installation
Clone the repository and install dependencies:

```bash
git clone <REPO-URL>
cd projectname
uv sync
```

## Configuration
### API Keys

Copy the `.env.example` file to `.env` and fill in your API keys:

​```bash
cp .env.example .env
​```

| Variable             | Mandatory  | Description                                       |
|----------------------|------------|---------------------------------------------------|
| `HF_TOKEN`           | ❌         | Token for the HF Inference API                    |
| `MODEL_ID`           | ❌         | Overrides the default model                         |
| `OPENAI_API_KEY`     | ❌         | Only needed when using LiteLLM models               |
| `LANGFUSE_PUBLIC_KEY`| ❌         | Tracing via Langfuse (W5: see [requirements.md](requirements.md))|
| `LANGFUSE_SECRET_KEY`| ❌         | Tracing via Langfuse (W5: see [requirements.md](requirements.md))|

## Running the system

### Option A — Docker (W7)

The whole stack — LLM runtime, model download, backend and web UI — starts with a
single command. Nothing except Docker needs to be installed on the host; neither a
local Ollama nor a local Python environment is required.

```bash
docker compose up --build
```

Once everything is up:

| URL                            | What                                             |
|--------------------------------|--------------------------------------------------|
| http://localhost:8501          | **Streamlit web UI** — upload a photo, get a listing |
| http://localhost:8000/docs     | Interactive API documentation (Swagger)          |
| http://localhost:8000/health   | Health endpoint (W11)                            |

The four services:

| Service       | Role                                                                            |
|---------------|---------------------------------------------------------------------------------|
| `ollama`      | Local LLM runtime, serves the text and vision models inside the compose network  |
| `ollama-init` | One-shot job: pulls `TEXT_MODEL_ID` and `VISION_MODEL_ID`, then exits             |
| `api`         | FastAPI backend ([`src/app.py`](src/app.py)) with the multi-agent system          |
| `frontend`    | Streamlit UI ([`frontend.py`](frontend.py))                                       |

The startup order is enforced by Compose: `ollama` must pass its healthcheck, then
`ollama-init` must finish pulling the models, then `api` starts and must answer on
`/health`, and only then does `frontend` come up. So the UI is never reachable
before the system behind it can actually serve a request.

`api` and `frontend` run from the *same* image and differ only in their command.
The uploaded image is written to the shared `uploads` volume, mounted into both
containers — the frontend hands the backend a file path, so both must see the same
directory.

> **First start takes a while.** The models are downloaded on the first run (several
> GB, depending on `TEXT_MODEL_ID`). They are cached in the named volume
> `ollama-models` and reused on every subsequent start. Without an NVIDIA GPU the
> models run on CPU — see the commented `deploy.resources` block in
> [`docker-compose.yml`](docker-compose.yml) for GPU passthrough.

Useful commands:

```bash
docker compose up --build          # build and start everything
docker compose ps                  # service status incl. health
docker compose logs -f api         # follow the agent output (TAO cycle, tool calls)
docker compose down                # stop (models stay cached)
docker compose down -v             # stop and delete models and uploads
```

Configuration: a `.env` file is optional. If present, `TEXT_MODEL_ID`,
`VISION_MODEL_ID` and the Langfuse keys are picked up; the endpoint URLs are set by
Compose itself, since inside the network the runtime is reached as `ollama`, not
`localhost`. Without `.env` the defaults from [`docker-compose.yml`](docker-compose.yml)
apply and the stack still runs (tracing is then simply skipped).

### Option B — locally with `uv`

Requires a running Ollama on the host with the models from `.env` already pulled.
Backend and frontend are two processes, so they need two terminals — see
[How to Run](#how-to-run) below for details and verification tips.

```bash
uv sync
uv run smartselleragent                      # terminal 1: API on 127.0.0.1:8000
uv run streamlit run frontend.py             # terminal 2: UI on localhost:8501
```

The frontend talks to `http://127.0.0.1:8000` by default; override with the
`API_BASE_URL` environment variable (this is what the Docker setup does).

## Architecture Overview
The system is built on the principles of a Service-Oriented Architecture (SOA) and strictly separates the user interface from data processing:

*   **Frontend (Streamlit):** A lightweight web interface that manages the file upload and communicates asynchronously with the API.
*   **Backend (FastAPI):** Provides REST endpoints (`/run-task`) to receive requests in a standardized manner.
*   **Multi-Agent-System (smolagents):**
    *   **Orchestrator:** The main agent that controls the workflow and has access to the WebSearch and Pricing tools.
    *   **Vision-Agent:** A sub-agent exclusively responsible for the visual analysis of the product images.
*   **Models (Ollama):** The local execution of the LLMs ensures data privacy and independence from cloud costs.

## How to Run
The system consists of two independent components that need to be started in separate terminals.

**Terminal 1: Start Backend (FastAPI Server)**

Start the interface first. This process must continue running in the background.
```bash
python -m uv run uvicorn src.app:api --reload
```
*Verification Tip:* Open **http://127.0.0.1:8000/health** in your browser. If you see `{"status":"ok", "message":"Der SmartSeller Agent läuft!"}`, the backend has started successfully. The interactive documentation for developers can be found at `http://127.0.0.1:8000/docs`.

**Terminal 2: Start Frontend (Streamlit)**

Open a second terminal window and start the user interface.
```bash
python -m uv run streamlit run frontend.py
```
*The browser will open automatically (at `http://localhost:8501`) and the system is ready to use.*