# Requirements

## Submission 
At the end of the semester, you will submit a Git repository (on GitHub or GitLab, either public or with read access for me). The repository must contain:

1. Working code – the system must be able to be started up consistently (I must be able to get it running locally)
2. Detailed project documentation as a Markdown file in the repository – not just a README, but a complete description of the system: architecture, design decisions, how it works, limitations
3. Fulfilment of requirements – a clear, structured list of all fulfilled requirements (P1–P5 and selected W requirements) with brief evidence for each requirement (reference to code, screenshot, log output or text)
4. Reflection texts for selected reflection requirements (W12–W14), also as Markdown in the repository

## List of requirements

### Compulsory requirements (P)
All five mandatory requirements must be met.

#### P1 – Genuine AI agent with tool usage
The system must include at least one AI agent that **calls upon real tools** (web search, code execution, file reading, API calls, etc.). A direct call to an LLM without the use of tools does not count.

> **Proof**: Log or screenshot showing at least one tool call.

#### P2 – TAO-Zyklus sichtbar
When a representative input is received, the agent goes through at least three complete TAO steps (Thought → Action → Observation). 
The cycle must be traceable in the output (verbose logging, trace or print output).

> **Proof**: Terminal output or screenshot showing at least 3 iterations.

#### P3 – Framework-Einsatz
The system uses an established agent framework: `smolagents`, `LangGraph`, `LlamaIndex Agents`, `CrewAI` or a similar one. 
Plain raw code without a framework is not permitted.

> **Proof**: Import statement + a brief explanation in the README of why this framework was chosen.

#### P4 – Documentation (README)
The repository contains a **README** file containing:
• Brief description of the system (what it does, for whom?)
• Architecture overview (text description or diagram)
• Installation instructions (dependencies, .env variables, startup command)
• Short example: Which input leads to which behavior?

#### P5 – Git repository with a meaningful commit history
The code lies in a Git repository. The commit history shows incremental development progress – not a single “Initial Commit” with the entire project.

> **Proof**: git log --oneline with at least 10 commits over the project timeframe.

### Compulsory elective requirements (W)
At least 11 of the following 14 compulsory elective requirements must be met.

| ID | Requirement | Lecture |
|----|:------------|---|
| W1 | Multi-agent setup: at least 2 agents with defined roles (Orchestrator + Subagent) | VL 4 |
| W2 | Multimodal input: at least one agent processes a non-textual modal as input – e.g. images, audio, video or structured files (PDF, CSV)| VL 4|
| W3 | RAG component: the system answers questions using its own knowledge base / its own documents | VL 7|
| W4 | Agentic RAG: the retrieval step is controlled by the agent itself as a tool, rather than being hard-coded | VL 7 |
| W5 | Observability: at least one form of tracing or structured logging is built in (e.g. Langfuse, Phoenix, structured stdout output)| VL 7 |
| W6 | Prediction Service: the agent/model is accessible via an HTTP API (e.g. FastAPI, Flask)| VL 9 |
| W7 | Containerisation: the system starts up completely via `docker compose up` (Dockerfile provided)| VL 9/13 |
| W8 | Automated testing: at least 5 meaningful unit or integration tests | VL 10 |
| W9 | Input validation & error handling: incorrect or unexpected input is handled gracefully | VL 9/10 |
| W10 | CI/CD pipeline: at least one automated step triggered by a push (GitHub Actions, GitLab CI, etc.) | VL 13 |
| W11 | Monitoring endpoint: `/health` route or Prometheus metrics available | VL 11/13 |
| W12 | Data/Concept Drift – Reflection (at least half a page): How might drift affect the system? What would be noticeable? | VL 11 |
| W13 | Continuous Learning – Concept (at least half a page): How could the system be improved using new data? | VL 12 |
| W14 | Responsible AI – Reflection (at least half a page): What risks, biases, or misuse potentials does your system have? | VL 14 |