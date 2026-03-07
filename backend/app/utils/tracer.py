"""
tracer.py — Centralized OpenTelemetry tracer for the NL2SQL pipeline.

Imports the tracer_provider that is already registered by arize.otel.register()
inside llm_service.py so every module can obtain a consistent tracer without
re-registering a new provider.

Usage:
    from app.utils.tracer import get_tracer

    tracer = get_tracer(__name__)

    with tracer.start_as_current_span("my_span") as span:
        span.set_attribute("key", "value")
        ...
"""

from opentelemetry import trace


def get_tracer(name: str) -> trace.Tracer:
    """
    Return an OpenTelemetry Tracer for the given instrumentation scope name.

    The tracer_provider is already configured globally by arize.otel.register()
    when llm_service is first imported (which happens at app startup). All spans
    produced by this tracer are therefore automatically exported to Arize AI.

    Args:
        name: Instrumentation scope name — pass __name__ from the calling module.

    Returns:
        A Tracer that creates spans under the registered Arize provider.
    """
    return trace.get_tracer(name)
