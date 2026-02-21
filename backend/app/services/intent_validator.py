"""
Intent Validator - Semantic validation gate for NL2SQL system.

This is the critical security/safety layer that ensures:
"The LLM cannot cause unsafe execution."

Responsibilities:
- Convert raw dict → Intent (Pydantic model)
- Validate against catalog (metrics, dimensions, time)
- Reject unknown/invalid fields with HARD FAIL

NO business logic. NO LLM logic. Only validation.
"""

from typing import Any, Dict, List, Optional

from app.models.intent import (
    Intent,
    IntentType,
    Filter,
    TimeSpec,
    Metric,
)
from app.services.catalog_manager import CatalogManager
from app.services.intent_errors import (
    IntentValidationError,
    MalformedIntentError,
    UnknownMetricError,
    UnknownDimensionError,
    UnknownTimeDimensionError,
    InvalidTimeWindowError,
    InvalidGranularityError,
    InvalidFilterError,
    InvalidTimeRangeError,
    IntentIncompleteError,
)
from pydantic import ValidationError


class IntentValidator:
    """
    Validates raw intent dictionaries against the catalog and intent rules.
    
    This is the semantic validation gate - if validation passes, the intent
    is safe to execute against the data layer.
    
    Usage:
        validator = IntentValidator(catalog_manager)
        intent = validator.validate(raw_intent_dict)  # raises on failure
    """
    
    VALID_GRANULARITIES = {"day", "week", "month", "quarter", "year"}
    
    def __init__(self, catalog: CatalogManager):
        self.catalog = catalog
    
    def validate(self, raw_intent: Dict[str, Any]) -> Intent:
        """
        Validate a raw intent dictionary and return a validated Intent object.

        Performs:
        1. Structural validation (Pydantic parsing)
        2. Metric validation (exists in catalog)
        3. Dimension validation (group_by fields exist)
        4. Intent-specific validation (time spec, granularity)
        5. Filter validation
        """
        intent = self._parse_intent(raw_intent)
        missing_fields: list[str] = []
        clarification_questions: list[str] = []
        
        # Validate metrics
        if not intent.metrics:
            missing_fields.append("metrics")
            clarification_questions.append("What would you like to measure?")
        else:
            for m in intent.metrics:
                self._validate_metric(m.name)
        
        # Validate group_by dimensions
        if intent.group_by:
            self._validate_dimensions(intent.group_by, context="group_by")
        
        # Validate time spec if present
        if intent.time is not None:
            self._validate_time_spec(intent.time)

        # Intent-specific validation
        intent_type = derive_intent_type_safe(intent)

        if intent_type == IntentType.TREND:
            if intent.time is None:
                missing_fields.append("time")
                clarification_questions.append(
                    "What time range and granularity would you like to use?"
                )
            elif intent.time.granularity is None:
                missing_fields.append("time.granularity")
                clarification_questions.append(
                    "What time granularity would you like? e.g. day, week, month"
                )

        elif intent_type in (IntentType.RANKING, IntentType.DISTRIBUTION):
            if not intent.group_by:
                missing_fields.append("group_by")
                clarification_questions.append("What would you like to group or rank by?")
        
        # Validate filters
        if intent.filters:
            self._validate_filters(intent.filters)
        
        if missing_fields:
            raise IntentIncompleteError(
                missing_fields=missing_fields,
                clarification_message=" ".join(clarification_questions),
            )
        return intent

    
    def _preprocess_intent(self, raw_intent: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pre-process raw intent to fix common LLM output issues.
        
        Currently a passthrough - can be extended for future fixes.
        """
        return raw_intent.copy()
    
    def _parse_intent(self, raw_intent: Dict[str, Any]) -> Intent:
        """
        Parse raw dictionary into Intent Pydantic model.
        
        Raises:
            MalformedIntentError: If parsing fails
        """
        try:
            processed_intent = self._preprocess_intent(raw_intent)
            return Intent(**processed_intent)
        except ValidationError as e:
            errors = e.errors()
            if errors:
                first_error = errors[0]
                field = ".".join(str(loc) for loc in first_error.get("loc", []))
                msg = first_error.get("msg", "Invalid intent structure")
                raise MalformedIntentError(
                    f"{field}: {msg}",
                    raw_intent=raw_intent
                )
            raise MalformedIntentError(str(e), raw_intent=raw_intent)
        except Exception as e:
            raise MalformedIntentError(
                f"Unexpected error: {str(e)}",
                raw_intent=raw_intent
            )
    
    def _validate_metric(self, metric: str) -> None:
        if not self.catalog.is_valid_metric(metric):
            raise UnknownMetricError(metric)
    
    def _validate_dimensions(self, dimensions: list[str], context: str):
        for dim in dimensions:
            if not self.catalog.is_valid_dimension(dim):
                raise UnknownDimensionError(dim, context)

    def _validate_time_spec(self, time_spec: TimeSpec) -> None:
        """
        Validate a unified TimeSpec (dimension, window/dates, granularity).
        
        Raises:
            UnknownTimeDimensionError: If time dimension not in catalog
            InvalidTimeWindowError: If window not recognized
            InvalidGranularityError: If granularity invalid
        """
        # Validate the time dimension field
        if not self.catalog.is_valid_time_dimension(time_spec.dimension):
            raise UnknownTimeDimensionError(time_spec.dimension)

        # Validate window if specified
        if time_spec.window:
            if not self.catalog.is_valid_time_window(time_spec.window):
                raise InvalidTimeWindowError(time_spec.window)

        # Validate granularity if specified
        if time_spec.granularity:
            allowed = self.catalog.get_time_granularities(time_spec.dimension)
            if time_spec.granularity not in allowed:
                raise InvalidGranularityError(time_spec.granularity)
    
    def _validate_filters(self, filters: List[Filter]) -> None:
        """
        Validate all filter dimensions exist in catalog.

        Raises:
            InvalidFilterError: If filter dimension not in catalog
        """
        for idx, flt in enumerate(filters):
            if not self.catalog.is_valid_dimension(flt.dimension):
                raise InvalidFilterError(
                    f"Unknown filter dimension: '{flt.dimension}'",
                    filter_index=idx,
                    dimension=flt.dimension
                )
    
    # ---------- Suggestion Helpers ----------
    
    def _get_metric_suggestions(self, metric: str) -> List[str]:
        """Get similar metric names for suggestions."""
        all_metrics = self.catalog.list_metric_names()
        return self._find_similar(metric, all_metrics, max_results=3)
    
    def _get_dimension_suggestions(self, dimension: str) -> List[str]:
        """Get similar dimension names for suggestions."""
        all_dimensions = self.catalog.list_dimension_names()
        return self._find_similar(dimension, all_dimensions, max_results=3)
    
    def _find_similar(self, query: str, candidates: List[str], max_results: int = 3) -> List[str]:
        """Find similar strings using simple substring matching."""
        query_lower = query.lower()
        prefix_matches = [c for c in candidates if c.lower().startswith(query_lower)]
        substring_matches = [
            c for c in candidates 
            if query_lower in c.lower() and c not in prefix_matches
        ]
        suggestions = prefix_matches + substring_matches
        return suggestions[:max_results]


# =============================================================================
# MODULE-LEVEL HELPERS
# =============================================================================

def derive_intent_type_safe(intent: Intent) -> IntentType:
    """
    Safely derive intent type from a validated Intent.

    Wraps derive_intent_type() and falls back to SNAPSHOT on any error.
    """
    from app.models.intent import derive_intent_type
    try:
        return derive_intent_type(intent)
    except Exception:
        return IntentType.SNAPSHOT


def validate_intent(raw_intent: Dict[str, Any], catalog: CatalogManager) -> Intent:
    """
    Convenience function to validate an intent.
    
    Args:
        raw_intent: Raw intent dictionary
        catalog: CatalogManager instance
        
    Returns:
        Validated Intent object
        
    Raises:
        IntentValidationError subclass on validation failure
    
    Example:
        >>> from backend.app.services.catalog_manager import CatalogManager
        >>> catalog = CatalogManager("path/to/catalog.yaml")
        >>> raw = {
        ...     "intent_type": "snapshot",
        ...     "metric": "total_quantity",
        ...     "time_range": {"window": "last_7_days"}
        ... }
        >>> intent = validate_intent(raw, catalog)
        >>> print(intent.metric)
        'total_quantity'
    """
    validator = IntentValidator(catalog)
    return validator.validate(raw_intent)
