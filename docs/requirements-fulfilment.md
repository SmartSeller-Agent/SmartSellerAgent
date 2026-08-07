# Requirements fulfilment

> Covers submission requirement 3: *"a clear, structured list of all fulfilled
> requirements (P1–P5 and selected W requirements) with brief evidence for each
> requirement (reference to code, screenshot, log output or text)."*
>
> **Scaffold.** The structure and the requirement texts are prepared. Fill in the
> status and the evidence. At least **11 of the 14 W requirements** must be met.
>
> Keep evidence short and checkable: a file reference with line number, a log
> excerpt, or a screenshot in `docs/assets/`. One or two sentences each.

## Mandatory requirements (P)

| ID | Requirement | Status | Evidence |
|----|---|---|---|
| P1 | Genuine AI agent with tool usage | | |
| P2 | TAO cycle visible, ≥3 steps | | |
| P3 | Established agent framework | | |
| P4 | README with description, architecture, installation, example | | |
| P5 | Git repository with meaningful commit history | | |

### P1 — Genuine AI agent with tool usage
> Evidence: log or screenshot of at least one tool call.

### P2 — TAO cycle visible
> Evidence: terminal output or screenshot showing at least 3 iterations.
> Note that `verbosity_level=LogLevel.DEBUG` in `src/app.py` is what makes the
> Thought part appear — at the default INFO level only Action and Observation
> are logged.

### P3 — Framework usage
> Evidence: import statement plus a short explanation of *why* smolagents.

### P4 — Documentation
> Evidence: point at [../README.md](../README.md) and this docs folder.

### P5 — Commit history
> Evidence: `git log --oneline` with at least 10 commits over the project period.

## Elective requirements (W)

> At least 11 of 14. Mark clearly which ones you are **not** claiming — an
> honest "not implemented" is better than a weak claim.

| ID | Requirement | Status | Evidence |
|----|---|---|---|
| W1 | Multi-agent setup (orchestrator + subagent) | | |
| W2 | Multimodal input | | |
| W3 | RAG component | | |
| W4 | Agentic RAG | | |
| W5 | Observability (tracing / structured logging) | | |
| W6 | Prediction service via HTTP API | | |
| W7 | Containerisation via `docker compose up` | | |
| W8 | ≥5 meaningful automated tests | | |
| W9 | Input validation & error handling | | |
| W10 | CI/CD pipeline triggered by push | | |
| W11 | Monitoring endpoint (`/health` or metrics) | | |
| W12 | Data/concept drift reflection | | [reflection-w12-drift.md](reflection-w12-drift.md) |
| W13 | Continuous learning concept | | [reflection-w13-continuous-learning.md](reflection-w13-continuous-learning.md) |
| W14 | Responsible AI reflection | | [reflection-w14-responsible-ai.md](reflection-w14-responsible-ai.md) |

### Notes per requirement

> Add a short paragraph for each W you claim. Suggested starting points based on
> the current state of the repository — verify each before submitting:
>
> - **W1** — `orchestrator` and `vision_agent` in `src/app.py`, with roles and
>   instructions in `src/prompts.yaml`.
> - **W2** — product photos through the vision tool (`src/tools/vision.py`).
> - **W5** — OpenTelemetry → Langfuse in `src/tracing.py`.
> - **W6** — FastAPI `/run-task` in `src/app.py`.
> - **W7** — `Dockerfile` + `docker-compose.yml`; the whole stack including the
>   model runtime starts with one command.
> - **W8** — `test/test_tools.py`.
> - **W9** — error handling in the vision tool and the pricing tool, HTTP 404/500
>   handling in `/run-task`.
> - **W10** — `.github/workflows/ci.yml`.
> - **W11** — `/health`, also used as the container healthcheck.
>
> W3 and W4 (RAG) are not implemented at the time of writing — decide whether to
> add them or to rely on the other 12.
