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

import logging
from typing import Any, Dict, List, Optional

from app.models.intent import (
    Intent,
    IntentType,
    Filter,
    TimeSpec,
    Metric,
)
from app.services.helpers.catalog_manager import CatalogManager
from app.services.intent.intent_errors import (
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

logger = logging.getLogger(__name__)


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
    
    def validate(self, raw_intent: Dict[str, Any], original_query: Optional[str] = None) -> Intent:
        """
        Validate a raw intent dictionary and return a validated Intent object.

        Performs:
        1. Structural validation (Pydantic parsing)
        2. Metric validation (exists in catalog)
        3. Dimension validation (group_by fields exist)
        4. Time & clarification rule enforcement (8 rules)
        5. Filter validation

        Args:
            raw_intent:     Raw intent dict from the LLM / normalizer.
            original_query: The user's original NL query string. Used by Fix 3
                            to detect trend intent that the LLM missed.
        """
        intent = self._parse_intent(raw_intent)
        missing_fields: list[str] = []
        clarification_questions: list[str] = []
        
        # --- Rule 8: Time must NEVER be in dimensions ---
        # Silently remove invoice_date from group_by if present
        if intent.group_by:
            cleaned = [d for d in intent.group_by if "invoice_date" not in d]
            if len(cleaned) != len(intent.group_by):
                logger.warning("Removed invoice_date from group_by (Rule 8: time must only use timeDimensions)")
                object.__setattr__(intent, 'group_by', cleaned if cleaned else None)
        
        # --- Validate metrics ---
        if not intent.metrics:
            missing_fields.append("metrics")
            clarification_questions.append("What would you like to measure?")
        else:
            for m in intent.metrics:
                self._validate_metric(m.name)
        
        # --- Validate group_by dimensions ---
        if intent.group_by:
            self._validate_dimensions(intent.group_by, context="group_by")
        
        # --- Validate time spec if present ---
        if intent.time is not None:
            self._validate_time_spec(intent.time)

        # --- Derive intent type for rule checks ---
        intent_type = derive_intent_type_safe(intent)

        # time is optional — ScopeTimeAgent (DSPy Stage 2) already decided
        # whether a time constraint is needed for the query. If it chose not to
        # emit one, the query runs over all available data, which is valid.
        # Rule 1 ("time mandatory") is intentionally removed.


        # --- Rule 4: Trend without granularity → clarify ---
        # Exception: if a derived_metric is present that the period planner
        # will auto-inject granularity for (SINGLE_TIME_SERIES path), skip clarification.
        if intent_type == IntentType.TREND:
            if intent.time is None:
                pass  # Already flagged by Rule 1
            elif intent.time.granularity is None:
                # BUG-03 FIX: don't ask for granularity if period_planner will inject it
                _planner_injected_metrics = {"wow_growth", "mom_growth", "yoy_growth", "period_change"}
                _derived = (
                    intent.post_processing.derived_metric
                    if intent.post_processing else None
                )
                if _derived not in _planner_injected_metrics:
                    missing_fields.append("time.granularity")
                    clarification_questions.append(
                        "What time granularity would you like? "
                        "(e.g., day, week, month, quarter, year)"
                    )

        # --- Fix 3: Keyword-driven trend guard (chicken-and-egg breaker) ---
        # Rule 4 above cannot fire if derive_intent_type() returned SNAPSHOT
        # because granularity is missing — that's the chicken-and-egg problem.
        # This block catches trend-language queries where the LLM AND the
        # patch_trend_intent() patcher both failed to set granularity.
        if (
            original_query
            and intent_type != IntentType.TREND          # Rule 4 didn’t fire above
            and "time.granularity" not in missing_fields  # not already flagged
        ):
            from app.services.intent.intent_normalizer import TREND_KEYWORDS
            _query_lower = original_query.lower()
            _has_trend_kw = any(kw in _query_lower for kw in TREND_KEYWORDS)
            _granularity_missing = (
                intent.time is None or intent.time.granularity is None
            )
            if _has_trend_kw and _granularity_missing:
                logger.warning(
                    "[Fix3] Trend keyword detected in query but granularity still missing after "
                    "patcher. Asking for clarification. "
                    f"intent_type={intent_type}, query='{original_query[:80]}'"
                )
                missing_fields.append("time.granularity")
                clarification_questions.append(
                    "What time granularity would you like the trend shown at? "
                    "(e.g., day, week, month, quarter, year)"
                )

        # --- Rule 5: Ranking without group_by → clarify ---
        has_ranking = bool(
            intent.post_processing and
            intent.post_processing.ranking and
            intent.post_processing.ranking.enabled
        )
        if has_ranking and not intent.group_by:
            missing_fields.append("group_by")
            clarification_questions.append(
                "Ranking requires a breakdown dimension. "
                "What would you like to rank by? (e.g., zone, brand, distributor)"
            )

        # --- Rule for distribution without group_by ---
        if intent_type == IntentType.DISTRIBUTION and not intent.group_by:
            if "group_by" not in missing_fields:
                missing_fields.append("group_by")
                clarification_questions.append("What would you like to group by?")

        # --- Rule 6: Growth without comparison window → clarify (DUAL_QUERY path only) ---
        # SINGLE_TIME_SERIES (rolling windows) expands the window implicitly and never
        # calls build_comparison_query, so comparison_window is not needed there.
        has_growth = bool(
            intent.post_processing and
            intent.post_processing.derived_metric in (
                "mom_growth", "yoy_growth", "wow_growth", "period_change"
            )
        )
        if has_growth:
            # Only fire on DUAL_QUERY path: explicit dates or non-contiguous (to-date) windows
            _NON_CONTIGUOUS = {"month_to_date", "quarter_to_date", "year_to_date", "today", "yesterday"}
            _is_explicit_dates = bool(
                intent.time and intent.time.start_date
            )
            _is_non_contiguous_window = bool(
                intent.time and intent.time.window and intent.time.window in _NON_CONTIGUOUS
            )
            _needs_dual_query = _is_explicit_dates or _is_non_contiguous_window
            if _needs_dual_query:
                has_comparison_window = bool(
                    intent.post_processing and
                    intent.post_processing.comparison and
                    intent.post_processing.comparison.comparison_window
                )
                if not has_comparison_window and not _is_explicit_dates:
                    missing_fields.append("post_processing.comparison.comparison_window")
                    clarification_questions.append(
                        "Growth requires a comparison period. "
                        "What period should we compare against? (e.g., last_month, last_quarter)"
                    )

        # --- Rule 7: Period comparison without window → clarify ---
        has_period_comparison = bool(
            intent.post_processing and
            intent.post_processing.comparison and
            intent.post_processing.comparison.type == "period"
        )
        if has_period_comparison:
            _is_explicit_dates = bool(intent.time and intent.time.start_date)
            if not intent.post_processing.comparison.comparison_window and not _is_explicit_dates:
                if "post_processing.comparison.comparison_window" not in missing_fields:
                    missing_fields.append("post_processing.comparison.comparison_window")
                    clarification_questions.append(
                        "Compared to which period?"
                    )
        
        # --- Validate filters ---
        if intent.filters:
            self._validate_filters(intent.filters)
        
        
        if missing_fields:
            allowed_values: Optional[list[str]] = None
            first_missing = missing_fields[0]
            
            if first_missing == "metrics":
                allowed_values = list(self.catalog.raw_catalog().get("metrics", {}).keys())
            elif first_missing == "group_by":
                allowed_values = list(self.catalog.raw_catalog().get("dimensions", {}).keys())
            elif first_missing == "time.granularity":
                allowed_values = ["day", "week", "month", "quarter", "year"]
            elif first_missing == "post_processing.comparison.comparison_window":
                allowed_values = ["previous_period", "last_month", "last_quarter", "last_year"]
                
            raise IntentIncompleteError(
                missing_fields=missing_fields,
                clarification_message=" ".join(clarification_questions),
                allowed_values=allowed_values
            )
        return intent

    
    # Common user phrases → canonical TIME_WINDOW slug
    _TIME_WINDOW_ALIASES: Dict[str, str] = {
        "last 7 days":      "last_7_days",
        "last 30 days":     "last_30_days",
        "last 90 days":     "last_90_days",
        "this month":       "month_to_date",
        "month to date":    "month_to_date",
        "this quarter":     "quarter_to_date",
        "quarter to date":  "quarter_to_date",
        "this year":        "year_to_date",
        "year to date":     "year_to_date",
        "last month":       "last_month",
        "last quarter":     "last_quarter",
        "last year":        "last_year",
        "today":            "today",
        "yesterday":        "yesterday",
        "all time":         "all_time",
    }

    def _preprocess_intent(self, raw_intent: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pre-process raw intent to normalise common LLM output variations and
        coerce clarification answers into the correct structure.

        Handles:
        - metrics as a plain string array ["net_value"] → [{"name": "net_value"}]
        - time as a plain string "last 30 days" → proper TimeSpec dict
        - string "null" → None for comparison.type and derived_metric
        """
        intent = raw_intent.copy()
        # --- Unflatten dot-notation keys from clarification answers ---
        # e.g., "time.window": "last_30_days" -> {"time": {"window": "last_30_days"}}
        keys_to_unflatten = [k for k in intent.keys() if "." in k]
        for k in keys_to_unflatten:
            val = intent.pop(k)
            parts = k.split(".")
            current = intent
            for part in parts[:-1]:
                if current.get(part) is None:
                    current[part] = {}
                elif not isinstance(current[part], dict):
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = val


        # --- Metrics: plain strings → {"name": str} dicts ---
        metrics = intent.get("metrics")
        if isinstance(metrics, list):
            normalised = []
            for m in metrics:
                if isinstance(m, str):
                    normalised.append({"name": m})
                else:
                    normalised.append(m)
            intent["metrics"] = normalised

        # --- Time: plain string OR dict → normalised TimeSpec dict ---
        scope = intent.get("sales_scope", "SECONDARY")
        cube = "fact_secondary_sales" if scope == "SECONDARY" else "fact_primary_sales"

        time_val = intent.get("time")
        if isinstance(time_val, str):
            # User answered the time clarification with a plain string like "last 30 days"
            key = time_val.strip().lower()
            window = self._TIME_WINDOW_ALIASES.get(key, key.replace(" ", "_"))
            intent["time"] = {
                "dimension": f"{cube}.invoice_date",
                "window": window,
                "start_date": None,
                "end_date": None,
                "granularity": None,
            }
            logger.info(f"Coerced string time '{time_val}' → window='{window}' ({cube}.invoice_date)")
        elif isinstance(time_val, dict):
            # time arrived as a dict (e.g., unflattened from 'time.window': 'last 30 days')
            # Normalise window alias if present
            raw_window = time_val.get("window")
            if isinstance(raw_window, str):
                key = raw_window.strip().lower()
                time_val["window"] = self._TIME_WINDOW_ALIASES.get(key, key.replace(" ", "_"))
            # Ensure dimension is fully qualified
            dim = time_val.get("dimension")
            if not dim or dim == "invoice_date":
                time_val["dimension"] = f"{cube}.invoice_date"
            logger.info(f"Normalised time dict: window='{time_val.get('window')}', dim='{time_val.get('dimension')}'")

        # --- "null" strings → None (prompt uses "null" as placeholder) ---
        pp = intent.get("post_processing")
        if isinstance(pp, dict):
            # derived_metric
            if pp.get("derived_metric") == "null":
                pp["derived_metric"] = None
            # comparison.type / comparison_window
            comp = pp.get("comparison")
            if isinstance(comp, dict):
                if comp.get("type") == "null":
                    comp["type"] = "none"
                if comp.get("comparison_window") == "null":
                    comp["comparison_window"] = None

        return intent
    
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


def validate_intent(raw_intent: Dict[str, Any], catalog: CatalogManager, original_query: Optional[str] = None) -> Intent:
    """
    Convenience function to validate an intent.
    
    Args:
        raw_intent:     Raw intent dictionary
        catalog:        CatalogManager instance
        original_query: Optional original NL query string for keyword-based
                        trend detection (Fix 3).
        
    Returns:
        Validated Intent object
        
    Raises:
        IntentValidationError subclass on validation failure

    """
    validator = IntentValidator(catalog)
    return validator.validate(raw_intent, original_query=original_query)
