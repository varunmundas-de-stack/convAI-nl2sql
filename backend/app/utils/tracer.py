from opentelemetry import trace


def get_tracer(name: str) -> trace.Tracer:
    """
    Args:
        name: Instrumentation scope name — pass __name__ from the calling module.

    Returns:
        A Tracer that creates spans under the registered Arize provider.
    """
    return trace.get_tracer(name)

import json

def _span_set(span, **kwargs) -> None:
    """
    Write key/value pairs onto an OTel span in one call.

    Key convention: first underscore → dot  (input_query → "input.query").
    Values are auto-serialized:
      dict/list → json.dumps (≤ 2000 chars)
      str       → truncated to 1000 chars
      None      → ""
      other     → str()
    """
    for raw_key, value in kwargs.items():
        key = raw_key.replace("_", ".", 1)
        if isinstance(value, (dict, list)):
            span.set_attribute(key, json.dumps(value, default=str)[:2000])
        elif isinstance(value, str):
            span.set_attribute(key, value[:1000])
        elif value is None:
            span.set_attribute(key, "")
        else:
            span.set_attribute(key, str(value))
