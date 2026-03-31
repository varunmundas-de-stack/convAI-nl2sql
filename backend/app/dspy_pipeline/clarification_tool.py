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

    # NEW: Track which specific term is being clarified for sequential resolution
    clarifying_term: Optional[str] = Field(default=None, description="Specific term being clarified (e.g., 'sales' when asking about sales metric)")

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# EXCEPTION (CONTROL FLOW)
# =============================================================================

class ClarificationRequired(Exception):
    """
    Raised by agents when they cannot proceed without user clarification.

    This is NOT an error — it's a control-flow interrupt.
    The pipeline should catch this and return it to the user.
    """

    def __init__(self, clarification: Clarification):
        self.clarification = clarification
        super().__init__(clarification.question)


class MultipleClarificationsRequired(Exception):
    """
    Raised by agents when they cannot proceed without multiple user clarifications.

    This handles cases where multiple terms of the same role need individual resolution.
    The pipeline should catch this and return all clarifications to the user.
    """

    def __init__(self, clarifications: List[Clarification]):
        self.clarifications = clarifications
        questions = [c.question for c in clarifications]
        super().__init__(f"Multiple clarifications needed: {'; '.join(questions)}")


# =============================================================================
# HELPER BUILDERS (OPTIONAL, BUT CLEAN)
# =============================================================================

def build_metric_clarification(
    ambiguous_terms: List[str],
    candidate_metrics: List[str],
) -> Clarification:

    if not ambiguous_terms:
        clarifying_question = "No metric mentioned. Choose one"
        clarifying_term = None
    else:
        clarifying_question = f"Which metric do you mean by '{', '.join(ambiguous_terms)}'?"
        clarifying_term = ambiguous_terms[0] if len(ambiguous_terms) == 1 else None

    return Clarification(
        request_id=str(uuid.uuid4()),
        field="metrics",
        question=clarifying_question,
        options=candidate_metrics,
        multi_select=False,
        clarifying_term=clarifying_term,
    )


def build_individual_metric_clarifications(
    ambiguous_terms: List[str],
    candidate_metrics: List[str],
) -> List[Clarification]:
    """
    Build individual clarification requests for each ambiguous metric term.

    This handles cases where multiple metric terms are classified and need
    individual resolution (e.g., "sales and revenue" should ask separately
    about "sales" and "revenue").
    """
    if not ambiguous_terms:
        return [build_metric_clarification([], candidate_metrics)]

    clarifications = []
    for term in ambiguous_terms:
        clarifying_question = f"Which metric do you mean by '{term}'?"
        clarifications.append(Clarification(
            request_id=str(uuid.uuid4()),
            field="metrics",
            question=clarifying_question,
            options=candidate_metrics,
            multi_select=False,
            context=f"Resolving ambiguous term: '{term}'"
        ))

    return clarifications


def build_dimension_clarification(
    ambiguous_terms: List[str],
    candidate_dimensions: List[str],
) -> Clarification:
    if not ambiguous_terms:
        clarifying_question = "No dimension mentioned. Choose one"
        clarifying_term = None
    else:
        clarifying_question = f"Which dimension do you mean by '{', '.join(ambiguous_terms)}'?"
        clarifying_term = ambiguous_terms[0] if len(ambiguous_terms) == 1 else None

    return Clarification(
        request_id=str(uuid.uuid4()),
        field="group_by",
        question=clarifying_question,
        options=candidate_dimensions,
        multi_select=False,
        clarifying_term=clarifying_term,
    )


def build_individual_dimension_clarifications(
    ambiguous_terms: List[str],
    candidate_dimensions: List[str],
) -> List[Clarification]:
    """
    Build individual clarification requests for each ambiguous dimension term.

    This handles cases where multiple dimension terms are classified and need
    individual resolution (e.g., "zone and region" should ask separately
    about "zone" and "region").
    """
    if not ambiguous_terms:
        return [build_dimension_clarification([], candidate_dimensions)]

    clarifications = []
    for term in ambiguous_terms:
        clarifying_question = f"Which dimension do you mean by '{term}'?"
        clarifications.append(Clarification(
            request_id=str(uuid.uuid4()),
            field="group_by",
            question=clarifying_question,
            options=candidate_dimensions,
            multi_select=False,
            context=f"Resolving ambiguous term: '{term}'"
        ))

    return clarifications


def build_time_clarification(
    ambiguous_expression: str,
    candidate_windows: List[str],
) -> Clarification:
    if ambiguous_expression == "time period":
        clarifying_question = "No time period mentioned. Choose one"
    else:
        clarifying_question = f"What time period do you mean by '{ambiguous_expression}'?"
    return Clarification(
        request_id=str(uuid.uuid4()),
        field="time",
        question=clarifying_question,
        options=candidate_windows,
        multi_select=False,
    )


def build_scope_clarification() -> Clarification:
    return Clarification(
        request_id=str(uuid.uuid4()),
        field="sales_scope",
        question="Which type of sales data do you want?",
        options=["PRIMARY", "SECONDARY"],
        multi_select=False,
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


def apply_multiple_clarification_overrides(
    overrides: Dict[str, Any],
    clarifications: List[Clarification],
    answers: List[ClarificationAnswer],
) -> Dict[str, Any]:
    """
    Apply multiple clarification answers into pipeline override dict.

    For multiple clarifications of the same field (e.g., multiple metrics),
    this aggregates the answers into a list.
    """
    if len(clarifications) != len(answers):
        raise ValueError("Clarifications and answers must have same length")

    # Group answers by field
    field_answers = {}
    for clarification, answer in zip(clarifications, answers):
        if clarification.request_id != answer.request_id:
            raise ValueError(f"Mismatched request IDs: {clarification.request_id} != {answer.request_id}")

        field = clarification.field
        if field not in field_answers:
            field_answers[field] = []

        if clarification.multi_select:
            if isinstance(answer.answer, list):
                field_answers[field].extend(answer.answer)
            else:
                field_answers[field].append(answer.answer)
        else:
            field_answers[field].append(answer.answer)

    # Update overrides with aggregated answers
    for field, answers_list in field_answers.items():
        if len(answers_list) == 1:
            overrides[field] = answers_list[0]
        else:
            overrides[field] = answers_list

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


def format_multiple_clarifications_response(clarifications: List[Clarification]) -> Dict[str, Any]:
    """
    Convert multiple clarifications into API-friendly response.
    """

    return {
        "type": "multiple_clarifications_required",
        "clarifications": [format_clarification_response(c) for c in clarifications],
        "count": len(clarifications),
    }