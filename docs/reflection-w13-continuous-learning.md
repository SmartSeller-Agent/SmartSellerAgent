# W13 — Continuous learning (concept)

> **Scaffold.** Requirement: *"at least half a page: How could the system be
> improved using new data?"* (VL 12)
>
> Note this asks for a **concept**, not an implementation. Guiding questions
> below; the text is yours. Roughly 300–400 words.

## What data the system produces today

> Start from what already exists rather than inventing a pipeline:
>
> - Langfuse traces: every run with its inputs, tool calls, intermediate steps
>   and final answer (`src/tracing.py`).
> - The uploaded images in the `uploads` volume.
> - The generated listings.
>
> What is *missing* is the outcome: did the item sell, and at what price? That
> gap is the interesting part of this reflection.

## How a feedback loop could be closed

> Sketch a realistic loop. Where would the signal come from?
>
> - Explicit: a thumbs up/down or a price correction field in the Streamlit UI.
> - Implicit: the user edits the generated listing before publishing — the diff
>   between generated and published text is a training signal.
> - External: actual sale price, if the platform reported it back.
>
> Which of these is realistic for this system, and which would need
> infrastructure you do not have?

## What could be improved with that data

> Distinguish clearly between the levers — they differ hugely in cost:
>
> - **Prompt improvement** — cheapest. Collect failure cases, adjust
>   `src/prompts.yaml`. No training involved.
> - **Few-shot examples** — feed successful listings into the prompt as examples.
> - **Retrieval / RAG** — build a knowledge base of past evaluations and let the
>   agent look up comparable items. Note that this would also cover W3/W4.
> - **Fine-tuning** — most expensive, needs the most data, and for an 8B model on
>   this hardware is unrealistic. Say so rather than pretending otherwise.

## Risks of a feedback loop

> A short but valuable paragraph: what goes wrong if you learn from your own
> output? Feedback loops amplify their own bias — if the system suggests low
> prices and users accept them, the data confirms low prices. How would you
> guard against that?
