# W14 — Responsible AI (reflection)

> **Scaffold.** Requirement: *"at least half a page: What risks, biases, or
> misuse potentials does your system have?"* (VL 14)
>
> Guiding questions below; the text is yours. Roughly 300–400 words. This one
> rewards honesty about your own system more than general AI-ethics statements.

## Data protection

> The most concrete point, and one the architecture makes explicit:
>
> The system supports two modes. In local mode the photos never leave the
> machine. In hosted mode (OpenRouter) every product photo and every prompt is
> sent to a third-party provider — and product photos are taken in people's
> homes. They contain more than the product: rooms, other belongings, sometimes
> people.
>
> Discuss: is the user aware of this? What does the Streamlit UI tell them? Would
> you make the mode visible in the interface?

## Bias

> Where can systematic distortion enter?
>
> - **Price estimates** — web search reflects the platforms and regions it
>   indexes. Prices for the German market are not prices everywhere.
> - **Product recognition** — vision models recognise well-known Western brands
>   more reliably than regional or niche products. What happens to someone
>   selling something the model does not know?
> - **Language** — the generated listings are German; the prompts are partly
>   English. Whose products get described well?

## Misuse potential

> Think about what the system makes *easy* that was hard before:
>
> - Mass generation of listings — a tool for bulk resellers, not just individuals.
> - Appealing descriptions of defective goods: the vision model sees the photo
>   the seller chose. It cannot know what the photo hides.
> - Price manipulation, if the recommendation is systematically skewed.

## Reliability and responsibility

> - The agent produces a **price recommendation**, not a valuation. What happens
>   if someone sells well below value because of it?
> - Small models hallucinate — a confidently wrong product identification leads
>   to a confidently wrong price.
> - There is no human-in-the-loop step in the current flow. Should there be one?

## What you have built in — and what you have not

> Close by matching risks to mitigations honestly:
>
> - Local mode as the default: data protection by architecture.
> - Traceability via Langfuse: every decision is reconstructable.
> - No authentication, no rate limiting, no content moderation, no logging of who
>   uploaded what.
>
> Naming the gaps counts in your favour here.
