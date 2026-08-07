# W12 — Data and concept drift (reflection)

> **Scaffold.** Requirement: *"at least half a page: How might drift affect the
> system? What would be noticeable?"* (VL 11)
>
> Guiding questions below — the text is yours. Delete these quote blocks as you
> write. Half a page means roughly 300–400 words.

## Where drift can enter this system

> Think through the inputs that change over time, independently of your code:
>
> - **Prices** — the resale value of a used Kallax shelf in two years is not
>   today's. The web search returns current listings, but the model's own price
>   intuition is frozen at its training cutoff.
> - **Products** — new devices, new brands, discontinued lines. What does the
>   vision model do with a product it has never seen?
> - **Photos** — camera quality, framing and lighting conventions shift; so do
>   the platforms people sell on and the style expected there.
> - **The search source** — DuckDuckGo result formats and ranking change; a
>   scraped snippet that parses today may not parse next year.
> - **The models themselves** — `qwen/qwen3-8b` on OpenRouter can be updated or
>   retired under the same slug. Silent drift with no code change on your side.

## What would be noticeable — and what would not

> The uncomfortable part: which of these would you actually *see*?
>
> - Loud failures: search returns nothing, the API rejects a request, the vision
>   tool errors out. These surface immediately.
> - Quiet failures: prices drift 30% off, listings sound outdated, the vision
>   model confidently misidentifies a new product. **Nothing in the current
>   system would flag this** — there is no ground truth to compare against.
>
> Discuss which signals you *could* observe with what already exists: the
> Langfuse traces record inputs, outputs and step counts per run. What would you
> look at there?

## What you would do about it

> Be concrete and proportionate — this is a student project, not a production
> system. Options worth weighing:
>
> - A small fixed evaluation set of photos with known reference prices, re-run
>   periodically.
> - Logging estimated price vs. actual selling price, if that feedback existed.
> - Alerting on step counts and error rates via the trace data.
> - Pinning model versions instead of floating slugs.
>
> Say which of these you would actually implement and which you consider out of
> proportion.
