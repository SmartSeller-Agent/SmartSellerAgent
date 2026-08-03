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

The whole stack — LLM runtime, model download and the agent itself — starts with a
single command. Nothing except Docker needs to be installed on the host; a local
Ollama installation is *not* required.

```bash
docker compose up --build
```

What happens:

| Service       | Role                                                                              |
|---------------|-----------------------------------------------------------------------------------|
| `ollama`      | Local LLM runtime, serves the text and vision models inside the compose network    |
| `ollama-init` | One-shot job: pulls `TEXT_MODEL_ID` and `VISION_MODEL_ID`, then exits               |
| `app`         | The smolagents multi-agent workflow ([`src/app.py`](src/app.py)), runs once and exits |

`app` starts only after `ollama-init` has completed successfully, so the agent never
talks to a runtime that has no models yet.

> **First start takes a while.** The models are downloaded on the first run (several
> GB, depending on `TEXT_MODEL_ID`). They are cached in the named volume
> `ollama-models` and reused on every subsequent start. Without an NVIDIA GPU the
> models run on CPU — see the commented `deploy.resources` block in
> [`docker-compose.yml`](docker-compose.yml) for GPU passthrough.

Useful commands:

```bash
docker compose up --build          # build and start everything
docker compose logs -f app         # follow the agent output (TAO cycle, tool calls)
docker compose down                # stop (models stay cached)
docker compose down -v             # stop and delete the downloaded models
```

Configuration: a `.env` file is optional. If present, `TEXT_MODEL_ID`,
`VISION_MODEL_ID` and the Langfuse keys are picked up; the endpoint URLs are set by
Compose itself, since inside the network the runtime is reached as `ollama`, not
`localhost`. Without `.env` the defaults from [`docker-compose.yml`](docker-compose.yml)
apply and the stack still runs (tracing is then simply skipped).

### Option B — locally with `uv`

Requires a running Ollama on the host with the models from `.env` already pulled.

```bash
uv sync
uv run smartselleragent
```

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