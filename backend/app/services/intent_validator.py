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

from backend.app.models.intent import (
    Intent,
    IntentType,
    Filter,
    TimeDimension,
    TimeRange,
)
from backend.app.services.catalog_manager import CatalogManager, AmbiguousResolutionError
from backend.app.services.intent_errors import (
    IntentValidationError,
    MalformedIntentError,
    UnknownMetricError,
    UnknownDimensionError,
    UnknownTimeDimensionError,
    InvalidTimeWindowError,
    InvalidGranularityError,
    InvalidFilterError,
    AmbiguousMetricError,
    AmbiguousDimensionError,
    InvalidTimeRangeError,
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
        """
        Initialize validator with a catalog manager.
        
        Args:
            catalog: CatalogManager instance for validating metrics/dimensions
        """
        self.catalog = catalog
    
    def validate(self, raw_intent: Dict[str, Any]) -> Intent:
        """
        Validate a raw intent dictionary and return a validated Intent object.
        
        This is the main entry point. It performs:
        1. Structural validation (Pydantic parsing)
        2. Metric validation (exists in catalog, unambiguous)
        3. Dimension validation (group_by fields exist)
        4. Time dimension validation (exists, valid granularity)
        5. Time range validation (valid window if specified)
        6. Filter validation (dimensions exist, values valid)
        
        Args:
            raw_intent: Dictionary from LLM or API
            
        Returns:
            Validated Intent object
            
        Raises:
            MalformedIntentError: If dict cannot be parsed to Intent
            UnknownMetricError: If metric not in catalog
            UnknownDimensionError: If dimension not in catalog
            UnknownTimeDimensionError: If time dimension not in catalog
            InvalidTimeWindowError: If time window not recognized
            InvalidGranularityError: If granularity invalid
            InvalidFilterError: If filter dimension unknown
            AmbiguousMetricError: If metric matches multiple catalog items
            AmbiguousDimensionError: If dimension matches multiple catalog items
        """
        # Step 1: Parse raw dict into Intent model
        intent = self._parse_intent(raw_intent)
        
        # Step 2: Validate metric exists and is unambiguous
        self._validate_metric(intent.metric)
        
        # Step 3: Validate group_by dimensions
        if intent.group_by:
            self._validate_dimensions(intent.group_by, context="group_by")
        
        # Step 4: Validate time dimension
        if intent.time_dimension:
            self._validate_time_dimension(intent.time_dimension)
        
        # Step 5: Validate time range
        if intent.time_range:
            self._validate_time_range(intent.time_range)
        
        # Step 6: Validate filters
        if intent.filters:
            self._validate_filters(intent.filters)
        
        return intent
    
    def _parse_intent(self, raw_intent: Dict[str, Any]) -> Intent:
        """
        Parse raw dictionary into Intent Pydantic model.
        
        Raises:
            MalformedIntentError: If parsing fails
        """
        try:
            return Intent(**raw_intent)
        except ValidationError as e:
            # Extract meaningful error message from Pydantic
            errors = e.errors()
            if errors:
                first_error = errors[0]
                field = ".".join(str(loc) for loc in first_error.get("loc", []))
                msg = first_error.get("msg", "Invalid intent structure")
                raise MalformedIntentError(
                    f"{field}: {msg}",
                    raw_intent=raw_intent
                )
            raise MalformedIntentError(
                str(e),
                raw_intent=raw_intent
            )
        except Exception as e:
            raise MalformedIntentError(
                f"Unexpected error: {str(e)}",
                raw_intent=raw_intent
            )
    
    def _validate_metric(self, metric: str) -> None:
        """
        Validate that metric exists in catalog and is unambiguous.
        
        Raises:
            UnknownMetricError: If metric not found
            AmbiguousMetricError: If metric matches multiple items
        """
        try:
            # Use resolve which will raise AmbiguousResolutionError if ambiguous
            self.catalog.resolve_metric(metric)
        except AmbiguousResolutionError as e:
            match_names = [m.get('name', m.get('id', '')) for m in e.matches]
            raise AmbiguousMetricError(metric, match_names)
        except Exception:
            # Metric not found - try to get suggestions
            suggestions = self._get_metric_suggestions(metric)
            raise UnknownMetricError(metric, suggestions)
    
    def _validate_dimensions(self, dimensions: List[str], context: str = "group_by") -> None:
        """
        Validate that all dimensions exist in catalog.
        
        Args:
            dimensions: List of dimension names to validate
            context: Context for error messages (group_by, filter, etc.)
            
        Raises:
            UnknownDimensionError: If any dimension not found
            AmbiguousDimensionError: If any dimension is ambiguous
        """
        for dim in dimensions:
            try:
                self.catalog.resolve_dimension(dim)
            except AmbiguousResolutionError as e:
                match_names = [d.get('name', d.get('id', '')) for d in e.matches]
                raise AmbiguousDimensionError(dim, match_names, context)
            except Exception:
                suggestions = self._get_dimension_suggestions(dim)
                raise UnknownDimensionError(dim, context, suggestions)
    
    def _validate_time_dimension(self, time_dim: TimeDimension) -> None:
        """
        Validate time dimension exists and granularity is valid.
        
        Raises:
            UnknownTimeDimensionError: If time dimension not in catalog
            InvalidGranularityError: If granularity not valid
        """
        # Validate dimension exists
        try:
            self.catalog.resolve_time_dimension(time_dim.dimension)
        except AmbiguousResolutionError as e:
            # Time dimensions shouldn't be ambiguous, but handle it
            match_names = [td.get('name', td.get('id', '')) for td in e.matches]
            raise UnknownTimeDimensionError(
                f"{time_dim.dimension} (ambiguous: {', '.join(match_names)})"
            )
        except Exception:
            suggestions = self._get_time_dimension_suggestions(time_dim.dimension)
            raise UnknownTimeDimensionError(time_dim.dimension, suggestions)
        
        # Validate granularity
        if time_dim.granularity not in self.VALID_GRANULARITIES:
            raise InvalidGranularityError(time_dim.granularity)
    
    def _validate_time_range(self, time_range: TimeRange) -> None:
        """
        Validate time range window if specified.
        
        Raises:
            InvalidTimeWindowError: If window not recognized
            InvalidTimeRangeError: If time range structure is invalid
        """
        # The TimeRange model already validates that we don't have both window and dates
        # But we need to validate the window value if present
        if time_range.window:
            if not self.catalog.is_valid_time_window(time_range.window):
                valid_windows = [tw.get('name', '') for tw in self.catalog.list_time_windows()]
                raise InvalidTimeWindowError(time_range.window, valid_windows)
        
        # If using explicit dates, basic validation (format is handled by Pydantic)
        # Additional date validation could be added here if needed
    
    def _validate_filters(self, filters: List[Filter]) -> None:
        """
        Validate all filter dimensions exist in catalog.
        
        Raises:
            InvalidFilterError: If filter dimension not in catalog
        """
        for idx, flt in enumerate(filters):
            try:
                self.catalog.resolve_dimension(flt.dimension)
            except AmbiguousResolutionError as e:
                match_names = [d.get('name', d.get('id', '')) for d in e.matches]
                raise InvalidFilterError(
                    f"Ambiguous filter dimension: '{flt.dimension}' matches {', '.join(match_names)}",
                    filter_index=idx,
                    dimension=flt.dimension
                )
            except Exception:
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
    
    def _get_time_dimension_suggestions(self, time_dim: str) -> List[str]:
        """Get similar time dimension names for suggestions."""
        all_time_dims = [td.get('name', '') for td in self.catalog.list_time_dimensions()]
        return self._find_similar(time_dim, all_time_dims, max_results=3)
    
    def _find_similar(self, query: str, candidates: List[str], max_results: int = 3) -> List[str]:
        """
        Find similar strings using simple substring matching.
        
        For production, consider using fuzzy matching (e.g., rapidfuzz).
        """
        query_lower = query.lower()
        
        # Exact prefix matches first
        prefix_matches = [c for c in candidates if c.lower().startswith(query_lower)]
        
        # Then substring matches
        substring_matches = [
            c for c in candidates 
            if query_lower in c.lower() and c not in prefix_matches
        ]
        
        # Combine and limit
        suggestions = prefix_matches + substring_matches
        return suggestions[:max_results]


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
