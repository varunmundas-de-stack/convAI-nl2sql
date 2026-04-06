import uuid
import logging
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)


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


# =============================================================================
# CLARIFICATION TOOL - STATE MANAGEMENT
# =============================================================================

class ClarificationTool:
    """
    Manages clarification state across pipeline executions.

    This tool tracks active clarifications by session and request,
    providing cleanup methods to prevent stale clarifications from
    persisting across queries in the same session.
    """

    def __init__(self):
        # In-memory stores for clarification state
        # Format: {"session_id:request_id": {...}, ...}
        self._active_clarifications: Dict[str, Dict] = {}

        # Session-level resolved term mappings that persist across queries
        # Format: {"session_id": {"resolved_metric_terms": {"sales": "net_value"}, ...}}
        self._session_resolved_terms: Dict[str, Dict[str, Dict[str, str]]] = {}

    def reset_for_new_request(self, session_id: Optional[str] = None) -> None:
        """
        Reset clarification tool for a new request.

        Args:
            session_id: Optional session ID to reset. If None, resets all state.
        """
        if session_id is None:
            # Global reset for brand-new sessions
            self._active_clarifications.clear()
            self._session_resolved_terms.clear()
            logger.debug("Reset all clarification state")
        else:
            # Session-specific reset for follow-up queries
            # Remove all active clarifications for this session (clear pending state)
            keys_to_remove = [
                key for key in self._active_clarifications.keys()
                if key.startswith(f"{session_id}:")
            ]
            for key in keys_to_remove:
                del self._active_clarifications[key]

            # Keep session-level resolved terms (they should persist across queries)
            # Only clear if this is explicitly a reset of resolved state too
            # (for now, preserve resolved terms)

            logger.debug(f"Reset active clarifications for session {session_id}, kept resolved terms")

    def reset_session_completely(self, session_id: str) -> None:
        """
        Completely reset all clarification state for a session, including resolved terms.
        Use this for session termination or when user explicitly wants fresh state.
        """
        # Remove all active clarifications for this session
        keys_to_remove = [
            key for key in self._active_clarifications.keys()
            if key.startswith(f"{session_id}:")
        ]
        for key in keys_to_remove:
            del self._active_clarifications[key]

        # Clear session-level resolved terms
        if session_id in self._session_resolved_terms:
            del self._session_resolved_terms[session_id]

        logger.debug(f"Completely reset all clarification state for session {session_id}")

    def cleanup_request_state(self, request_id_prefix: str, max_entries: int = 100) -> int:
        """
        Clean up clarification state for completed requests.

        Args:
            request_id_prefix: Prefix to match request IDs for cleanup
            max_entries: Maximum entries to clean (for safety)

        Returns:
            Number of entries cleaned up
        """
        cleaned_count = 0

        # Clean up active clarifications
        keys_to_remove = []
        for key in self._active_clarifications.keys():
            if request_id_prefix in key and cleaned_count < max_entries:
                keys_to_remove.append(key)
                cleaned_count += 1

        for key in keys_to_remove:
            del self._active_clarifications[key]

        logger.debug(f"Cleaned up {cleaned_count} clarification entries for prefix {request_id_prefix}")
        return cleaned_count

    def store_clarification(self, session_id: str, request_id: str, clarification: Dict) -> None:
        """Store a clarification request."""
        key = f"{session_id}:{request_id}"
        self._active_clarifications[key] = clarification

    def get_clarification(self, session_id: str, request_id: str) -> Optional[Dict]:
        """Retrieve a clarification request."""
        key = f"{session_id}:{request_id}"
        return self._active_clarifications.get(key)

    def has_active_clarifications(self, session_id: str) -> bool:
        """Check if a session has any active clarifications."""
        return any(
            key.startswith(f"{session_id}:")
            for key in self._active_clarifications.keys()
        )

    def store_resolved_term(self, session_id: str, term_type: str, original_term: str, resolved_value: str) -> None:
        """
        Store a resolved term mapping for future queries in the same session.

        Args:
            session_id: Session identifier
            term_type: Type of term ('metric', 'dimension', etc.)
            original_term: Original ambiguous term (e.g., 'sales')
            resolved_value: Resolved value (e.g., 'net_value')
        """
        if session_id not in self._session_resolved_terms:
            self._session_resolved_terms[session_id] = {}

        term_key = f"resolved_{term_type}_terms"
        if term_key not in self._session_resolved_terms[session_id]:
            self._session_resolved_terms[session_id][term_key] = {}

        self._session_resolved_terms[session_id][term_key][original_term] = resolved_value
        logger.debug(f"Stored resolved term mapping for session {session_id}: {original_term} -> {resolved_value}")

    def get_resolved_terms(self, session_id: str) -> Dict[str, Dict[str, str]]:
        """
        Get all resolved term mappings for a session.

        Returns:
            Dictionary of term mappings like {'resolved_metric_terms': {'sales': 'net_value'}}
        """
        return self._session_resolved_terms.get(session_id, {})


# Singleton instance for use by the pipeline
clarification_tool = ClarificationTool()


# =============================================================================
# TESTING (for development)
# =============================================================================

if __name__ == "__main__":
    # Simple test to verify functionality
    print("Testing ClarificationTool...")

    # Test basic functionality
    tool = ClarificationTool()
    tool.store_resolved_term("session1", "metric", "sales", "net_value")
    tool.store_resolved_term("session1", "dimension", "region", "zone")

    resolved_terms = tool.get_resolved_terms("session1")
    assert "resolved_metric_terms" in resolved_terms
    assert resolved_terms["resolved_metric_terms"]["sales"] == "net_value"
    print("Store and retrieve resolved terms works")

    # Test session reset preserves resolved terms
    tool.store_clarification("session1", "req1", {"field": "metrics", "question": "test"})
    assert tool.has_active_clarifications("session1")

    tool.reset_for_new_request(session_id="session1")
    assert not tool.has_active_clarifications("session1")
    resolved_terms = tool.get_resolved_terms("session1")
    assert resolved_terms["resolved_metric_terms"]["sales"] == "net_value"
    print("Session reset preserves resolved terms")

    # Test complete reset
    tool.reset_session_completely("session1")
    assert not tool.has_active_clarifications("session1")
    assert tool.get_resolved_terms("session1") == {}
    print("Complete session reset works")

    print("All tests passed! ClarificationTool is working correctly.")