from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PipelineState:
    request_id: str
    original_query: str
    intent: dict
    missing_fields: list[str]
    session_id: Optional[str] = None
