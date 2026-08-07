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
    <img src="docs/figures/logo_2.png" alt="Logo" width="150" height="150">
  </a>  
  <br>
  <br>

  :arrow_double_down: <u><b> Explore the documentation below </b> </u> :arrow_double_down:

  [![Architecture][architecture-shield]][architecture-url] [![Requirements][requirements-shield]][requirements-url] [![Performance][performance-shield]][performance-url]

  <b></b>

  <b> Problems </b> :question: 

  [See known limitations](#known-limitations) or [open an issue](https://github.com/SmartSeller-Agent/SmartSellerAgent/issues/new)
</div>



## About the project

Selling a used item online is mostly clerical work: figure out what the thing actually is, look up what comparable ones go for, decide on a price, write a title and a description that read well, and then type all of it into a form. 

SmartSellerAgent does that from a single photo.

You upload the picture, thats it. From there a multi-agent system takes over: a vision agent identifies the product, brand and condition; the orchestrator researches realistic second-hand prices with a web search and writes the ad in German. If you ask it to, a publisher agent then drives a real browser through the kleinanzeigen.de offer form and fills everything in, the last click stays yours unless you explicitly hand it over.

## Contents

- [Quickstart](#quickstart-openrouter) — the short path with hosted models
- [Requirements](#requirements) — what you need installed
- [Configuration](#configuration) — the `.env` file and what is in it
- [How to Run](#how-to-run) — hosted models (A1) or local models (A2)
- [Publishing to kleinanzeigen.de](#publishing-to-kleinanzeigende) — login and the two publish switches
- [Architecture Overview](#architecture-overview) — how the parts fit together
- [Documentation](#documentation) — the detailed docs in `docs/`
- [License](#license) — MIT

## Quickstart (OpenRouter)

> [!TIP]
> The recommended way: all models run at **OpenRouter** (no models are downloaded and a run takes minutes instead of tens of minutes). 
>
> All you need is Docker and an API key. 
> *(Only the optional publishing step at the end adds one more tool, `uv`.)*

**1. Get a key at [openrouter.ai/keys](https://openrouter.ai/keys)**: 
It starts with `sk-or-v1-`; **setting a credit limit** on it is a good idea while testing.

**2. Clone and create the `.env`:**

```bash
git clone https://github.com/SmartSeller-Agent/SmartSellerAgent.git
cd SmartSellerAgent
cp .env.example .env
```

**3. Paste the key into that `.env`**
it is the one line that is empty on purpose:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

**4. Start everything:**

```bash
docker compose up --build
```

*No `-f` needed: the template already selects the hosted stack via `COMPOSE_FILE`. Forgetting the key stops the stack right there with a message saying so.*

**5. Open <http://localhost:8501>**:
- enter you PLZ on first startup
- upload a product photo and let it run. The result is a German listing with a title, a description and a suggested price.

**Optional: filling the kleinanzeigen.de form.** 
That part drives a real browser, and shows you the filled-in form on kleinanzeigen.de.

It is the only step that needs more than Docker: [`uv`](https://docs.astral.sh/uv/), the Python project runner. Install it once:

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

*Or through a package manager you already use: `brew install uv` on macOS, `pipx install uv` anywhere. Restart the terminal afterwards so it is on your `PATH` — `uv --version` should then answer.*

That is the only installation. Start the browser in a second terminal and leave it open, then log in once in that window:

```bash
cd SmartSellerAgent # you have to be in the project root for uv to find the scripts
uv run python -m scripts.host_browser
```

*The first run takes a moment: `uv` sets up the environment, and the script fetches the Chromium browser itself (~150 MB) if it is not there yet.*

Nothing goes live by accident: publishing needs `KLEINANZEIGEN_ALLOW_PUBLISH=true` in `.env` *and* the checkbox in the UI. 
Without both, the form is only filled in for you to check and submit yourself.

No API key, or the photos must not leave the machine? Then skip all of the above and run [Option A2](#option-a2--docker-with-local-models-w7) instead — plain
`docker compose up --build` with no `.env` at all.

## Requirements

**Docker with Compose** — that is the whole list for running the system. No
Python, no Ollama and no API key are needed for the self-contained
[local setup](#option-a2--docker-with-local-models-w7); the recommended
[hosted setup](#quickstart-openrouter) adds nothing but an OpenRouter key.

One exception: filling the listing into the kleinanzeigen.de form drives a
browser on your machine, and that one is started with
[`uv`](https://docs.astral.sh/uv/) in a second terminal. The
[Quickstart](#quickstart-openrouter) shows how to install `uv` on Windows, macOS
and Linux, and [Publishing to kleinanzeigen.de](#publishing-to-kleinanzeigende)
explains the rest. Everything up to the finished listing runs in Docker alone.

Working on the code instead of just running it? See [CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Configuration

A `.env` file is optional. Without one the system starts in **local mode** with
the defaults from [docker-compose.yml](docker-compose.yml), self-contained and
without any key. To use the faster hosted models, copy the template and put your
OpenRouter key in it:

```bash
cp .env.example .env
```

The template sets `COMPOSE_FILE=docker-compose.openrouter.yml`, so from then on
a plain `docker compose up --build` runs the **hosted stack**. Comment that one
line out to go back to local models; nothing else changes.

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | ⚠️ | **Hosted mode** — the stack refuses to start without it |
| `COMPOSE_FILE` | ❌ | Which stack a plain `docker compose` command uses (set to hosted in the template) |
| `TEXT_MODEL_ID` | ❌ | Model pulled into the local Ollama container (default `qwen3:1.7b`) |
| `VISION_MODEL_ID` | ❌ | Vision model pulled locally (default `llava`) |
| `OPENROUTER_TEXT_MODEL` | ❌ | Hosted text model (default `qwen/qwen3-8b`) |
| `OPENROUTER_VISION_MODEL` | ❌ | Hosted vision model (default `google/gemini-2.5-flash`) |
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
| http://localhost:6080/vnc.html | The container's browser, live — fallback mode only, see below |

### Publishing to kleinanzeigen.de

The site has no API, so the agent drives a real browser through the offer form.
Two things follow from that, and both are visible in the UI:

**You log in yourself.** The site puts a security check and two-factor prompt in
front of the login, which no script can solve. No password is ever asked for or
stored — you sign in by hand once, and only the resulting session is kept. There
are two ways to get a browser you can do that in:

*A browser on your machine (the default).* Start it once in its own terminal and
leave it open; the container drives it and the window appears on your desktop:

```bash
uv run python -m scripts.host_browser
```

This is the only part of the project that needs `uv` on the host; the
[Quickstart](#quickstart-openrouter) has the one-line installer for Windows,
macOS and Linux. Nothing else has to be installed by hand: `uv` builds the
environment on the first run, and the script downloads the Chromium browser
itself if it is missing. Everything up to the finished listing runs in Docker
alone.

No configuration needed, the containers already point at it. The login then
lives in that browser's own profile, which persists. This is the reliable path:
the marketplace treats the container's browser as a different device and has
refused sessions there that work everywhere else.

*A browser inside the container (fallback).* The container then runs its own
browser on a virtual screen and streams it to `localhost:6080`. No extra
terminal and no Python on the host, but subject to the device problem above:

```bash
# in .env — the empty value is what switches the host browser off
KLEINANZEIGEN_BROWSER_CDP=
KLEINANZEIGEN_VNC=true
```

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
This is also what a plain `docker compose up` starts once a `.env` exists.

```bash
cp .env.example .env     # then paste your key into OPENROUTER_API_KEY
docker compose up --build
```

That works without `-f` because [.env.example](.env.example) sets
`COMPOSE_FILE=docker-compose.openrouter.yml`, and Compose reads that variable
from `.env`. It applies to every `docker compose` command in this project —
`up`, `down`, `logs`, all of them. The explicit form does the same thing and
also works without a `.env`:

```bash
docker compose -f docker-compose.openrouter.yml up --build
```

`OPENROUTER_API_KEY` is required either way; the stack refuses to start with a
clear error if it is empty, rather than failing later on the first request. The
models used are `OPENROUTER_TEXT_MODEL` and `OPENROUTER_VISION_MODEL` — kept
separate from the local model ids, so switching modes needs no edit beyond the
`COMPOSE_FILE` line.

### Option A2 — Docker with local models (W7)

The whole stack — LLM runtime, model download, backend and web UI — starts with a
single command. Nothing except Docker needs to be installed on the host; neither a
local Ollama nor a local Python environment is required, and no API key.

```bash
docker compose up --build
```

This is what a plain `docker compose up` does with **no `.env` file at all**. If
you have a `.env` from the template, comment out its `COMPOSE_FILE` line to come
back here, or name the file explicitly:

```bash
docker compose -f docker-compose.yml up --build
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

## :warning: Known Limitations and Issues

- **Current version can process only one image** and adds only one image to the display being created. This will be addressed in a future release (see [![GitHub issue state #47](https://shields.io/badge/GitHub_issue_47-red?style=flat-square)](https://github.com/SmartSeller-Agent/SmartSellerAgent/issues/47)).
- **Local inference is slow.** It takes about 3.6 minutes per model invocation on the CPU, and a run chains together several of them. See [performance.md](performance.md)
- **The frontend passes a file path**, not a file. Both containers must therefore point to the same directory. This is solved using a volume, but it is not a robust solution.
- **No authentication** on the front end or API, no rate limit. The noVNC view of the fallback path runs without a password, which is why its port is explicitly bound only to `127.0.0.1`.
- **The interface does not indicate which operating mode it is using.** In hosted mode, every product photo leaves the computer, but this is only specified in the configuration. See [W14](reflection-w14-responsible-ai.md).
- **The form's selectors are hard-coded.** The website has no interface; any redesign breaks the tool. See [W12](reflection-w12-drift.md).
- **The price estimate is a recommendation, not an appraisal.** It is based on the results of two web searches and on a model whose sense of price is frozen at the level of its training.
- **Small models are unreliable when called from the tool.** The local approach using `qwen3:1.7b` fails significantly more often than the hosted one.
- **Uploaded images are not automatically deleted.** They accumulate in the `uploads` volume until they are manually removed.

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