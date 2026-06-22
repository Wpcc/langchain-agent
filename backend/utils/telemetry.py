"""OpenTelemetry tracing setup.

Disabled (no-op) when OTEL_ENDPOINT is not configured — local dev needs
no extra infrastructure.

Set OTEL_ENDPOINT in .env to one of:
    console                          print each span to stdout (dev, no backend)
    http://localhost:4318/v1/traces  export to Jaeger / Tempo / any OTLP backend

Usage:
    from backend.utils.telemetry import get_tracer

    with get_tracer().start_as_current_span("my.operation") as span:
        span.set_attribute("key", value)
        ...
"""
from opentelemetry import trace

_SERVICE_NAME = "zhisaotong-backend"


def setup_telemetry(endpoint: str = "") -> None:
    """Configure the global tracer provider.

    If endpoint is empty the default ProxyTracerProvider is left in place,
    which produces spans that go nowhere — effectively zero export overhead.
    """
    if not endpoint:
        return

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.resources import SERVICE_NAME
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider(resource=Resource({SERVICE_NAME: _SERVICE_NAME}))

    if endpoint == "console":
        # Dev mode: print each finished span to stdout, no backend needed.
        # SimpleSpanProcessor exports synchronously so spans appear immediately
        # rather than being buffered and flushed in the background.
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )

    trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_SERVICE_NAME)
