from dataclasses import dataclass


@dataclass
class PipelineState:
    request_id: str
    original_query: str
    intent: dict
    missing_fields: list[str]
