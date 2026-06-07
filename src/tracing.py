import base64
from opentelemetry.sdk.trace import TracerProvider
#from opentelemetry.sdk.trace.export import BatchSpanProcessor #@TODO: switch to BatchSpanProcessor for better performance in production
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.instrumentation.smolagents import SmolagentsInstrumentor
from requests import auth

from src.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

class _DebugExporter:
    def __init__(self, inner):
        self._inner = inner

    def export(self, spans):
        names = [s.name for s in spans]
        print(f"[OTLP] → exporting {names}")
        result = self._inner.export(spans)
        print(f"[OTLP] ← result: {result}")
        return result

    def shutdown(self):
        return self._inner.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self._inner.force_flush(timeout_millis)


def setup_tracing() -> TracerProvider:
    auth = base64.b64encode(
        f"{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}".encode()
    ).decode()

    print(f"[tracing] endpoint: {LANGFUSE_HOST}/api/public/otel/v1/traces")
    print(f"[tracing] auth header starts with: Basic {auth[:10]}...")
    
    otlp_exporter = OTLPSpanExporter(
        endpoint=f"{LANGFUSE_HOST}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )

    provider = TracerProvider()

    # PROVIDER 1: use this exporter for debugging to see the spans in the console
    #provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))  # for debugging purposes, prints spans to console
    
    # PROVIDER 2: use this exporter to send spans to Langfuse (recommended for production)
    #provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))  # sends spans to Langfuse
    
    # PROVIDER 3: use this exporter for debugging to see the OTLP exporter's behavior and responses
    provider.add_span_processor(SimpleSpanProcessor(_DebugExporter(otlp_exporter)))  # sends spans to Langfuse with debug logging
    
    SmolagentsInstrumentor().instrument(tracer_provider=provider)

    return provider
