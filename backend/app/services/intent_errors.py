"""
Intent Validation Errors - Centralized failure taxonomy.

These are SYSTEM errors, not LLM errors.
They represent validation failures after the LLM has produced an intent.

Purpose:
- Clean, structured logs
- Predictable frontend behavior
- Explicit error codes for monitoring/alerting

Each error has:
- ERROR_CODE: Unique identifier for logging/monitoring
- message: Human-readable description
- to_dict(): Structured output for API responses
"""

from enum import Enum
from typing import Any, Dict, List, Optional


class IntentErrorCode(str, Enum):
    """
    Canonical error codes for intent validation failures.
    
    These codes are used for:
    - Logging and monitoring
    - Frontend error handling
    - Metrics and alerting
    """
    # Catalog validation errors
    UNKNOWN_METRIC = "UNKNOWN_METRIC"
    UNKNOWN_DIMENSION = "UNKNOWN_DIMENSION"
    UNKNOWN_TIME_DIMENSION = "UNKNOWN_TIME_DIMENSION"
    INVALID_TIME_WINDOW = "INVALID_TIME_WINDOW"
    INVALID_GRANULARITY = "INVALID_GRANULARITY"
    
    # Structural errors
    MALFORMED_INTENT = "MALFORMED_INTENT"
    INVALID_FILTER = "INVALID_FILTER"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    
    # Scope errors
    OUT_OF_SCOPE_INTENT = "OUT_OF_SCOPE_INTENT"
    UNSUPPORTED_INTENT_TYPE = "UNSUPPORTED_INTENT_TYPE"


class IntentValidationError(Exception):
    """
    Base class for all intent validation errors.
    
    All validation errors are HARD FAILURES - they should stop execution
    and return a clear error to the user.
    """
    
    ERROR_CODE: IntentErrorCode = None  # Override in subclasses
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Any = None,
        suggestions: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize validation error.
        
        Args:
            message: Human-readable error message
            field: Field name that caused the error (e.g., "metric", "group_by[0]")
            value: The invalid value
            suggestions: Suggested corrections (e.g., similar valid values)
            metadata: Additional context for debugging
        """
        self.message = message
        self.field = field
        self.value = value
        self.suggestions = suggestions or []
        self.metadata = metadata or {}
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert error to structured dict for API responses.
        
        Returns:
            {
                "error_code": "UNKNOWN_METRIC",
                "error_type": "UnknownMetricError",
                "message": "Unknown metric: 'total_sales'",
                "field": "metric",
                "value": "total_sales",
                "suggestions": ["total_quantity", "transaction_count"],
                "metadata": {...}
            }
        """
        return {
            "error_code": self.ERROR_CODE.value if self.ERROR_CODE else "VALIDATION_ERROR",
            "error_type": self.__class__.__name__,
            "message": self.message,
            "field": self.field,
            "value": self.value,
            "suggestions": self.suggestions,
            "metadata": self.metadata
        }


# ============================================================================
# CATALOG VALIDATION ERRORS
# ============================================================================

class UnknownMetricError(IntentValidationError):
    """
    ERROR_CODE: UNKNOWN_METRIC
    
    Raised when a metric is not found in the catalog.
    
    Example:
        User asks for "total_sales" but catalog only has "total_quantity"
    """
    ERROR_CODE = IntentErrorCode.UNKNOWN_METRIC
    
    def __init__(self, metric: str, suggestions: Optional[List[str]] = None):
        message = f"Unknown metric: '{metric}'"
        if suggestions:
            message += f". Did you mean: {', '.join(suggestions[:3])}?"
        super().__init__(
            message=message,
            field="metric",
            value=metric,
            suggestions=suggestions
        )


class UnknownDimensionError(IntentValidationError):
    """
    ERROR_CODE: UNKNOWN_DIMENSION
    
    Raised when a dimension is not found in the catalog.
    
    Example:
        User asks to group by "country" but catalog only has "region", "state"
    """
    ERROR_CODE = IntentErrorCode.UNKNOWN_DIMENSION
    
    def __init__(
        self,
        dimension: str,
        context: str = "group_by",
        suggestions: Optional[List[str]] = None
    ):
        message = f"Unknown dimension in {context}: '{dimension}'"
        if suggestions:
            message += f". Did you mean: {', '.join(suggestions[:3])}?"
        super().__init__(
            message=message,
            field=context,
            value=dimension,
            suggestions=suggestions,
            metadata={"context": context}
        )


class UnknownTimeDimensionError(IntentValidationError):
    """
    ERROR_CODE: UNKNOWN_TIME_DIMENSION
    
    Raised when a time dimension is not found in the catalog.
    
    Example:
        User asks for trend by "order_date" but catalog only has "invoice_date"
    """
    ERROR_CODE = IntentErrorCode.UNKNOWN_TIME_DIMENSION
    
    def __init__(self, time_dimension: str, suggestions: Optional[List[str]] = None):
        message = f"Unknown time dimension: '{time_dimension}'"
        if suggestions:
            message += f". Did you mean: {', '.join(suggestions[:3])}?"
        super().__init__(
            message=message,
            field="time_dimension.dimension",
            value=time_dimension,
            suggestions=suggestions
        )


class InvalidTimeWindowError(IntentValidationError):
    """
    ERROR_CODE: INVALID_TIME_WINDOW
    
    Raised when a time window is not recognized.
    
    Example:
        User specifies window="last_2_weeks" but catalog only has "last_7_days", "last_30_days"
    """
    ERROR_CODE = IntentErrorCode.INVALID_TIME_WINDOW
    
    def __init__(self, window: str, valid_windows: Optional[List[str]] = None):
        message = f"Invalid time window: '{window}'"
        if valid_windows:
            message += f". Valid options: {', '.join(valid_windows[:5])}"
        super().__init__(
            message=message,
            field="time_range.window",
            value=window,
            suggestions=valid_windows
        )


class InvalidGranularityError(IntentValidationError):
    """
    ERROR_CODE: INVALID_GRANULARITY
    
    Raised when time granularity is not valid.
    
    Example:
        User specifies granularity="hourly" but only day/week/month/quarter/year are supported
    """
    ERROR_CODE = IntentErrorCode.INVALID_GRANULARITY
    
    VALID_GRANULARITIES = ["day", "week", "month", "quarter", "year"]
    
    def __init__(self, granularity: str):
        message = f"Invalid granularity: '{granularity}'. Valid options: {', '.join(self.VALID_GRANULARITIES)}"
        super().__init__(
            message=message,
            field="time_dimension.granularity",
            value=granularity,
            suggestions=self.VALID_GRANULARITIES
        )




# ============================================================================
# STRUCTURAL ERRORS
# ============================================================================

class MalformedIntentError(IntentValidationError):
    """
    ERROR_CODE: MALFORMED_INTENT
    
    Raised when the raw intent dict cannot be parsed into an Intent object.
    
    This indicates the LLM output was structurally invalid (missing required fields,
    wrong types, violates Pydantic constraints, etc.)
    
    Example:
        - Missing "metric" field
        - "intent_type" is not "snapshot" or "trend"
        - "group_by" is a string instead of a list
    """
    ERROR_CODE = IntentErrorCode.MALFORMED_INTENT
    
    def __init__(self, message: str, raw_intent: Optional[Dict] = None):
        super().__init__(
            message=f"Malformed intent: {message}",
            field=None,
            value=None,
            metadata={"raw_intent": raw_intent}
        )


class InvalidFilterError(IntentValidationError):
    """
    ERROR_CODE: INVALID_FILTER
    
    Raised when a filter is invalid (unknown dimension, bad operator, etc.)
    
    Example:
        - Filter dimension not in catalog
        - Operator "in" used with single value instead of list
    """
    ERROR_CODE = IntentErrorCode.INVALID_FILTER
    
    def __init__(self, message: str, filter_index: int, dimension: Optional[str] = None):
        super().__init__(
            message=message,
            field=f"filters[{filter_index}]",
            value=dimension,
            metadata={"filter_index": filter_index, "dimension": dimension}
        )


class InvalidTimeRangeError(IntentValidationError):
    """
    ERROR_CODE: INVALID_TIME_RANGE
    
    Raised when time range specification is invalid.
    
    Example:
        - Both window and explicit dates specified
        - start_date without end_date
        - Invalid date format
    """
    ERROR_CODE = IntentErrorCode.INVALID_TIME_RANGE
    
    def __init__(self, message: str, time_range: Optional[Dict] = None):
        super().__init__(
            message=f"Invalid time range: {message}",
            field="time_range",
            value=None,
            metadata={"time_range": time_range}
        )


# ============================================================================
# SCOPE ERRORS
# ============================================================================

class OutOfScopeIntentError(IntentValidationError):
    """
    ERROR_CODE: OUT_OF_SCOPE_INTENT
    
    Raised when the user's query is outside the system's capabilities.
    
    Example:
        - User asks for predictive analytics (we only do descriptive)
        - User asks to modify data (we only read)
        - User asks about entities not in our catalog
    """
    ERROR_CODE = IntentErrorCode.OUT_OF_SCOPE_INTENT
    
    def __init__(self, message: str, intent_summary: Optional[str] = None):
        super().__init__(
            message=f"Out of scope: {message}",
            field=None,
            value=None,
            metadata={"intent_summary": intent_summary}
        )


class UnsupportedIntentTypeError(IntentValidationError):
    """
    ERROR_CODE: UNSUPPORTED_INTENT_TYPE
    
    Raised when the intent type is not supported by the system.
    
    Example:
        - LLM outputs intent_type="comparison" but we only support "snapshot" and "trend"
    """
    ERROR_CODE = IntentErrorCode.UNSUPPORTED_INTENT_TYPE
    
    def __init__(self, intent_type: str, supported_types: Optional[List[str]] = None):
        supported = supported_types or ["snapshot", "trend"]
        message = f"Unsupported intent type: '{intent_type}'. Supported types: {', '.join(supported)}"
        super().__init__(
            message=message,
            field="intent_type",
            value=intent_type,
            suggestions=supported,
            metadata={"supported_types": supported}
        )


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def format_error_response(error: IntentValidationError) -> Dict[str, Any]:
    """
    Format an IntentValidationError for API response.
    
    Args:
        error: The validation error
        
    Returns:
        Structured error dict suitable for JSON response
        
    Example:
        {
            "success": false,
            "error": {
                "error_code": "UNKNOWN_METRIC",
                "error_type": "UnknownMetricError",
                "message": "Unknown metric: 'total_sales'. Did you mean: total_quantity?",
                "field": "metric",
                "value": "total_sales",
                "suggestions": ["total_quantity", "transaction_count"],
                "metadata": {}
            }
        }
    """
    return {
        "success": False,
        "error": error.to_dict()
    }
