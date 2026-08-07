<a id="readme-top"></a>

<div align="center">

# SmartSellerAgent
**A photo goes in, a finished marketplace listing comes out.**

<!-- Project Shields -->
[![CI][ci-shield]][ci-url] [![Python][python-shield]][python-url] [![Docker][docker-shield]][docker-url] [![smolagents][smolagents-shield]][smolagents-url] [![Contributors][contributing-shield]][contributing-url] [![License][license-shield]][license-url]

</div>


<!-- Project Logo -->
<br />
<div align="center">
  <a href="https://github.com/SmartSeller-Agent/SmartSellerAgent">
    <img src="docs/figures/logo_2.png" alt="Logo" width="100" height="100">
  </a>  
  <br>
  <br>

  Explore the documentation below 

  [![Architecture][architecture-shield]][architecture-url] [![Requirements][requirements-shield]][requirements-url] [![Performance][performance-shield]][performance-url]
</div>



## About the project

Selling a used item online is mostly clerical work: figure out what the thing actually is, look up what comparable ones go for, decide on a price, write a title and a description that read well, and then type all of it into a form. 

SmartSellerAgent does that from a single photo.

You upload the picture, thats it. From there a multi-agent system takes over: a vision agent identifies the product, brand and condition; the orchestrator researches realistic second-hand prices with a web search and writes the ad in German. If you ask it to, a publisher agent then drives a real browser through the kleinanzeigen.de offer form and fills everything in, the last click stays yours unless you explicitly hand it over.


## Contents

- [Requirements](#requirements) — what you need installed
- [Configuration](#configuration) — the `.env` file and what is in it
- [How to Run](#how-to-run) — hosted models (A1) or local models (A2)
- [Publishing to kleinanzeigen.de](#publishing-to-kleinanzeigende) — login and the two publish switches
- [Architecture Overview](#architecture-overview) — how the parts fit together
- [Documentation](#documentation) — the detailed docs in `docs/`
- [License](#license) — MIT

## Requirements

Docker with Compose. Nothing else (no Python, no Ollama, no API Keys, even if these are recommended) for the default setup.

```bash
git clone <REPO-URL>
cd SmartSellerAgent
docker compose up --build
```

Working on the code instead of just running it? See [CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Configuration

A `.env` file is optional, without one the system starts in local mode with the defaults from [docker-compose.yml](docker-compose.yml). 
To change anything, copy the template and edit it:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `TEXT_MODEL_ID` | ❌ | Model pulled into the local Ollama container (default `qwen3:1.7b`) |
| `VISION_MODEL_ID` | ❌ | Vision model pulled locally (default `llava`) |
| `OPENROUTER_API_KEY` | ⚠️ | **Only for hosted mode** — required by `docker-compose.openrouter.yml` |
| `OPENROUTER_TEXT_MODEL` | ❌ | Hosted text model (default `qwen/qwen3-8b`) |
| `OPENROUTER_VISION_MODEL` | ❌ | Hosted vision model (default `google/gemini-2.5-flash`) |
| `COMPOSE_FILE` | ❌ | Selects the mode once instead of per command (see below) |
| `LANGFUSE_PUBLIC_KEY` | ❌ | Tracing via Langfuse (W5) — skipped when empty |
| `LANGFUSE_SECRET_KEY` | ❌ | Tracing via Langfuse (W5) — skipped when empty |

[.env.example](.env.example) documents every variable including the less common
ones (`MODEL_EXTRA_BODY`, `VISION_TIMEOUT_S`, the separate `*_API_BASE` endpoints).

## How to Run

Everything runs in Docker either way. The two options differ only in **where the
models run** — hosted at OpenRouter, or locally in an `ollama` container:

| | A1 — OpenRouter *(recommended)* | A2 — local models |
|---|---|---|
| Setup | API key with credit | none, self-contained |
| First start | immediate | several GB downloaded |
| Speed | fast | slow (CPU inference) |
| Data | sent to the provider | stays on the machine |
| Cost | pay per token | none |

**A1 is the recommended way to run this project** — an agent run takes minutes
instead of tens of minutes. Use A2 if you have no API key, or if the product
photos must not leave the machine.

In both cases the same URLs are served once the stack is up:

| URL | What |
|---|---|
| http://localhost:8501 | **Streamlit web UI** — upload a photo, get a listing |
| http://localhost:8000/docs | Interactive API documentation (Swagger) |
| http://localhost:8000/health | Health endpoint (W11) |
| http://localhost:6080/vnc.html | The browser the agent drives, live — see below |

### Publishing to kleinanzeigen.de

The site has no API, so the agent drives a real browser through the offer form.
Two things follow from that, and both are visible in the UI:

**You log in yourself.** The site puts a security check and two-factor prompt in
front of the login, which no script can solve. No password is ever asked for or
stored — you sign in by hand once, and only the resulting session is kept. There
are two ways to get a browser you can do that in:

*A browser on your machine (recommended).* Start it once in its own terminal and
leave it open; the container drives it and the window appears on your desktop:

```bash
uv run python -m scripts.host_browser
```

```bash
# in .env
KLEINANZEIGEN_BROWSER_CDP=http://host.docker.internal:9222
KLEINANZEIGEN_VNC=false
```

The login then lives in that browser's own profile, which persists. This is the
reliable path: the marketplace treats the container's browser as a different
device and has refused sessions there that work everywhere else.

*A browser inside the container.* Without the two lines above, the container runs
its own browser on a virtual screen and streams it to `localhost:6080`. No extra
terminal, but subject to the device problem described above.

Either way, the sidebar walks you through it: it says whether a browser is
running, offers a check, and only offers to log in when the check says you are
not.

**Nothing goes live by accident.** A published ad cannot be taken back, so it
takes two switches: `KLEINANZEIGEN_ALLOW_PUBLISH=true` in `.env` (the operator
allows it at all) *and* the checkbox in the UI (this one run is meant to go
live). Either one missing means the form is only filled in and a screenshot is
written. Neither switch is visible to the language model, and the result shown
in the UI comes from the tool's own record — not from what the agent says it
did.

Run only one of the two stacks at a time; both use the same container names, so
stop the other with `docker compose down` first.

### Option A1 — Docker with hosted models (OpenRouter) *(recommended)*

The models run at OpenRouter. Nothing is downloaded and nothing runs on the CPU.

```bash
docker compose -f docker-compose.openrouter.yml up --build
```

Requires `OPENROUTER_API_KEY` in `.env` (see [.env.example](.env.example)); the
stack refuses to start with a clear error if it is missing. The models used are
`OPENROUTER_TEXT_MODEL` and `OPENROUTER_VISION_MODEL` — kept separate from the
local model ids so switching modes needs no edit to `.env`.

**Selecting the mode once instead of per command.** Compose reads `COMPOSE_FILE`
from `.env`, so a single line there makes plain `docker compose up` use the hosted
stack:

```bash
# in .env
COMPOSE_FILE=docker-compose.openrouter.yml
```

With that line, every `docker compose` command in this project targets the hosted
stack — `up`, `down`, `logs`, all of them, without `-f`. Remove or comment it out
to go back to local.

### Option A2 — Docker with local models (W7)

The whole stack — LLM runtime, model download, backend and web UI — starts with a
single command. Nothing except Docker needs to be installed on the host; neither a
local Ollama nor a local Python environment is required.

```bash
docker compose up --build
```

This is what a plain `docker compose up` does with no `.env` and no API key at
all — the self-contained path (W7).

The four services:

| Service       | Role                                                                            |
|---------------|---------------------------------------------------------------------------------|
| `ollama`      | Local LLM runtime, serves the text and vision models inside the compose network  |
| `ollama-init` | One-shot job: pulls `TEXT_MODEL_ID` and `VISION_MODEL_ID`, then exits             |
| `api`         | FastAPI backend ([`src/app.py`](src/app.py)) with the multi-agent system          |
| `frontend`    | Streamlit UI ([`src/frontend.py`](src/frontend.py))                               |

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

Note that the endpoint URLs are set by Compose itself and ignore any value in
`.env` — inside the compose network the runtime is reached as `ollama`, not
`localhost`. Everything else is configured as described under
[Configuration](#configuration).

### Running without Docker

For working on the code (instant reload instead of an image rebuild) see [CONTRIBUTING.md](docs/CONTRIBUTING.md). 
That path is a development setup, not a third deployment mode.

## Architecture Overview
The system is built on the principles of a Service-Oriented Architecture (SOA) and strictly separates the user interface from data processing:

*   **Frontend (Streamlit):** A lightweight web interface that manages the file upload and communicates asynchronously with the API.
*   **Backend (FastAPI):** Provides REST endpoints (`/run-task`) to receive requests in a standardized manner.
*   **Multi-Agent-System (smolagents):**
    *   **Orchestrator:** The main agent that controls the workflow and has access to the WebSearch and Pricing tools.
    *   **Vision-Agent:** A sub-agent exclusively responsible for the visual analysis of the product images.
*   **Models:** Configurable per deployment. In the default setup the LLMs run locally in an Ollama container, which keeps the data on the machine and avoids cloud costs at the price of speed. Alternatively the same containers can be pointed at a hosted provider (OpenRouter) — much faster, but the requests including the product photos then leave the machine. Text and vision model are configured separately and may sit at different providers.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Detailed system description: components, data flow, design decisions, limitations |
| [docs/requirements.md](docs/requirements.md#requirements-definitions) | Requirements definitions (P1–P5, W1–W14) |
| [docs/requirements.md](docs/requirements.md#requirements-fulfilment) | Which requirements (P1–P5, W1–W14) are met, with evidence |
| [docs/performance.md](docs/performance.md) | Measurements and what was optimised |
| [docs/reflection-w12-drift.md](docs/reflection-w12-drift.md) | Data/concept drift (W12) |
| [docs/reflection-w13-continuous-learning.md](docs/reflection-w13-continuous-learning.md) | Continuous learning (W13) |
| [docs/reflection-w14-responsible-ai.md](docs/reflection-w14-responsible-ai.md) | Responsible AI (W14) |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | Development setup, tests, branch workflow |

## License

Distributed under the MIT License — use it, change it, ship it, just keep the
copyright notice. See [LICENSE](LICENSE) for the full text.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[ci-shield]: https://img.shields.io/github/actions/workflow/status/SmartSeller-Agent/SmartSellerAgent/ci.yml?branch=develop&style=flat-square
[ci-url]: https://github.com/SmartSeller-Agent/SmartSellerAgent/actions/workflows/ci.yml
[python-shield]: https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white
[python-url]: pyproject.toml
[docker-shield]: https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white
[docker-url]: docker-compose.yml
[smolagents-shield]: https://img.shields.io/badge/agents-smolagents-FF9D00?style=flat-square
[smolagents-url]: https://github.com/huggingface/smolagents
[contributing-shield]: https://img.shields.io/github/contributors/SmartSeller-Agent/SmartSellerAgent?style=flat-square
[contributing-url]: docs/CONTRIBUTING.md
[license-shield]: https://img.shields.io/badge/License-MIT-3da639?style=flat-square
[license-url]: LICENSE

[architecture-shield]: https://img.shields.io/badge/Architecture-0c3727?style=for-the-badge
[architecture-url]: docs/architecture.md
[requirements-shield]: https://img.shields.io/badge/Requirements-0c3727?style=for-the-badge
[requirements-url]: docs/requirements.md
[performance-shield]: https://img.shields.io/badge/Performance-0c3727?style=for-the-badge
[performance-url]: docs/performance.md