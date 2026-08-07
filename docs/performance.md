# Performance

Every number on this page was measured on this project. The local figures come
from the Ollama request log, the hosted ones from the two agent runs kept in
[logs/](logs/), so each of them can be checked against its source.

## Measurement method

Ollama logs every HTTP request through its Go web framework, which doubles as a
profiler — the third column is the request duration:

```bash
docker logs smartseller-ollama 2>&1 | grep "chat/completions"
```

```
[GIN] 2026/08/04 - 11:18:15 | 200 | 1m55s | 172.18.0.3 | POST "/v1/chat/completions"
       └ timestamp          └ status └ duration └ client └ endpoint
```

In hosted mode this does not apply — https://openrouter.ai/activity shows
latency, tokens and cost per call instead.

## Baseline: local, CPU only

Hardware: 16 GB RAM, no NVIDIA GPU (Intel Iris Xe), Docker VM with 16 CPUs and
11.7 GB RAM. Models: `qwen3:8b` (5.9 GB) + `llava` (4.8 GB), both `100% CPU`.

| Call | Duration |
|---|---|
| 1 | 1m55s |
| 2 | 2m23s |
| 3 | 2m41s |
| 4 | 2m48s |
| 5 | 2m48s |
| 6 | 2m59s |
| 7 | 3m41s |
| 8 | 6m40s |
| 9 | 6m48s |
| — | **10m0s → HTTP 500 (timeout)** |

**Average ≈ 3.6 minutes per single model call.** A full agent run chains several
of these, which is where the ~20–30 minute total came from.

## Findings

### 1. CPU inference — the structural limit
No GPU available, so both models run on the CPU. This is the dominant cost and
cannot be optimised away in software; it can only be avoided by moving inference
elsewhere.

### 2. Reasoning mode
`ollama show qwen3:8b` reports `Capabilities: completion, tools, thinking`. The
model emits a `<think>` block before every answer — hundreds to over a thousand
tokens per step that never appear in the result. `/no_think` (local) and
`reasoning: {enabled: false}` (hosted) switch that off.

Against OpenRouter this is not a tuning knob but a requirement: smolagents sends
`tool_choice=required`, which Qwen3 rejects while thinking is on, so every call
fails with HTTP 400 until reasoning is disabled. What it costs is visible in the
two logs below. With reasoning off, `qwen/qwen3-8b` produced a median of 94
output tokens per step (14 to 437); with reasoning on,
`google/gemini-2.5-flash` produced a median of 541 (94 to 1,200). The thought
text is billed like any other output, which is most of the price difference in
the table further down.

### 3. Blocking trace export
`SimpleSpanProcessor` exported every span synchronously, blocking the agent for
one HTTPS round trip to Langfuse each time. Switched to `BatchSpanProcessor`.

Measured with a simulated 300 ms export latency over 40 spans:

| | before | after |
|---|---|---|
| Agent blocked | 12.26 s | 0.00 s |
| Export calls | 40 | 1 |
| Spans delivered | 40/40 | 40/40 |

No spans are lost: the FastAPI lifespan handler in `src/app.py` flushes the queue
on shutdown.

### 4. Model residency — checked, not a problem
```bash
docker exec smartseller-ollama ollama ps
```
Both models stayed loaded simultaneously (10.7 GB in an 11.7 GB VM), so no
reload thrashing occurred. Note the `UNTIL` column: after ~5 minutes idle a model
is unloaded and the next request pays the reload.

### 5. Context window
`ollama ps` reports `CONTEXT 4096` while `ollama show` gives a native length of
40960. When the context overflows, the *beginning* of the prompt is truncated —
which is where the system instructions live.

We did not chase this further, because the move to hosted models made it moot for
the runs we now ship. It stays on this page as the first thing to check if the
agent ever starts ignoring its instructions in later steps: the input token
counts in the logs grow from about 1,400 to over 21,000 within a single run, so
the ceiling is closer than it looks.

## Hosted mode

The same task, the same prompts, models at OpenRouter instead of the local
Ollama. The figures come from the step summaries and the `cost=` fields that
smolagents logs for every call, so they can be recounted from the files in
[logs/](logs/).

| | local (`qwen3:8b`, CPU) | hosted (`qwen/qwen3-8b`) | hosted (`gemini-2.5-flash`) |
|---|---|---|---|
| Per agent step | ≈ 3.6 min | 2 to 12 s | 2 to 18 s |
| Model calls per run | not recorded | 9 | 10 |
| Whole run | ~20 to 30 min | **49 s** / **89 s** | **153 s** |
| Cost per run | none | $0.0040 / $0.0034 | $0.0127 |

The units are not quite the same and it is worth saying so: the local number is
the model call alone, taken from Ollama's own request log, while the hosted
numbers are whole agent steps and therefore include whatever tool ran inside
them. That makes the comparison conservative rather than flattering.

**Hosted runs finish between ten and thirty times faster.** This is the only
change on this page that altered the experience rather than a detail. Everything
else we tried moved seconds; moving the inference off the CPU moved a run from
"start it and go get a coffee" to "watch it work".

Two things the table hides. The longest step in a hosted run is not the model at
all: filling the offer form took 50 s and 40 s in the two runs, because a real
browser is typing into a real website. And the second qwen run is slower than the
first (89 s versus 49 s) for the same reason — only the second one reached the
form.

The cost is small enough to be irrelevant for development, but it is not zero,
and it scales with the thought text: the run with reasoning enabled cost three
times as much as the two without.
