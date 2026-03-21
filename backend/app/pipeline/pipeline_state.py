from dataclasses import dataclass, field
from typing import Optional, Dict


@dataclass
class PipelineState:
    request_id: str
    original_query: str
    intent: dict
    missing_fields: list[str]
    session_id: Optional[str] = None
    # Track resolved clarifications to prevent infinite loops
    resolved_clarifications: Optional[Dict[str, str]] = None
