# Architecture and design decisions

> Covers submission requirement 2: *"Detailed project documentation — not just a
> README, but a complete description of the system: architecture, design
> decisions, how it works, limitations."*
>
> **Scaffold.** Headings and guiding questions are prepared; the text is yours.
> Delete these quote blocks as you fill each section.

## 1. What the system does

> One or two paragraphs: what problem does SmartSellerAgent solve, for whom?
> Which input goes in, which output comes out? Keep it concrete — the reader
> should be able to picture one full run.

## 2. Component overview

> Describe each part and what it is responsible for. A diagram helps; a text
> description is explicitly allowed.
>
> - Frontend (Streamlit, `frontend.py`)
> - Backend (FastAPI, `src/app.py`) — endpoints `/health`, `/run-task`
> - Orchestrator agent (smolagents `ToolCallingAgent`)
> - Vision subagent
> - Tools: web search, vision, pricing
> - Model runtime: local Ollama container **or** OpenRouter
> - Observability: OpenTelemetry → Langfuse

## 3. How a request flows through the system

> Walk one request end to end: user uploads a photo in Streamlit → file written
> to the shared volume → POST `/run-task` → orchestrator picks the prompt from
> `src/prompts.yaml` → delegates to the vision subagent → web search → margin
> calculation → answer back to the UI.
>
> This is also the natural place to show the TAO cycle (P2) and where in the logs
> it becomes visible.

## 4. Design decisions

> The interesting part for grading: *why*, not *what*. For each decision state
> the alternatives you considered and why you chose as you did. Candidates:
>
> - **Framework choice (smolagents)** — required as evidence for P3.
> - **Multi-agent split** — why a separate vision subagent instead of one agent
>   with a vision tool?
> - **Two deployment modes** — local Ollama by default, OpenRouter optional.
>   Trade-off: self-contained and private vs. fast.
> - **Two compose files instead of one** — Compose 2.23 cannot skip a profiled
>   `depends_on` target, so a single file would have cost the startup ordering
>   guarantee (models pulled before the agent starts).
> - **`BatchSpanProcessor` instead of `SimpleSpanProcessor`** — tracing off the
>   critical path; see [performance.md](performance.md).
> - **Prompts in YAML** instead of hardcoded strings.
> - **Reasoning disabled for Qwen3** — required, not optional: smolagents sends
>   `tool_choice=required`, which the provider rejects in thinking mode.

## 5. Configuration

> How the two modes are selected, which variables matter, what happens when
> `.env` is missing. Point at [.env.example](../.env.example) rather than
> repeating it.

## 6. Limitations and known issues

> Be honest here — naming limitations reads as competence, not weakness.
> Candidates from the current state:
>
> - Local CPU inference is slow (measured: several minutes per model call).
> - The frontend passes a *file path* to the backend, so both processes need a
>   shared filesystem — solved with a Docker volume, but it is not a robust
>   interface for a real deployment.
> - No authentication on the API.
> - Web search results are unfiltered; price estimates are only as good as what
>   DuckDuckGo returns.
> - Small models are unreliable at tool calling.
> - Uploaded images are not cleaned up.