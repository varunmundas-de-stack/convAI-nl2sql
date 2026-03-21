"""
Type-Agnostic Clarification Tool for DSPy Agents

This tool allows DSPy agents to request clarification from users when query
intent is ambiguous or incomplete. Supports any type of clarification need
with rich options, multiple selection, and comprehensive validation.

Key Features:
- Type-agnostic: Handle any clarification type (metrics, dimensions, time, scope, custom)
- Rich options: Support detailed descriptions and metadata
- Multiple selection: Allow single or multiple option selection
- Custom values: Support user-provided custom values when options aren't sufficient
- DSPy integration: Clean exception-based interface for DSPy agents
- Comprehensive validation: Robust error handling and constraint validation
"""

import logging
import uuid
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, ConfigDict, validator
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# =============================================================================
# TYPE DEFINITIONS AND MODELS
# =============================================================================

class ClarificationType(str, Enum):
    """Types of clarifications that can be requested."""
    METRIC = "metric"
    DIMENSION = "dimension"
    SCOPE = "scope"
    TIME = "time"
    TIME_WINDOW = "time_window"
    TIME_GRANULARITY = "time_granularity"
    FILTER = "filter"
    AGGREGATION = "aggregation"
    COMPARISON = "comparison"
    RANKING = "ranking"
    GROUP_BY = "group_by"
    GENERAL = "general"
    CUSTOM = "custom"


class ClarificationOption(BaseModel):
    """A single clarification option that the user can select."""
    id: str = Field(..., description="Unique identifier for this option")
    label: str = Field(..., description="Human-readable label shown to the user")
    description: Optional[str] = Field(None, description="Detailed description of this option")
    value: Any = Field(..., description="The actual value to use if selected")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional option metadata")

    model_config = ConfigDict(extra="forbid")


class ClarificationRequest(BaseModel):
    """Request for clarification from a DSPy agent."""
    # Core identification
    clarification_type: ClarificationType = Field(..., description="Type of clarification needed")
    field_name: str = Field(..., description="Name of the field that needs clarification")
    field_path: Optional[str] = Field(None, description="Dot-notation path to nested field (e.g., 'time.granularity')")

    # User-facing content
    question: str = Field(..., description="Question to ask the user")
    context: str = Field(..., description="Context explaining why clarification is needed")
    help_text: Optional[str] = Field(None, description="Additional help text for the user")

    # Options and constraints
    options: List[ClarificationOption] = Field(..., description="Available clarification options")
    allow_custom: bool = Field(default=True, description="Whether user can provide custom input")
    allow_multiple: bool = Field(default=False, description="Whether user can select multiple options")
    required: bool = Field(default=True, description="Whether this clarification is required to proceed")

    # Metadata
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional request metadata")

    model_config = ConfigDict(extra="forbid")


class ClarificationResponse(BaseModel):
    """Response to a clarification request."""
    request_id: str = Field(..., description="ID of the original clarification request")
    selected_option_ids: List[str] = Field(default_factory=list, description="IDs of selected options")
    custom_value: Optional[Any] = Field(None, description="Custom value provided by user")
    resolved_value: Any = Field(..., description="Final resolved value to use")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence in resolution (0.0-1.0)")
    user_notes: Optional[str] = Field(None, description="Additional notes from the user")

    model_config = ConfigDict(extra="forbid")


@dataclass
class ClarificationContext:
    """Context information for clarification requests from DSPy agents."""
    agent_name: str
    step_name: str
    input_data: Any
    partial_output: Any = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ClarificationRequiredException(Exception):
    """
    Exception raised when a DSPy agent needs clarification to proceed.

    This exception signals that the agent cannot continue without user input.
    The exception carries the clarification request details.
    """
    def __init__(
        self,
        request_id: str,
        clarification_request: ClarificationRequest,
        agent_context: Optional[Dict[str, Any]] = None
    ):
        self.request_id = request_id
        self.clarification_request = clarification_request
        self.agent_context = agent_context or {}
        super().__init__(f"Clarification required: {clarification_request.question}")


# =============================================================================
# CLARIFICATION TOOL
# =============================================================================

class ClarificationTool:
    """
    Type-agnostic clarification tool for DSPy agents.

    Allows agents to request clarification when query intent is ambiguous.
    Supports any type of clarification with rich options, multiple selection,
    custom values, and comprehensive validation.

    Features:
    - Type-agnostic clarification requests
    - Rich option metadata and descriptions
    - Multiple selection support
    - Custom value support
    - Comprehensive error handling
    - State persistence

    Usage:
        tool = ClarificationTool()

        # Request clarification
        request_id = tool.request_clarification(
            clarification_type=ClarificationType.METRIC,
            field_name="metrics",
            question="Which metric would you like to analyze?",
            context="Your query mentioned 'sales' which could refer to multiple metrics",
            options=[
                ClarificationOption(id="net", label="Net Sales", value="net_value"),
                ClarificationOption(id="gross", label="Gross Sales", value="gross_value")
            ]
        )

        # Provide answer
        response = tool.provide_clarification(
            request_id=request_id,
            selected_option_ids=["net"]
        )
    """

    def __init__(self):
        """Initialize the clarification tool."""
        self.pending_requests: Dict[str, ClarificationRequest] = {}
        self.completed_responses: Dict[str, ClarificationResponse] = {}
        # Per-request overrides: {field_name: resolved_catalog_value}
        # Populated by the resume path before re-running the pipeline.
        # Cleared at the start of every fresh (non-resume) pipeline run.
        self.field_resolved_overrides: Dict[str, str] = {}

    def reset_for_new_request(self) -> None:
        """
        Clear per-request state so a fresh query never sees answers
        from a prior user session.

        Call this at the start of every NEW (non-resume) pipeline execution.
        """
        self.field_resolved_overrides = {}

    def set_field_override(self, field_name: str, resolved_value: str) -> None:
        """
        Store a resolved clarification answer for the current re-run.

        Called by the resume path BEFORE re-running the pipeline so that
        agents can skip re-asking the same clarification question.

        Args:
            field_name:     e.g. "group_by" or "metrics"
            resolved_value: the catalog value, e.g. "state" or "net_value"
        """
        self.field_resolved_overrides[field_name] = resolved_value
        logger.debug(
            f"[ClarificationTool] Field override set: {field_name!r} → {resolved_value!r}"
        )

    def get_field_override(self, field_name: str) -> Optional[str]:
        """
        Retrieve the resolved value for a field (if set for this re-run).

        Returns None when running fresh (no prior clarification for this field).
        """
        return self.field_resolved_overrides.get(field_name)


    def request_clarification(
        self,
        clarification_type: ClarificationType,
        field_name: str,
        question: str,
        context: str,
        options: List[ClarificationOption],
        field_path: Optional[str] = None,
        help_text: Optional[str] = None,
        allow_custom: bool = True,
        allow_multiple: bool = False,
        required: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Request clarification from the user.

        Args:
            clarification_type: Type of clarification needed
            field_name: Name of the field needing clarification
            question: Question to ask the user
            context: Context about why clarification is needed
            options: Available options for clarification
            field_path: Dot-notation path for nested fields (optional)
            help_text: Additional help text (optional)
            allow_custom: Whether user can provide custom input
            allow_multiple: Whether user can select multiple options
            required: Whether this clarification is required
            metadata: Additional metadata

        Returns:
            request_id: Unique ID for this clarification request

        Raises:
            ValueError: If options are empty or invalid

        Example:
            >>> tool = ClarificationTool()
            >>> options = [
            ...     ClarificationOption(id="net", label="Net Sales", value="net_value"),
            ...     ClarificationOption(id="gross", label="Gross Sales", value="gross_value")
            ... ]
            >>> request_id = tool.request_clarification(
            ...     ClarificationType.METRIC,
            ...     "metrics",
            ...     "Which type of sales do you mean?",
            ...     "The term 'sales' could refer to net sales or gross sales",
            ...     options
            ... )
        """
        if not options:
            raise ValueError("At least one clarification option must be provided")

        # Validate options have unique IDs
        option_ids = [opt.id for opt in options]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("Clarification options must have unique IDs")

        request_id = str(uuid.uuid4())

        request = ClarificationRequest(
            clarification_type=clarification_type,
            field_name=field_name,
            field_path=field_path,
            question=question,
            context=context,
            help_text=help_text,
            options=options,
            allow_custom=allow_custom,
            allow_multiple=allow_multiple,
            required=required,
            metadata=metadata or {}
        )

        self.pending_requests[request_id] = request

        logger.info(f"🤔 [ClarificationTool] Clarification requested")
        logger.info(f"🤔 [ClarificationTool] Type: {clarification_type.value}")
        logger.info(f"🤔 [ClarificationTool] Field: {field_name}")
        logger.info(f"🤔 [ClarificationTool] Question: {question}")
        logger.info(f"🤔 [ClarificationTool] Options: {len(options)} available")

        return request_id

    def provide_clarification(
        self,
        request_id: str,
        selected_option_ids: Optional[List[str]] = None,
        custom_value: Optional[Any] = None,
        user_notes: Optional[str] = None
    ) -> ClarificationResponse:
        """
        Provide clarification response.

        Args:
            request_id: ID of the clarification request
            selected_option_ids: IDs of the selected options
            custom_value: Custom value provided by user
            user_notes: Additional notes from the user

        Returns:
            ClarificationResponse with resolved value

        Raises:
            ValueError: If request not found, invalid options, or invalid response

        Example:
            >>> response = tool.provide_clarification(
            ...     request_id=request_id,
            ...     selected_option_ids=["net"]
            ... )
            >>> print(response.resolved_value)  # "net_value"
        """
        if request_id not in self.pending_requests:
            raise ValueError(f"No pending clarification request with ID: {request_id}")

        request = self.pending_requests[request_id]

        # Resolve the value based on response
        resolved_value = None
        confidence = 1.0
        selected_option_ids = selected_option_ids or []

        if selected_option_ids:
            # Validate selected options exist
            valid_option_ids = {opt.id for opt in request.options}
            invalid_ids = set(selected_option_ids) - valid_option_ids
            if invalid_ids:
                raise ValueError(f"Invalid option IDs: {list(invalid_ids)}")

            # Check multiple selection constraint
            if len(selected_option_ids) > 1 and not request.allow_multiple:
                raise ValueError("Multiple selections not allowed for this clarification")

            # Get selected options
            selected_options = [
                opt for opt in request.options
                if opt.id in selected_option_ids
            ]

            if request.allow_multiple:
                # Multiple selection: return list of values
                resolved_value = [opt.value for opt in selected_options]
            else:
                # Single selection: return single value
                resolved_value = selected_options[0].value

            logger.info(f"🤔 [ClarificationTool] Selected options: {[opt.label for opt in selected_options]}")

        elif custom_value is not None:
            if not request.allow_custom:
                raise ValueError("Custom values not allowed for this clarification")
            resolved_value = custom_value
            confidence = 0.8  # Lower confidence for custom values
            logger.info(f"🤔 [ClarificationTool] Custom value provided: {custom_value}")

        else:
            if request.required:
                raise ValueError("Clarification is required but no response provided")
            resolved_value = None
            confidence = 0.0
            logger.info(f"🤔 [ClarificationTool] No response provided for optional clarification")

        response = ClarificationResponse(
            request_id=request_id,
            selected_option_ids=selected_option_ids,
            custom_value=custom_value,
            resolved_value=resolved_value,
            confidence=confidence,
            user_notes=user_notes
        )

        # Move from pending to completed
        self.completed_responses[request_id] = response
        del self.pending_requests[request_id]

        logger.info(f"🤔 [ClarificationTool] ✅ Clarification resolved")
        logger.info(f"🤔 [ClarificationTool] Resolved value: {resolved_value}")
        logger.info(f"🤔 [ClarificationTool] Confidence: {confidence:.1f}")

        return response

    def get_clarification_request(self, request_id: str) -> Optional[ClarificationRequest]:
        """Get a clarification request by ID."""
        return self.pending_requests.get(request_id)

    def get_clarification_response(self, request_id: str) -> Optional[ClarificationResponse]:
        """Get a clarification response by request ID."""
        return self.completed_responses.get(request_id)

    def get_pending_requests(self) -> Dict[str, ClarificationRequest]:
        """Get all pending clarification requests."""
        return self.pending_requests.copy()

    def get_completed_responses(self) -> Dict[str, ClarificationResponse]:
        """Get all completed clarification responses."""
        return self.completed_responses.copy()

    def has_pending_clarifications(self) -> bool:
        """Check if there are any pending clarifications."""
        return len(self.pending_requests) > 0

    def cancel_clarification(self, request_id: str) -> bool:
        """
        Cancel a pending clarification request.

        Args:
            request_id: ID of the request to cancel

        Returns:
            True if cancelled, False if request not found
        """
        if request_id in self.pending_requests:
            del self.pending_requests[request_id]
            logger.info(f"🤔 [ClarificationTool] Cancelled clarification request {request_id}")
            return True
        return False

    def clear_all(self) -> None:
        """Clear all clarification data (for testing/cleanup)."""
        self.pending_requests.clear()
        self.completed_responses.clear()
        logger.debug("🤔 [ClarificationTool] Cleared all clarification data")

    # DSPy Agent Interface Methods
    def request_metric_clarification(
        self,
        ambiguous_terms: List[str],
        available_metrics: List[Dict[str, str]],
        agent_context: Optional[ClarificationContext] = None,
        **kwargs
    ) -> str:
        """
        Request clarification for ambiguous metric terms.

        Args:
            ambiguous_terms: Terms that could refer to multiple metrics
            available_metrics: Available metric options
            agent_context: DSPy agent context
            **kwargs: Additional arguments

        Returns:
            request_id: Clarification request ID

        Raises:
            ClarificationRequiredException: Always raised to signal clarification needed
        """
        options = [
            ClarificationOption(
                id=metric["name"],
                label=metric["label"],
                description=metric.get("description"),
                value=metric["name"]
            )
            for metric in available_metrics
        ]

        # Add agent context to metadata
        metadata = kwargs.get('metadata', {})
        if agent_context:
            metadata.update({
                'agent_name': agent_context.agent_name,
                'step_name': agent_context.step_name,
                'input_data': str(agent_context.input_data)[:500],  # Truncate for storage
                'agent_metadata': agent_context.metadata
            })
            kwargs['metadata'] = metadata

        request_id = self.request_clarification(
            clarification_type=ClarificationType.METRIC,
            field_name="metrics",
            question=f"Which metric do you mean by '{', '.join(ambiguous_terms)}'?",
            context=f"The term(s) '{', '.join(ambiguous_terms)}' could refer to multiple metrics",
            options=options,
            allow_custom=False,
            **kwargs
        )

        # Get the request object
        request = self.get_clarification_request(request_id)

        # Raise exception to signal clarification needed
        raise ClarificationRequiredException(
            request_id=request_id,
            clarification_request=request,
            agent_context=agent_context.__dict__ if agent_context else None
        )

    def request_dimension_clarification(
        self,
        ambiguous_terms: List[str],
        available_dimensions: List[Dict[str, str]],
        agent_context: Optional[ClarificationContext] = None,
        **kwargs
    ) -> str:
        """
        Request clarification for ambiguous dimension terms.

        Args:
            ambiguous_terms: Terms that could refer to multiple dimensions
            available_dimensions: Available dimension options
            agent_context: DSPy agent context
            **kwargs: Additional arguments

        Returns:
            request_id: Clarification request ID

        Raises:
            ClarificationRequiredException: Always raised
        """
        options = [
            ClarificationOption(
                id=dim["name"],
                label=dim["label"],
                description=dim.get("description"),
                value=dim["name"]
            )
            for dim in available_dimensions
        ]

        # Add agent context to metadata
        metadata = kwargs.get('metadata', {})
        if agent_context:
            metadata.update({
                'agent_name': agent_context.agent_name,
                'step_name': agent_context.step_name,
                'input_data': str(agent_context.input_data)[:500],
                'agent_metadata': agent_context.metadata
            })
            kwargs['metadata'] = metadata

        request_id = self.request_clarification(
            clarification_type=ClarificationType.DIMENSION,
            field_name="group_by",
            question=f"Which dimension do you mean by '{', '.join(ambiguous_terms)}'?",
            context=f"The term(s) '{', '.join(ambiguous_terms)}' could refer to multiple dimensions",
            options=options,
            allow_custom=False,
            **kwargs
        )

        # Get the request object
        request = self.get_clarification_request(request_id)

        # Raise exception to signal clarification needed
        raise ClarificationRequiredException(
            request_id=request_id,
            clarification_request=request,
            agent_context=agent_context.__dict__ if agent_context else None
        )

    def request_time_granularity_clarification(
        self,
        agent_context: Optional[ClarificationContext] = None,
        **kwargs
    ) -> str:
        """
        Request clarification for time granularity.

        Args:
            agent_context: DSPy agent context
            **kwargs: Additional arguments

        Returns:
            request_id: Clarification request ID

        Raises:
            ClarificationRequiredException: Always raised
        """
        granularities = ["day", "week", "month", "quarter", "year"]
        options = [
            ClarificationOption(
                id=granularity,
                label=granularity.title(),
                description=f"Group results by {granularity}",
                value=granularity
            )
            for granularity in granularities
        ]

        # Add agent context to metadata
        metadata = kwargs.get('metadata', {})
        if agent_context:
            metadata.update({
                'agent_name': agent_context.agent_name,
                'step_name': agent_context.step_name,
                'input_data': str(agent_context.input_data)[:500],
                'agent_metadata': agent_context.metadata
            })
            kwargs['metadata'] = metadata

        request_id = self.request_clarification(
            clarification_type=ClarificationType.TIME_GRANULARITY,
            field_name="time.granularity",
            field_path="time.granularity",
            question="What time granularity would you like for the trend?",
            context="Trend analysis requires specifying how to group the time periods",
            options=options,
            allow_custom=False,
            **kwargs
        )

        # Get the request object
        request = self.get_clarification_request(request_id)

        # Raise exception to signal clarification needed
        raise ClarificationRequiredException(
            request_id=request_id,
            clarification_request=request,
            agent_context=agent_context.__dict__ if agent_context else None
        )

    def request_scope_clarification(
        self,
        agent_context: Optional[ClarificationContext] = None,
        **kwargs
    ) -> str:
        """
        Request clarification for sales scope.

        Args:
            agent_context: DSPy agent context
            **kwargs: Additional arguments

        Returns:
            request_id: Clarification request ID

        Raises:
            ClarificationRequiredException: Always raised
        """
        options = [
            ClarificationOption(
                id="primary",
                label="Primary Sales",
                description="Sales from company to distributors",
                value="PRIMARY"
            ),
            ClarificationOption(
                id="secondary",
                label="Secondary Sales",
                description="Sales from distributors to retailers",
                value="SECONDARY"
            )
        ]

        # Add agent context to metadata
        metadata = kwargs.get('metadata', {})
        if agent_context:
            metadata.update({
                'agent_name': agent_context.agent_name,
                'step_name': agent_context.step_name,
                'input_data': str(agent_context.input_data)[:500],
                'agent_metadata': agent_context.metadata
            })
            kwargs['metadata'] = metadata

        request_id = self.request_clarification(
            clarification_type=ClarificationType.SCOPE,
            field_name="sales_scope",
            question="Which type of sales data do you want?",
            context="The query doesn't specify whether you want Primary or Secondary sales",
            options=options,
            allow_custom=False,
            **kwargs
        )

        # Get the request object
        request = self.get_clarification_request(request_id)

        # Raise exception to signal clarification needed
        raise ClarificationRequiredException(
            request_id=request_id,
            clarification_request=request,
            agent_context=agent_context.__dict__ if agent_context else None
        )


# =============================================================================
# HELPER FUNCTIONS FOR COMMON CLARIFICATIONS
# =============================================================================

def create_metric_clarification(
    ambiguous_terms: List[str],
    available_metrics: List[Dict[str, str]]
) -> ClarificationRequest:
    """
    Create a metric clarification request.

    Args:
        ambiguous_terms: Terms that could refer to multiple metrics
        available_metrics: List of dicts with 'name', 'label', 'description'

    Returns:
        ClarificationRequest ready to be used
    """
    options = [
        ClarificationOption(
            id=metric["name"],
            label=metric["label"],
            description=metric.get("description"),
            value=metric["name"]
        )
        for metric in available_metrics
    ]

    return ClarificationRequest(
        clarification_type=ClarificationType.METRIC,
        field_name="metrics",
        question=f"Which metric do you mean by '{', '.join(ambiguous_terms)}'?",
        context=f"The term(s) '{', '.join(ambiguous_terms)}' could refer to multiple metrics",
        options=options,
        allow_custom=False,
        required=True
    )


def create_dimension_clarification(
    ambiguous_terms: List[str],
    available_dimensions: List[Dict[str, str]]
) -> ClarificationRequest:
    """
    Create a dimension clarification request.

    Args:
        ambiguous_terms: Terms that could refer to multiple dimensions
        available_dimensions: List of dicts with 'name', 'label', 'description'

    Returns:
        ClarificationRequest ready to be used
    """
    options = [
        ClarificationOption(
            id=dim["name"],
            label=dim["label"],
            description=dim.get("description"),
            value=dim["name"]
        )
        for dim in available_dimensions
    ]

    return ClarificationRequest(
        clarification_type=ClarificationType.DIMENSION,
        field_name="group_by",
        question=f"Which dimension do you mean by '{', '.join(ambiguous_terms)}'?",
        context=f"The term(s) '{', '.join(ambiguous_terms)}' could refer to multiple dimensions",
        options=options,
        allow_custom=False,
        required=True
    )


def create_time_clarification(
    ambiguous_expression: str,
    possible_interpretations: List[Dict[str, Any]]
) -> ClarificationRequest:
    """
    Create a time clarification request.

    Args:
        ambiguous_expression: The ambiguous time expression
        possible_interpretations: List of dicts with time interpretations

    Returns:
        ClarificationRequest ready to be used
    """
    options = [
        ClarificationOption(
            id=f"time_{i}",
            label=interp["label"],
            description=interp.get("description"),
            value=interp["value"]
        )
        for i, interp in enumerate(possible_interpretations)
    ]

    return ClarificationRequest(
        clarification_type=ClarificationType.TIME,
        field_name="time",
        question=f"What time period do you mean by '{ambiguous_expression}'?",
        context=f"The expression '{ambiguous_expression}' could have multiple interpretations",
        options=options,
        allow_custom=True,
        required=True
    )


def create_scope_clarification() -> ClarificationRequest:
    """
    Create a sales scope clarification request.

    Returns:
        ClarificationRequest for PRIMARY vs SECONDARY scope
    """
    options = [
        ClarificationOption(
            id="primary",
            label="Primary Sales",
            description="Sales from company to distributors",
            value="PRIMARY"
        ),
        ClarificationOption(
            id="secondary",
            label="Secondary Sales",
            description="Sales from distributors to retailers",
            value="SECONDARY"
        )
    ]

    return ClarificationRequest(
        clarification_type=ClarificationType.SCOPE,
        field_name="sales_scope",
        question="Which type of sales data do you want?",
        context="The query doesn't specify whether you want Primary or Secondary sales",
        options=options,
        allow_custom=False,
        required=True
    )


def handle_clarification_exception(
    exception: ClarificationRequiredException,
    return_request: bool = True
) -> Union[ClarificationRequest, Dict[str, Any]]:
    """
    Handle a clarification exception from a DSPy agent.

    Args:
        exception: The clarification exception
        return_request: Whether to return the request object or a dict

    Returns:
        Either the clarification request object or a dict representation
    """
    logger.info(f"🤔 Handling clarification exception: {exception.request_id}")

    if return_request:
        return exception.clarification_request
    else:
        return {
            "type": "clarification_required",
            "request_id": exception.request_id,
            "clarification": exception.clarification_request.model_dump(),
            "agent_context": exception.agent_context
        }


# =============================================================================
# GLOBAL CLARIFICATION TOOL INSTANCE
# =============================================================================

# Global instance for use across DSPy agents
clarification_tool = ClarificationTool()