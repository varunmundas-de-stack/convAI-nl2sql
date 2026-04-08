"""
Pipeline Context and Error Types

Extracted from query_orchestrator.py to break circular import dependencies
and make context available to all tools.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.dspy_pipeline.clarification_tool import CompoundClarificationState
    from app.models.qco import QueryContextObject
else:
    # Use string annotations to avoid circular imports at runtime
    CompoundClarificationState = "CompoundClarificationState"
    QueryContextObject = "QueryContextObject"


# =============================================================================
# STAGE CONSTANTS
# =============================================================================

class Stage:
    RECEIVED                = "received"
    QCO_LOADED              = "qco_loaded"
    INTENT_EXTRACTED        = "intent_extracted"
    INTENT_MERGED           = "intent_merged"
    CLARIFICATION_REQUESTED = "clarification_requested"
    INTENT_VALIDATED        = "intent_validated"
    CUBE_QUERY_BUILT        = "cube_query_built"
    CUBE_EXECUTED           = "cube_executed"
    INSIGHTS_GENERATED      = "insights_generated"
    INSIGHTS_REFINED        = "insights_refined"
    VISUAL_SPEC_GENERATED   = "visual_spec_generated"
    QCO_RESOLVED            = "qco_resolved"
    COMPLETED               = "completed"


# =============================================================================
# ERROR TYPES
# =============================================================================

@dataclass
class OrchestratorError:
    stage: str
    error_type: str
    message: str = ""
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details or {},
        }


# =============================================================================
# PIPELINE CONTEXT
# =============================================================================

@dataclass
class PipelineContext:
    """Single object threaded through every pipeline step."""

    # inputs
    query: str
    session_id: Optional[str] = None
    original_query: Optional[str] = None
    skip_reset_overrides: bool = False
    resolved_clarifications: Optional[Dict[str, Any]] = None

    # pipeline tracking
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stage: str = Stage.RECEIVED
    success: bool = False
    start_time: float = field(default_factory=time.monotonic)
    duration_ms: int = 0

    # step outputs
    previous_qco: Optional["QueryContextObject"] = None
    raw_intent: Optional[Dict[str, Any]] = None
    merged_intent: Optional[Dict[str, Any]] = None
    validated_intent: Optional[Any] = None
    original_intent: Optional[Any] = None
    cube_query: Optional[Dict[str, Any]] = None
    period_strategy: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    comparison_data: Optional[List[Dict[str, Any]]] = None
    insights: Optional[Any] = None
    refined_insights: Optional[Any] = None
    visual_spec: Optional[Any] = None

    # clarification
    clarification: Optional[bool] = None
    missing_fields: Optional[List[str]] = None
    clarification_message: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    clarification_answers: Optional[Dict[str, Any]] = None

    # compound query support
    is_compound_query: bool = False
    compound_metadata: Optional[Dict[str, Any]] = None
    compound_clarification_state: Optional["CompoundClarificationState"] = None
    is_compound_partial: bool = False

    # error
    error: Optional[OrchestratorError] = None

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.start_time) * 1000)

    def fail(self, stage: str, error_type: str, message: str, details=None) -> "PipelineContext":
        """Stamp a hard error onto the context. The runner stops after this."""
        self.error = OrchestratorError(stage=stage, error_type=error_type, message=message, details=details)
        self.duration_ms = self.elapsed_ms()
        return self

    def to_dict(self) -> Dict[str, Any]:
        def _dump(obj):
            return obj.model_dump() if obj is not None and hasattr(obj, "model_dump") else obj

        effective = self.query
        if self.clarification_answers and self.original_query:
            parts = [f"{k}: {v}" for k, v in self.clarification_answers.items() if isinstance(v, str) and v.strip()]
            if parts:
                effective = f"{self.original_query} ({', '.join(parts)})"

        return {
            "query": self.query,
            "original_query": self.original_query,
            "effective_query": effective,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "success": self.success,
            "stage": self.stage,
            "duration_ms": self.duration_ms,
            "has_previous_context": self.previous_qco is not None,
            "raw_intent": self.raw_intent,
            "merged_intent": self.merged_intent,
            "validated_intent": _dump(self.validated_intent),
            "original_intent": _dump(self.original_intent),
            "cube_query": self.cube_query,
            "period_strategy": self.period_strategy,
            "data": self.data,
            "comparison_data": self.comparison_data,
            "insights": _dump(self.insights),
            "refined_insights": _dump(self.refined_insights),
            "visual_spec": _dump(self.visual_spec),
            "clarification": self.clarification,
            "missing_fields": self.missing_fields,
            "clarification_message": self.clarification_message,
            "allowed_values": self.allowed_values,
            "clarification_answers": self.clarification_answers,
            "is_compound_query": self.is_compound_query,
            "compound_metadata": self.compound_metadata,
            "is_compound_partial": self.is_compound_partial,
            "has_compound_clarification_state": self.compound_clarification_state is not None,
            "error": self.error.to_dict() if self.error else None,
        }