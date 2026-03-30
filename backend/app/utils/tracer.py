from opentelemetry import trace


def get_tracer(name: str) -> trace.Tracer:
    """
    Args:
        name: Instrumentation scope name — pass __name__ from the calling module.

    Returns:
        A Tracer that creates spans under the registered Arize provider.
    """
    return trace.get_tracer(name)
