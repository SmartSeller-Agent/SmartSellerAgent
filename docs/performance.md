# Performance

> **Scaffold with real data.** The measurements below were taken from this
> project; the interpretation and any further runs are yours to complete.

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

> Fill in what you measured after each change.

### 1. CPU inference — the structural limit
No GPU available, so both models run on the CPU. This is the dominant cost and
cannot be optimised away in software; it can only be avoided by moving inference
elsewhere.

### 2. Reasoning mode
`ollama show qwen3:8b` reports `Capabilities: completion, tools, thinking`. The
model emits a `<think>` block before every answer — hundreds to over a thousand
tokens per step that never appear in the result.

> Record here what `/no_think` (local) and `reasoning: {enabled: false}` (hosted)
> actually gained.

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

> Not investigated further. Worth a look if the agent behaves erratically in
> later steps.

## Hosted mode

> Record the comparison here: same task, same prompt, OpenRouter instead of local
> Ollama. Latency per call and total runtime, from
> https://openrouter.ai/activity.
