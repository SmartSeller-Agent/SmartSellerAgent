import base64
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.instrumentation.smolagents import SmolagentsInstrumentor

from src.config import (
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    LANGFUSE_HOST,
    OTEL_DEBUG_EXPORT,
)


class _DebugExporter:
    """Wraps an exporter and logs what it ships. Enable via OTEL_DEBUG_EXPORT=true."""

    def __init__(self, inner):
        self._inner = inner

    def export(self, spans):
        names = [s.name for s in spans]
        print(f"[OTLP] → exporting {len(names)} span(s): {names}")
        result = self._inner.export(spans)
        print(f"[OTLP] ← result: {result}")
        return result

    def shutdown(self):
        return self._inner.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self._inner.force_flush(timeout_millis)


def setup_tracing() -> TracerProvider:
    """Instrument smolagents and ship the spans to Langfuse.

    The caller owns the returned provider and must call shutdown() on it before
    the process exits — spans are buffered, so anything still queued would be
    lost otherwise. src/app.py does this in the FastAPI lifespan handler.
    """
    provider = TracerProvider()

    # Without credentials every span export would run into a 401 (and the OTLP
    # retries would stall the run). Instrument anyway so the agent behaves
    # identically, just without exporting — this keeps `docker compose up`
    # working out of the box when no Langfuse account is configured.
    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        print("[tracing] no Langfuse credentials found — continuing without span export")
        SmolagentsInstrumentor().instrument(tracer_provider=provider)
        return provider

    auth = base64.b64encode(
        f"{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}".encode()
    ).decode()

    exporter = OTLPSpanExporter(
        endpoint=f"{LANGFUSE_HOST}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )
    if OTEL_DEBUG_EXPORT:
        exporter = _DebugExporter(exporter)

    # BatchSpanProcessor queues spans and exports them from a background thread.
    # SimpleSpanProcessor, used before, exported on every span end and blocked
    # the agent for the duration of each HTTPS round trip to Langfuse — with
    # several spans per agent step that added up over a run. Same spans, same
    # destination, just off the critical path.
    provider.add_span_processor(BatchSpanProcessor(exporter))

    print(f"[tracing] exporting spans to {LANGFUSE_HOST} (batched)")

    SmolagentsInstrumentor().instrument(tracer_provider=provider)

    return provider
