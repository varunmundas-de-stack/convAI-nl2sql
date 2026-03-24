import uuid
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# CORE MODEL
# =============================================================================

class Clarification(BaseModel):
    """
    Minimal clarification request.
    """

    request_id: str = Field(..., description="Unique ID for this clarification")
    field: str = Field(..., description="Field that needs clarification (e.g., metrics, group_by, time)")
    question: str = Field(..., description="Question to ask the user")
    options: List[Any] = Field(..., description="Valid options to choose from")
    multi_select: bool = Field(default=False, description="Allow multiple selections")

    # Optional context (useful for debugging / UI)
    context: Optional[str] = Field(default=None)

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# EXCEPTION (CONTROL FLOW)
# =============================================================================

class ClarificationRequired(Exception):
    """
    Raised by agents when they cannot proceed without user clarification.

    This is NOT an error — it’s a control-flow interrupt.
    The pipeline should catch this and return it to the user.
    """

    def __init__(self, clarification: Clarification):
        self.clarification = clarification
        super().__init__(clarification.question)


# =============================================================================
# HELPER BUILDERS (OPTIONAL, BUT CLEAN)
# =============================================================================

def build_metric_clarification(
    ambiguous_terms: List[str],
    candidate_metrics: List[str],
) -> Clarification:
    return Clarification(
        request_id=str(uuid.uuid4()),
        field="metrics",
        question=f"Which metric do you mean by '{', '.join(ambiguous_terms)}'?",
        options=candidate_metrics,
        multi_select=False,
        context="Ambiguous metric term in query",
    )


def build_dimension_clarification(
    ambiguous_terms: List[str],
    candidate_dimensions: List[str],
) -> Clarification:
    return Clarification(
        request_id=str(uuid.uuid4()),
        field="group_by",
        question=f"Which dimension do you mean by '{', '.join(ambiguous_terms)}'?",
        options=candidate_dimensions,
        multi_select=False,
        context="Ambiguous dimension term in query",
    )


def build_time_clarification(
    ambiguous_expression: str,
    candidate_windows: List[str],
) -> Clarification:
    return Clarification(
        request_id=str(uuid.uuid4()),
        field="time",
        question=f"What time period do you mean by '{ambiguous_expression}'?",
        options=candidate_windows,
        multi_select=False,
        context="Ambiguous time expression",
    )


def build_scope_clarification() -> Clarification:
    return Clarification(
        request_id=str(uuid.uuid4()),
        field="sales_scope",
        question="Which type of sales data do you want?",
        options=["PRIMARY", "SECONDARY"],
        multi_select=False,
        context="Scope not specified in query",
    )


# =============================================================================
# RESPONSE MODEL (FOR RESUME FLOW)
# =============================================================================

class ClarificationAnswer(BaseModel):
    """
    User response to a clarification.

    This is what your API should accept when resuming the pipeline.
    """

    request_id: str
    answer: Any  # can be str or list depending on multi_select

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# PIPELINE INTEGRATION HELPERS
# =============================================================================

def apply_clarification_override(
    overrides: Dict[str, Any],
    clarification: Clarification,
    answer: ClarificationAnswer,
) -> Dict[str, Any]:
    """
    Apply user answer into pipeline override dict.

    Example:
        overrides = {}
        → {"metrics": "net_value"}
    """

    if clarification.multi_select:
        if not isinstance(answer.answer, list):
            raise ValueError("Expected list answer for multi-select clarification")
        overrides[clarification.field] = answer.answer
    else:
        overrides[clarification.field] = answer.answer

    return overrides


def format_clarification_response(clarification: Clarification) -> Dict[str, Any]:
    """
    Convert clarification into API-friendly response.
    """

    return {
        "type": "clarification_required",
        "request_id": clarification.request_id,
        "field": clarification.field,
        "question": clarification.question,
        "options": clarification.options,
        "multi_select": clarification.multi_select,
        "context": clarification.context,
    }