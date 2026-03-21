"""
DSPy Module implementations for Intent Extraction Pipeline.

Following RULE M1: Use dspy.Predict for structured extraction, ChainOfThought only for Classifier
Following RULE M2: All modules as dspy.Module classes
Following RULE M4: Serialize inter-agent Pydantic models to JSON strings
Following RULE M5: current_date injected at pipeline level
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

import dspy
from pydantic import ValidationError

from .signatures import (
    ClassifyQuery,
    ResolveScope,
    ResolveTime,
    ResolveScopeTime,
    ExtractMetrics,
    ResolveDimensions,
    AssembleIntent
)
from .clarification_tool import (
    clarification_tool,
    ClarificationOption,
    ClarificationType,
    ClarificationContext,
    ClarificationRequiredException,
)
from .schemas import (
    ClassifiedQuery,
    ScopeResult,
    TimeResult,
    ScopeTimeResult,
    MetricsResult,
    DimensionsResult,
    FilterCondition,
    PostProcessingSpec,
    CATALOG_METRICS,
    ALL_DIMENSIONS,
    COMMON_DIMENSIONS,
    SECONDARY_ONLY_DIMENSIONS,
    TIME_WINDOWS,
    resolve_metric_alias,
    resolve_dimension_alias,
    get_valid_dimensions_for_scope,
    find_ambiguous_dimension_candidates,
    find_ambiguous_metric_candidates,
)
from ..models.intent import Intent, Metric, Filter, TimeSpec, RankingSpec, ComparisonSpec, PostProcessing

logger = logging.getLogger(__name__)

# =============================================================================
# AGENT IMPLEMENTATIONS
# =============================================================================

class ClassifierAgent(dspy.Module):
    """
    Agent 1: Term classification and semantic labeling.

    Uses ChainOfThought per RULE M1 since classification may benefit from rationale.
    """

    def __init__(self):
        super().__init__()
        self.classifier = dspy.ChainOfThought(ClassifyQuery)

    def forward(self, query: str) -> ClassifiedQuery:
        """Classify query terms into semantic categories."""
        logger.info("🏷️  [ClassifierAgent] Starting term classification")
        logger.debug(f"🏷️  [ClassifierAgent] Input query: '{query[:100]}{'...' if len(query) > 100 else ''}'")

        try:
            # Call DSPy predictor
            logger.debug("🏷️  [ClassifierAgent] Calling DSPy ChainOfThought classifier")
            result = self.classifier(query=query)

            logger.debug(f"🏷️  [ClassifierAgent] Raw DSPy output - metrics: {result.metric_terms}")
            logger.debug(f"🏷️  [ClassifierAgent] Raw DSPy output - dimensions: {result.dimension_terms}")
            logger.debug(f"🏷️  [ClassifierAgent] Raw DSPy output - time: {result.time_expressions}")

            # Parse comma-separated lists
            classified = ClassifiedQuery(
                query_text=query,
                metric_terms=self._parse_terms(result.metric_terms),
                dimension_terms=self._parse_terms(result.dimension_terms),
                filter_terms=self._parse_terms(result.filter_terms),
                time_expressions=self._parse_terms(result.time_expressions),
                ranking_indicators=self._parse_terms(result.ranking_indicators),
                scope_indicators=self._parse_terms(result.scope_indicators),
                comparison_indicators=self._parse_terms(result.comparison_indicators)
            )

            logger.info(f"🏷️  [ClassifierAgent] ✅ Classification successful")
            logger.info(f"🏷️  [ClassifierAgent] Found {len(classified.metric_terms)} metric terms: {classified.metric_terms}")
            logger.info(f"🏷️  [ClassifierAgent] Found {len(classified.dimension_terms)} dimension terms: {classified.dimension_terms}")
            logger.info(f"🏷️  [ClassifierAgent] Found {len(classified.time_expressions)} time expressions: {classified.time_expressions}")
            if classified.ranking_indicators:
                logger.info(f"🏷️  [ClassifierAgent] Found ranking indicators: {classified.ranking_indicators}")
            if classified.scope_indicators:
                logger.info(f"🏷️  [ClassifierAgent] Found scope indicators: {classified.scope_indicators}")

            logger.debug(f"🏷️  [ClassifierAgent] Complete classification result: {classified.model_dump()}")
            return classified

        except Exception as e:
            logger.error(f"🏷️  [ClassifierAgent] ❌ Classification failed: {e}")
            logger.warning(f"🏷️  [ClassifierAgent] 🔄 Falling back to empty classification")
            # Fallback: empty classification
            return ClassifiedQuery(query_text=query)

    def _parse_terms(self, terms_str: str) -> List[str]:
        """Parse comma-separated terms string into list."""
        if not terms_str or terms_str.strip().lower() in ['none', 'null', '']:
            return []
        return [term.strip() for term in terms_str.split(',') if term.strip()]


class ScopeAgent(dspy.Module):
    """
    Agent 2: Sales scope determination.

    Uses dspy.Predict per RULE M1 for structured extraction.
    Focused solely on determining PRIMARY vs SECONDARY scope.
    """

    def __init__(self):
        super().__init__()
        self.resolver = dspy.Predict(ResolveScope)

    def forward(self, classified_query: ClassifiedQuery) -> ScopeResult:
        """Resolve sales scope from query indicators."""
        logger.info("🏢 [ScopeAgent] Starting scope resolution")
        logger.debug(f"🏢 [ScopeAgent] Scope indicators: {classified_query.scope_indicators}")

        try:
            # Call DSPy predictor with serialized input per RULE M4
            classified_json = classified_query.model_dump_json()
            logger.debug("🏢 [ScopeAgent] Calling DSPy scope resolver")
            result = self.resolver(classified_query=classified_json)

            logger.debug(f"🏢 [ScopeAgent] Raw DSPy output - scope: {result.sales_scope}")

            # Parse and validate scope
            scope_result = ScopeResult(
                sales_scope=self._parse_sales_scope(result.sales_scope)
            )

            logger.info(f"🏢 [ScopeAgent] ✅ Scope resolution successful")
            logger.info(f"🏢 [ScopeAgent] Sales scope: {scope_result.sales_scope}")

            logger.debug(f"🏢 [ScopeAgent] Complete scope result: {scope_result.model_dump()}")
            return scope_result

        except Exception as e:
            logger.error(f"🏢 [ScopeAgent] ❌ Scope resolution failed: {e}")
            logger.warning(f"🏢 [ScopeAgent] 🔄 Falling back to default scope")
            # Fallback: default scope
            return ScopeResult(sales_scope="SECONDARY")

    def _parse_sales_scope(self, scope_str: str) -> str:
        """Parse and validate sales scope."""
        if not scope_str:
            return "SECONDARY"
        scope_upper = scope_str.strip().upper()
        return scope_upper if scope_upper in ["PRIMARY", "SECONDARY"] else "SECONDARY"


class TimeAgent(dspy.Module):
    """
    Agent 3: Time constraint resolution with decision logic.

    Uses dspy.Predict per RULE M1 for structured extraction.
    Implements the time decision framework:
    - Time is mandatory for performance queries (KPI, DISTRIBUTION, RANKING, TREND, COMPARISON)
    - Time is null for structural queries (catalog/membership queries)
    - Requests clarification when time is required but absent
    """

    def __init__(self):
        super().__init__()
        self.resolver = dspy.Predict(ResolveTime)

    def forward(self, classified_query: ClassifiedQuery, current_date: str, intent_category: str = "UNKNOWN", previous_context: str = "") -> TimeResult:
        """Resolve time specification with decision logic and clarification rules."""
        logger.info("⏰ [TimeAgent] Starting time resolution")
        logger.debug(f"⏰ [TimeAgent] Current date: {current_date}")
        logger.debug(f"⏰ [TimeAgent] Intent category: {intent_category}")
        logger.debug(f"⏰ [TimeAgent] Time expressions: {classified_query.time_expressions}")
        logger.debug(f"⏰ [TimeAgent] Has previous context: {'Yes' if previous_context else 'No'}")

        # Check for already resolved time clarification to avoid re-asking
        from .clarification_tool import clarification_tool
        already_resolved_time = clarification_tool.get_field_override("time")
        if already_resolved_time:
            logger.info(f"⏰ [TimeAgent] Time was already clarified → using resolved value '{already_resolved_time}'")
            return TimeResult(
                time_window=already_resolved_time,
                start_date=None,
                end_date=None,
                granularity=None,
                has_time_constraint=True,
                requires_clarification=False
            )

        try:
            # Call DSPy predictor with serialized input per RULE M4
            classified_json = classified_query.model_dump_json()
            logger.debug("⏰ [TimeAgent] Calling DSPy time resolver")
            result = self.resolver(
                classified_query=classified_json,
                current_date=current_date,
                intent_category=intent_category,
                previous_context=previous_context
            )

            logger.debug(f"⏰ [TimeAgent] Raw DSPy output - window: {result.time_window}")
            logger.debug(f"⏰ [TimeAgent] Raw DSPy output - dates: {result.start_date} to {result.end_date}")
            logger.debug(f"⏰ [TimeAgent] Raw DSPy output - granularity: {result.granularity}")
            logger.debug(f"⏰ [TimeAgent] Raw DSPy output - has_constraint: {result.has_time_constraint}")
            logger.debug(f"⏰ [TimeAgent] Raw DSPy output - requires_clarification: {result.requires_clarification}")
            logger.debug(f"⏰ [TimeAgent] Raw DSPy output - reasoning: {result.reasoning}")

            # Parse and validate results
            time_result = TimeResult(
                time_window=self._parse_time_window(result.time_window),
                start_date=self._parse_date(result.start_date),
                end_date=self._parse_date(result.end_date),
                granularity=self._parse_granularity(result.granularity),
                has_time_constraint=self._parse_boolean(result.has_time_constraint, default=False),
                requires_clarification=self._parse_boolean(result.requires_clarification, default=False)
            )

            # Apply decision logic and clarification rules
            time_result = self._apply_time_decision_rules(
                time_result, classified_query, intent_category, previous_context
            )

            # Enforce TimeSpec constraint: window XOR dates (binary constraint per RULE D5)
            if time_result.time_window and (time_result.start_date or time_result.end_date):
                logger.warning("⏰ [TimeAgent] ⚠️  Both window and explicit dates provided, clearing dates")
                time_result.start_date = None
                time_result.end_date = None

            # Handle clarification request if needed
            if time_result.requires_clarification:
                from .clarification_tool import clarification_tool, ClarificationContext, ClarificationOption, ClarificationType
                self._request_time_clarification(classified_query.query_text, intent_category)

            logger.info(f"⏰ [TimeAgent] ✅ Time resolution successful")
            if time_result.has_time_constraint:
                if time_result.time_window:
                    logger.info(f"⏰ [TimeAgent] Time window: {time_result.time_window}")
                else:
                    logger.info(f"⏰ [TimeAgent] Date range: {time_result.start_date} to {time_result.end_date}")
                if time_result.granularity:
                    logger.info(f"⏰ [TimeAgent] Granularity: {time_result.granularity}")
            else:
                logger.info("⏰ [TimeAgent] No time constraint specified")

            if time_result.requires_clarification:
                logger.info("⏰ [TimeAgent] Time clarification requested")

            logger.debug(f"⏰ [TimeAgent] Complete time result: {time_result.model_dump()}")
            return time_result

        except ClarificationRequiredException:
            # Re-raise clarification exceptions
            raise
        except Exception as e:
            logger.error(f"⏰ [TimeAgent] ❌ Time resolution failed: {e}")
            logger.warning(f"⏰ [TimeAgent] 🔄 Falling back to no time constraint")
            # Fallback: no time constraint
            return TimeResult(has_time_constraint=False)

    def _apply_time_decision_rules(self, time_result: TimeResult, classified_query: ClassifiedQuery,
                                 intent_category: str, previous_context: str) -> TimeResult:
        """Apply the time decision framework rules."""
        logger.debug("⏰ [TimeAgent] Applying time decision rules")

        # Check if query is structural/catalog-based
        is_structural_query = self._is_structural_query(classified_query, intent_category)

        if is_structural_query:
            # Structural queries don't need time
            logger.debug("⏰ [TimeAgent] Structural query detected - time not required")
            time_result.has_time_constraint = False
            time_result.requires_clarification = False
            return time_result

        # Performance queries require time
        has_time_from_query = (
            time_result.time_window or
            time_result.start_date or
            classified_query.time_expressions
        )

        has_time_from_context = bool(previous_context and "time" in previous_context.lower())

        if not has_time_from_query and not has_time_from_context:
            # Check for "all time" indicators
            if self._has_all_time_indicators(classified_query):
                logger.debug("⏰ [TimeAgent] All-time indicators detected - using all_time window")
                time_result.time_window = "all_time"
                time_result.has_time_constraint = True
                time_result.requires_clarification = False
            else:
                logger.debug("⏰ [TimeAgent] Performance query without time - clarification required")
                time_result.requires_clarification = True
                time_result.has_time_constraint = False

        return time_result

    def _is_structural_query(self, classified_query: ClassifiedQuery, intent_category: str) -> bool:
        """Check if query is asking about structure/membership rather than performance."""
        # Check for structural intent keywords
        structural_keywords = [
            "what", "which", "list", "show", "available", "exist", "have",
            "brands", "zones", "categories", "products", "retailers", "distributors"
        ]

        query_lower = classified_query.query_text.lower()

        # If query asks "what/which X" without metrics, it's likely structural
        for keyword in structural_keywords:
            if keyword in query_lower:
                # Check if it's asking about entities without measuring them
                if not classified_query.metric_terms and not any(
                    metric_word in query_lower for metric_word in ["sales", "revenue", "value", "quantity", "count"]
                ):
                    return True

        return False

    def _has_all_time_indicators(self, classified_query: ClassifiedQuery) -> bool:
        """Check for indicators that suggest all-time data is wanted."""
        all_time_indicators = [
            "all time", "overall", "total", "ever", "highest ever", "best", "worst",
            "all-time", "lifetime", "historical", "complete", "entire"
        ]

        query_lower = classified_query.query_text.lower()
        return any(indicator in query_lower for indicator in all_time_indicators)

    def _request_time_clarification(self, query_text: str, intent_category: str):
        """Request time clarification using the clarification tool."""
        from .clarification_tool import clarification_tool, ClarificationContext, ClarificationOption, ClarificationType, ClarificationRequiredException

        # Create context-specific clarification message based on intent
        clarification_prompts = {
            "KPI": "What time period should this cover? (e.g., this month, last 30 days)",
            "RANKING": "Should this ranking be based on all-time data, or a specific period?",
            "TREND": "What time range should the trend cover?",
            "COMPARISON": "What period should this be compared against?",
            "DISTRIBUTION": "What time period should this analysis cover?",
            "DEFAULT": "What time period would you like to analyze?"
        }

        question = clarification_prompts.get(intent_category, clarification_prompts["DEFAULT"])

        # Common time options
        options = [
            ClarificationOption(
                id="last_30_days",
                label="Last 30 Days",
                description="Data from the past 30 days",
                value="last_30_days"
            ),
            ClarificationOption(
                id="month_to_date",
                label="Month to Date",
                description="From the beginning of this month until now",
                value="month_to_date"
            ),
            ClarificationOption(
                id="last_month",
                label="Last Month",
                description="Complete previous month",
                value="last_month"
            ),
            ClarificationOption(
                id="quarter_to_date",
                label="Quarter to Date",
                description="From the beginning of this quarter until now",
                value="quarter_to_date"
            ),
            ClarificationOption(
                id="all_time",
                label="All Time",
                description="All available historical data",
                value="all_time"
            )
        ]

        agent_context = ClarificationContext(
            agent_name="TimeAgent",
            step_name="resolve_time",
            input_data=query_text,
            metadata={"intent_category": intent_category}
        )

        request_id = clarification_tool.request_clarification(
            clarification_type=ClarificationType.TIME,
            field_name="time",
            question=question,
            context=f"This {intent_category.lower()} query requires a time period to provide meaningful results.",
            options=options,
            allow_custom=True,
            metadata={"intent_category": intent_category}
        )

        # Get the request object
        request = clarification_tool.get_clarification_request(request_id)

        # Raise exception to signal clarification needed
        raise ClarificationRequiredException(
            request_id=request_id,
            clarification_request=request,
            agent_context=agent_context.__dict__
        )

    def _parse_time_window(self, window_str: str) -> Optional[str]:
        """Parse and validate time window."""
        if not window_str or window_str.strip().lower() in ['none', 'null', '']:
            return None
        window = window_str.strip()
        return window if window in TIME_WINDOWS else None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse and validate date string."""
        if not date_str or date_str.strip().lower() in ['none', 'null', '']:
            return None
        # Basic validation of YYYY-MM-DD format
        date = date_str.strip()
        try:
            datetime.strptime(date, "%Y-%m-%d")
            return date
        except ValueError:
            return None

    def _parse_granularity(self, granularity_str: str) -> Optional[str]:
        """Parse and validate granularity."""
        if not granularity_str or granularity_str.strip().lower() in ['none', 'null', '']:
            return None
        gran = granularity_str.strip()
        return gran if gran in ["day", "week", "month", "quarter", "year"] else None

    def _parse_boolean(self, bool_str: str, default: bool = False) -> bool:
        """Parse boolean string."""
        if not bool_str:
            return default
        return bool_str.strip().lower() in ['true', 'yes', '1']


class ScopeTimeAgent(dspy.Module):
    """
    Legacy Agent 2: Sales scope and time resolution (DEPRECATED).

    This is kept for backwards compatibility during the transition period.
    Use ScopeAgent and TimeAgent separately for new implementations.
    """

    def __init__(self):
        super().__init__()
        self.resolver = dspy.Predict(ResolveScopeTime)

    def forward(self, classified_query: ClassifiedQuery, current_date: str) -> ScopeTimeResult:
        """Resolve sales scope and time specification (DEPRECATED)."""
        logger.warning("⚠️  [ScopeTimeAgent] Using legacy combined agent - consider migrating to separate ScopeAgent and TimeAgent")
        logger.info("⏰ [ScopeTimeAgent] Starting scope and time resolution")
        logger.debug(f"⏰ [ScopeTimeAgent] Current date: {current_date}")
        logger.debug(f"⏰ [ScopeTimeAgent] Time expressions: {classified_query.time_expressions}")
        logger.debug(f"⏰ [ScopeTimeAgent] Scope indicators: {classified_query.scope_indicators}")

        try:
            # Call DSPy predictor with serialized input per RULE M4
            classified_json = classified_query.model_dump_json()
            logger.debug("⏰ [ScopeTimeAgent] Calling DSPy resolver")
            result = self.resolver(
                classified_query=classified_json,
                current_date=current_date
            )

            logger.debug(f"⏰ [ScopeTimeAgent] Raw DSPy output - scope: {result.sales_scope}")
            logger.debug(f"⏰ [ScopeTimeAgent] Raw DSPy output - window: {result.time_window}")
            logger.debug(f"⏰ [ScopeTimeAgent] Raw DSPy output - dates: {result.start_date} to {result.end_date}")
            logger.debug(f"⏰ [ScopeTimeAgent] Raw DSPy output - granularity: {result.granularity}")

            # Parse and validate results
            scope_time = ScopeTimeResult(
                sales_scope=self._parse_sales_scope(result.sales_scope),
                time_window=self._parse_time_window(result.time_window),
                start_date=self._parse_date(result.start_date),
                end_date=self._parse_date(result.end_date),
                granularity=self._parse_granularity(result.granularity),
                has_time_constraint=self._parse_boolean(result.has_time_constraint, default=False)
            )

            # Enforce TimeSpec constraint: window XOR dates (binary constraint in Python per RULE D5)
            if scope_time.time_window and (scope_time.start_date or scope_time.end_date):
                logger.warning("⏰ [ScopeTimeAgent] ⚠️  Both window and explicit dates provided, clearing dates")
                scope_time.start_date = None
                scope_time.end_date = None

            logger.info(f"⏰ [ScopeTimeAgent] ✅ Scope resolution successful")
            logger.info(f"⏰ [ScopeTimeAgent] Sales scope: {scope_time.sales_scope}")
            if scope_time.has_time_constraint:
                if scope_time.time_window:
                    logger.info(f"⏰ [ScopeTimeAgent] Time window: {scope_time.time_window}")
                else:
                    logger.info(f"⏰ [ScopeTimeAgent] Date range: {scope_time.start_date} to {scope_time.end_date}")
                if scope_time.granularity:
                    logger.info(f"⏰ [ScopeTimeAgent] Granularity: {scope_time.granularity}")
            else:
                logger.info("⏰ [ScopeTimeAgent] No time constraint specified")

            logger.debug(f"⏰ [ScopeTimeAgent] Complete scope/time result: {scope_time.model_dump()}")
            return scope_time

        except Exception as e:
            logger.error(f"⏰ [ScopeTimeAgent] ❌ Scope/time resolution failed: {e}")
            logger.warning(f"⏰ [ScopeTimeAgent] 🔄 Falling back to default scope, no time")
            # Fallback: default scope, no time
            return ScopeTimeResult(
                sales_scope="SECONDARY",
                has_time_constraint=False
            )

    def _parse_sales_scope(self, scope_str: str) -> str:
        """Parse and validate sales scope."""
        if not scope_str:
            return "SECONDARY"
        scope_upper = scope_str.strip().upper()
        return scope_upper if scope_upper in ["PRIMARY", "SECONDARY"] else "SECONDARY"

    def _parse_time_window(self, window_str: str) -> Optional[str]:
        """Parse and validate time window."""
        if not window_str or window_str.strip().lower() in ['none', 'null', '']:
            return None
        window = window_str.strip()
        return window if window in TIME_WINDOWS else None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse and validate date string."""
        if not date_str or date_str.strip().lower() in ['none', 'null', '']:
            return None
        # Basic validation of YYYY-MM-DD format
        date = date_str.strip()
        try:
            datetime.strptime(date, "%Y-%m-%d")
            return date
        except ValueError:
            return None

    def _parse_granularity(self, granularity_str: str) -> Optional[str]:
        """Parse and validate granularity."""
        if not granularity_str or granularity_str.strip().lower() in ['none', 'null', '']:
            return None
        gran = granularity_str.strip()
        return gran if gran in ["day", "week", "month", "quarter", "year"] else None

    def _parse_boolean(self, bool_str: str, default: bool = False) -> bool:
        """Parse boolean string."""
        if not bool_str:
            return default
        return bool_str.strip().lower() in ['true', 'yes', '1']


class MetricsAgent(dspy.Module):
    """
    Agent 3: Metric extraction and aggregation specification with integrated ambiguity reasoning.

    Uses dspy.Predict per RULE M1 for structured extraction.
    """

    def __init__(self):
        super().__init__()
        self.extractor = dspy.Predict(ExtractMetrics)

    def forward(self, classified_query: ClassifiedQuery, sales_scope: str) -> MetricsResult:
        """Extract and validate metrics with ambiguity detection."""
        logger.info("📊 [MetricsAgent] Starting metric extraction")
        logger.debug(f"📊 [MetricsAgent] Sales scope: {sales_scope}")
        logger.debug(f"📊 [MetricsAgent] Metric terms: {classified_query.metric_terms}")

        try:
            # Prepare available metrics for ambiguity detection
            available_metrics = [
                {
                    "name": name,
                    "label": name.replace("_", " ").title(),
                    "description": f"{name.replace('_', ' ').title()} metric"
                }
                for name in CATALOG_METRICS
            ]

            # Call DSPy predictor with available metrics
            classified_json = classified_query.model_dump_json()
            logger.debug("📊 [MetricsAgent] Calling DSPy extractor")
            result = self.extractor(
                classified_query=classified_json,
                sales_scope=sales_scope,
                available_metrics=str(available_metrics)
            )

            logger.debug(f"📊 [MetricsAgent] Raw DSPy output - metrics: {result.metrics}")
            logger.debug(f"📊 [MetricsAgent] Raw DSPy output - aggregations: {result.aggregations}")
            logger.debug(f"📊 [MetricsAgent] Raw DSPy output - ambiguous_terms: {result.ambiguous_terms}")
            logger.debug(f"📊 [MetricsAgent] Raw DSPy output - ambiguity_confidence: {result.ambiguity_confidence}")

            # Parse results
            raw_metrics = self._parse_terms(result.metrics)
            raw_aggregations = self._parse_terms(result.aggregations)
            ambiguous_terms = self._parse_terms(result.ambiguous_terms)
            ambiguity_confidence = self._parse_float(result.ambiguity_confidence)
            ambiguous_matches = self._parse_json(result.ambiguous_matches)

            # Check for ambiguity and request clarification if needed
            if ambiguous_terms and ambiguity_confidence > 0.7:
                # Check if this metric was already resolved in the current clarification re-run
                already_resolved_metric = clarification_tool.get_field_override("metrics")
                
                if already_resolved_metric:
                    logger.info(
                        f"📊 [MetricsAgent] Metric term was already clarified "
                        f"→ using resolved value '{already_resolved_metric}'"
                    )
                    # Override the raw metrics with the resolved value
                    raw_metrics = [already_resolved_metric]
                else:
                    logger.info("📊 [MetricsAgent] 🤔 Ambiguity detected, requesting clarification")
                    self._request_metric_clarification(
                        query=classified_query.query_text,
                        ambiguous_terms=ambiguous_terms,
                        ambiguous_matches=ambiguous_matches,
                        reasoning=result.reasoning
                    )

            # Continue with normal validation if no ambiguity
            validated_metrics = []
            validated_aggregations = []

            for i, metric in enumerate(raw_metrics):
                resolved_metric = resolve_metric_alias(metric)
                logger.debug(f"📊 [MetricsAgent] Resolving '{metric}' -> '{resolved_metric}'")

                if resolved_metric in CATALOG_METRICS:
                    validated_metrics.append(resolved_metric)
                    # Use provided aggregation or default
                    if i < len(raw_aggregations) and raw_aggregations[i] in ["sum", "count", "avg"]:
                        validated_aggregations.append(raw_aggregations[i])
                        logger.debug(f"📊 [MetricsAgent] Using provided aggregation: {raw_aggregations[i]}")
                    else:
                        # Default aggregation based on metric
                        default_agg = "count" if resolved_metric == "count" else "sum"
                        validated_aggregations.append(default_agg)
                        logger.debug(f"📊 [MetricsAgent] Using default aggregation: {default_agg}")
                else:
                    logger.warning(f"📊 [MetricsAgent] ⚠️  Invalid metric '{resolved_metric}' not in catalog")

            # Ensure at least one metric
            if not validated_metrics:
                logger.warning("📊 [MetricsAgent] ⚠️  No valid metrics found, defaulting to net_value")
                validated_metrics = ["net_value"]
                validated_aggregations = ["sum"]

            metrics_result = MetricsResult(
                metrics=validated_metrics,
                aggregations=validated_aggregations
            )

            logger.info(f"📊 [MetricsAgent] ✅ Metric extraction successful")
            logger.info(f"📊 [MetricsAgent] Extracted {len(validated_metrics)} metrics:")
            for metric, agg in zip(validated_metrics, validated_aggregations):
                logger.info(f"📊 [MetricsAgent]   - {metric} ({agg})")

            logger.debug(f"📊 [MetricsAgent] Complete metrics result: {metrics_result.model_dump()}")
            return metrics_result

        except ClarificationRequiredException:
            # Re-raise clarification exceptions
            raise
        except Exception as e:
            logger.error(f"📊 [MetricsAgent] ❌ Metrics extraction failed: {e}")
            logger.warning(f"📊 [MetricsAgent] 🔄 Falling back to default metric")
            # Fallback: default metric
            return MetricsResult(
                metrics=["net_value"],
                aggregations=["sum"]
            )

    def _request_metric_clarification(
        self,
        query: str,
        ambiguous_terms: List[str],
        ambiguous_matches: List[Dict[str, str]],
        reasoning: str
    ):
        """Request metric clarification using the clarification tool."""
        # Create agent context
        agent_context = ClarificationContext(
            agent_name="MetricsAgent",
            step_name="extract_metrics",
            input_data=query,
            metadata={
                "ambiguous_terms": ambiguous_terms,
                "reasoning": reasoning,
                "available_metrics_count": len(CATALOG_METRICS)
            }
        )

        # Use the clarification tool's built-in method
        clarification_tool.request_metric_clarification(
            ambiguous_terms=ambiguous_terms or ["metrics"],
            available_metrics=ambiguous_matches or [
                {
                    "name": name,
                    "label": name.replace("_", " ").title(),
                    "description": f"{name.replace('_', ' ').title()} metric"
                }
                for name in CATALOG_METRICS
            ],
            agent_context=agent_context
        )

    def _parse_terms(self, terms_str: str) -> List[str]:
        """Parse comma-separated terms string."""
        if not terms_str or terms_str.strip().lower() in ['none', 'null', '']:
            return []
        return [term.strip() for term in terms_str.split(',') if term.strip()]

    def _parse_float(self, value: str) -> float:
        """Parse float from agent output."""
        try:
            if isinstance(value, (int, float)):
                return float(value)
            import re
            numbers = re.findall(r'(\d+\.?\d*)', str(value))
            if numbers:
                return max(0.0, min(1.0, float(numbers[0]) / 100 if float(numbers[0]) > 1 else float(numbers[0])))
            return 0.0
        except:
            return 0.0

    def _parse_json(self, value: str) -> List[Dict[str, str]]:
        """Parse JSON from agent output."""
        try:
            import json
            parsed = json.loads(str(value))
            if isinstance(parsed, list):
                return parsed
        except:
            pass
        return []


class DimensionsAgent(dspy.Module):
    """
    Agent 4: Dimensions, filters, and context-aware operations with integrated ambiguity reasoning.

    Uses dspy.Predict per RULE M1. Handles stateful context per RULE D4.
    """

    def __init__(self):
        super().__init__()
        self.resolver = dspy.Predict(ResolveDimensions)

    def forward(self,
                classified_query: ClassifiedQuery,
                sales_scope: str,
                previous_context: str = "") -> DimensionsResult:
        """Resolve dimensions, filters, and context operations with ambiguity detection."""
        logger.info("🗂️  [DimensionsAgent] Starting dimensions resolution")
        logger.debug(f"🗂️  [DimensionsAgent] Sales scope: {sales_scope}")
        logger.debug(f"🗂️  [DimensionsAgent] Dimension terms: {classified_query.dimension_terms}")
        logger.debug(f"🗂️  [DimensionsAgent] Filter terms: {classified_query.filter_terms}")
        logger.debug(f"🗂️  [DimensionsAgent] Has previous context: {'Yes' if previous_context else 'No'}")
        if previous_context:
            logger.debug(f"🗂️  [DimensionsAgent] Previous context preview: {previous_context[:100]}...")

        try:
            # Prepare available dimensions for ambiguity detection
            valid_dims = get_valid_dimensions_for_scope(sales_scope)
            available_dimensions = [
                {
                    "name": dim,
                    "label": dim.replace("_", " ").title(),
                    "description": f"{dim.replace('_', ' ').title()} dimension"
                }
                for dim in valid_dims
            ]

            # ── PRE-LLM DETERMINISTIC AMBIGUITY CHECK ──────────────────────────
            # Check each classified dimension term against the catalog BEFORE
            # calling the LLM. This is reliable regardless of LLM confidence.
            for term in classified_query.dimension_terms:
                candidates = find_ambiguous_dimension_candidates(term, valid_dims)
                if candidates:
                    # Check if this term was already resolved in the current
                    # clarification re-run (multi-clarification support).
                    # Use get_field_override() which is scoped per-request —
                    # never leaks answers from a previous user session.
                    already_resolved = clarification_tool.get_field_override("group_by")
                    # Only accept this override if it's actually one of the
                    # valid candidates for the current ambiguous term.
                    if already_resolved and already_resolved not in candidates:
                        already_resolved = None
                    if already_resolved:
                        logger.info(
                            f"🗂️  [DimensionsAgent] Term '{term}' was already clarified "
                            f"→ using resolved value '{already_resolved}'"
                        )
                        # Will be injected below after LLM call via override
                        # Store for post-LLM injection
                        classified_query = classified_query.model_copy(
                            update={"dimension_terms": [
                                already_resolved if t == term else t
                                for t in classified_query.dimension_terms
                            ]}
                        )
                    else:
                        logger.info(
                            f"🗂️  [DimensionsAgent] 🤔 Pre-LLM: '{term}' is ambiguous, "
                            f"candidates: {candidates}"
                        )
                        self._request_dimension_clarification(
                            query=classified_query.query_text,
                            ambiguous_terms=[term],
                            ambiguous_matches=[
                                {
                                    "name": c,
                                    "label": c.replace("_", " ").title(),
                                    "description": f"{c.replace('_', ' ').title()} dimension"
                                }
                                for c in candidates
                            ],
                            reasoning=f"'{term}' is not a direct catalog dimension and "
                                      f"matches multiple candidates: {candidates}"
                        )
            # ────────────────────────────────────────────────────────────────────

            # Call DSPy predictor
            classified_json = classified_query.model_dump_json()
            logger.debug("🗂️  [DimensionsAgent] Calling DSPy resolver")
            result = self.resolver(
                classified_query=classified_json,
                sales_scope=sales_scope,
                available_dimensions=str(available_dimensions),
                previous_context=previous_context
            )

            logger.debug(f"🗂️  [DimensionsAgent] Raw DSPy output - group_by: {result.group_by}")
            logger.debug(f"🗂️  [DimensionsAgent] Raw DSPy output - filters: {result.filters}")
            logger.debug(f"🗂️  [DimensionsAgent] Raw DSPy output - context_op: {result.context_operation}")
            logger.debug(f"🗂️  [DimensionsAgent] Raw DSPy output - ranking: {result.ranking_enabled}")
            logger.debug(f"🗂️  [DimensionsAgent] Raw DSPy output - ambiguous_terms: {result.ambiguous_terms}")

            # Parse ambiguity information
            ambiguous_terms = self._parse_terms(result.ambiguous_terms)
            ambiguity_confidence = self._parse_float(result.ambiguity_confidence)
            ambiguous_matches = self._parse_json(result.ambiguous_matches)

            # LLM-based ambiguity check (secondary, after deterministic check)
            if ambiguous_terms and ambiguity_confidence > 0.7:
                logger.info("🗂️  [DimensionsAgent] 🤔 Ambiguity detected, requesting clarification")
                self._request_dimension_clarification(
                    query=classified_query.query_text,
                    ambiguous_terms=ambiguous_terms,
                    ambiguous_matches=ambiguous_matches,
                    reasoning=result.reasoning
                )

            # Continue with normal processing if no ambiguity
            # Parse dimensions
            group_by = self._parse_and_validate_dimensions(
                result.group_by, sales_scope
            )

            # Parse filters
            filters = self._parse_filters(result.filters, sales_scope)

            # Parse ranking
            ranking_enabled = self._parse_boolean(result.ranking_enabled)
            ranking_order = result.ranking_order if ranking_enabled else None
            ranking_limit = self._parse_int(result.ranking_limit) if ranking_enabled else None

            # Validate ranking requires group_by (binary constraint per RULE D5)
            if ranking_enabled and not group_by:
                logger.warning("🗂️  [DimensionsAgent] ⚠️  Ranking requested without group_by, disabling ranking")
                ranking_enabled = False
                ranking_order = None
                ranking_limit = None

            dimensions_result = DimensionsResult(
                group_by=group_by,
                filters=filters,
                context_operation=self._parse_context_operation(result.context_operation)
            )

            logger.info(f"🗂️  [DimensionsAgent] ✅ Dimensions resolution successful")
            if group_by:
                logger.info(f"🗂️  [DimensionsAgent] Group by: {group_by}")
            else:
                logger.info("🗂️  [DimensionsAgent] No grouping dimensions")

            if filters:
                logger.info(f"🗂️  [DimensionsAgent] Found {len(filters)} filters:")
                for f in filters:
                    logger.info(f"🗂️  [DimensionsAgent]   - {f.dimension} {f.operator} {f.value}")
            else:
                logger.info("🗂️  [DimensionsAgent] No filters")

            if ranking_enabled:
                logger.info(f"🗂️  [DimensionsAgent] Ranking: {ranking_order} {ranking_limit}")

            if dimensions_result.context_operation:
                logger.info(f"🗂️  [DimensionsAgent] Context operation: {dimensions_result.context_operation}")

            logger.debug(f"🗂️  [DimensionsAgent] Complete dimensions result: {dimensions_result.model_dump()}")
            return dimensions_result

        except ClarificationRequiredException:
            # Re-raise clarification exceptions
            raise
        except Exception as e:
            logger.error(f"🗂️  [DimensionsAgent] ❌ Dimensions resolution failed: {e}")
            logger.warning(f"🗂️  [DimensionsAgent] 🔄 Falling back to no dimensions")
            # Fallback: no dimensions
            return DimensionsResult()

    def _request_dimension_clarification(
        self,
        query: str,
        ambiguous_terms: List[str],
        ambiguous_matches: List[Dict[str, str]],
        reasoning: str
    ):
        """Request dimension clarification using the clarification tool."""
        agent_context = ClarificationContext(
            agent_name="DimensionsAgent",
            step_name="resolve_dimensions",
            input_data=query,
            metadata={
                "ambiguous_terms": ambiguous_terms,
                "reasoning": reasoning
            }
        )

        clarification_tool.request_dimension_clarification(
            ambiguous_terms=ambiguous_terms or ["dimensions"],
            available_dimensions=ambiguous_matches or [
                {
                    "name": dim,
                    "label": dim.replace("_", " ").title(),
                    "description": f"{dim.replace('_', ' ').title()} dimension"
                }
                for dim in ALL_DIMENSIONS
            ],
            agent_context=agent_context
        )

    def _parse_terms(self, terms_str: str) -> List[str]:
        """Parse comma-separated terms string."""
        if not terms_str or terms_str.strip().lower() in ['none', 'null', '']:
            return []
        return [term.strip() for term in terms_str.split(',') if term.strip()]

    def _parse_float(self, value: str) -> float:
        """Parse float from agent output."""
        try:
            if isinstance(value, (int, float)):
                return float(value)
            import re
            numbers = re.findall(r'(\d+\.?\d*)', str(value))
            if numbers:
                return max(0.0, min(1.0, float(numbers[0]) / 100 if float(numbers[0]) > 1 else float(numbers[0])))
            return 0.0
        except:
            return 0.0

    def _parse_json(self, value: str) -> List[Dict[str, str]]:
        """Parse JSON from agent output."""
        try:
            import json
            parsed = json.loads(str(value))
            if isinstance(parsed, list):
                return parsed
        except:
            pass
        return []

    def _parse_and_validate_dimensions(self, dims_str: str, sales_scope: str) -> Optional[List[str]]:
        """Parse and validate dimensions against scope."""
        if not dims_str or dims_str.strip().lower() in ['none', 'null', '']:
            return None

        raw_dims = [dim.strip() for dim in dims_str.split(',') if dim.strip()]
        if not raw_dims:
            return None

        # Get valid dimensions for scope
        valid_dims = get_valid_dimensions_for_scope(sales_scope)

        # Resolve aliases and validate
        validated_dims = []
        for dim in raw_dims:
            resolved_dim = resolve_dimension_alias(dim)
            if resolved_dim in valid_dims:
                validated_dims.append(resolved_dim)
                # ANTI-PATTERN A2: Never allow invoice_date in group_by
                if resolved_dim == "invoice_date":
                    logger.warning("invoice_date not allowed in group_by, removing")
                    validated_dims.remove(resolved_dim)

        # Limit to max 2 dimensions per RULE
        if len(validated_dims) > 2:
            logger.warning(f"Too many dimensions ({len(validated_dims)}), limiting to 2")
            validated_dims = validated_dims[:2]

        return validated_dims if validated_dims else None

    def _parse_filters(self, filters_str: str, sales_scope: str) -> Optional[List[FilterCondition]]:
        """Parse filters JSON array."""
        if not filters_str or filters_str.strip().lower() in ['none', 'null', '']:
            return None

        try:
            filters_data = json.loads(filters_str)
            if not isinstance(filters_data, list):
                return None

            valid_dims = get_valid_dimensions_for_scope(sales_scope)
            filters = []

            for filter_data in filters_data:
                if not isinstance(filter_data, dict):
                    continue

                dimension = filter_data.get('dimension')
                if not dimension:
                    continue

                resolved_dim = resolve_dimension_alias(dimension)
                if resolved_dim not in valid_dims:
                    continue

                filter_obj = FilterCondition(
                    dimension=resolved_dim,
                    operator=filter_data.get('operator', 'equals'),
                    value=filter_data.get('value', '')
                )
                filters.append(filter_obj)

            return filters if filters else None

        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Failed to parse filters: {e}")
            return None

    def _parse_context_operation(self, operation_str: str) -> Optional[str]:
        """Parse context operation."""
        if not operation_str or operation_str.strip().lower() in ['none', 'null', '']:
            return None
        op = operation_str.strip().upper()
        valid_ops = ["MINIMAL_MESSAGE", "DRILL_DOWN", "ALSO_BY", "REPLACE_BY"]
        return op if op in valid_ops else None

    def _parse_boolean(self, bool_str: str) -> bool:
        """Parse boolean string."""
        if not bool_str:
            return False
        return bool_str.strip().lower() in ['true', 'yes', '1']

    def _parse_int(self, int_str: str) -> Optional[int]:
        """Parse integer string."""
        if not int_str or int_str.strip().lower() in ['none', 'null', '']:
            return None
        try:
            return int(int_str.strip())
        except ValueError:
            return None


class Assembler(dspy.Module):
    """
    Agent 5: Final assembly with binary constraint enforcement.

    Two-phase approach per RULE D6:
    1. LLM-based merge using dspy.Predict
    2. Python constraint enforcement
    """

    def __init__(self):
        super().__init__()
        self.assembler = dspy.Predict(AssembleIntent)

    def forward(self,
                scope_result: ScopeResult,
                time_result: TimeResult,
                metrics_result: MetricsResult,
                dimensions_result: DimensionsResult) -> Intent:
        """Assemble final intent from separate scope and time results."""
        logger.info("🔧 [Assembler] Starting final intent assembly")
        logger.debug(f"🔧 [Assembler] Scope: {scope_result.sales_scope}")
        logger.debug(f"🔧 [Assembler] Time constraint: {time_result.has_time_constraint}")
        logger.debug(f"🔧 [Assembler] Metrics: {len(metrics_result.metrics)} items")
        logger.debug(f"🔧 [Assembler] Dimensions: {len(dimensions_result.group_by) if dimensions_result.group_by else 0} items")
        logger.debug(f"🔧 [Assembler] Filters: {len(dimensions_result.filters) if dimensions_result.filters else 0} items")

        try:
            # Combine scope and time into ScopeTimeResult for compatibility
            scope_time_result = ScopeTimeResult(
                sales_scope=scope_result.sales_scope,
                time_window=time_result.time_window,
                start_date=time_result.start_date,
                end_date=time_result.end_date,
                granularity=time_result.granularity,
                has_time_constraint=time_result.has_time_constraint
            )

            # Phase 1: LLM-based merge per RULE D6
            logger.debug("🔧 [Assembler] Phase 1: LLM-based merge")
            merged_intent = self._llm_merge(scope_time_result, metrics_result, dimensions_result)

            # Phase 2: Python constraint enforcement per RULE D6
            logger.debug("🔧 [Assembler] Phase 2: Python constraint enforcement")
            final_intent = self._enforce_constraints(merged_intent)

            logger.info(f"🔧 [Assembler] ✅ Intent assembly successful")
            logger.info(f"🔧 [Assembler] Final scope: {final_intent.sales_scope}")
            logger.info(f"🔧 [Assembler] Final metrics: {[m.name for m in final_intent.metrics]}")
            if final_intent.group_by:
                logger.info(f"🔧 [Assembler] Final group_by: {final_intent.group_by}")
            if final_intent.filters:
                logger.info(f"🔧 [Assembler] Final filters: {len(final_intent.filters)} items")
            if final_intent.time:
                if final_intent.time.window:
                    logger.info(f"🔧 [Assembler] Final time: {final_intent.time.window}")
                elif final_intent.time.start_date:
                    logger.info(f"🔧 [Assembler] Final time: {final_intent.time.start_date} to {final_intent.time.end_date}")

            logger.debug(f"🔧 [Assembler] Complete final intent: {final_intent.model_dump()}")
            return final_intent

        except Exception as e:
            logger.error(f"🔧 [Assembler] ❌ Intent assembly failed: {e}")
            logger.warning(f"🔧 [Assembler] 🔄 Falling back to minimal valid intent")
            # Fallback: minimal valid intent
            return self._create_fallback_intent(metrics_result)

    def _llm_merge(self, scope_time: ScopeTimeResult, metrics: MetricsResult,
                   dimensions: DimensionsResult) -> Intent:
        """Phase 1: LLM-based merge of upstream results."""
        logger.debug("🔧 [Assembler] Attempting LLM-based merge")
        try:
            # Serialize upstream results per RULE M4
            scope_time_json = scope_time.model_dump_json()
            metrics_json = metrics.model_dump_json()
            dimensions_json = dimensions.model_dump_json()

            result = self.assembler(
                scope_time_result=scope_time_json,
                metrics_result=metrics_json,
                dimensions_result=dimensions_json
            )

            # Parse the final intent JSON
            intent_data = json.loads(result.final_intent)

            # Clean the data to only include valid Intent fields
            valid_fields = {
                'sales_scope', 'metrics', 'group_by', 'filters', 'time', 'post_processing'
            }
            cleaned_data = {k: v for k, v in intent_data.items() if k in valid_fields}

            # Fix metrics format - ensure they're Metric objects, not strings
            if 'metrics' in cleaned_data and cleaned_data['metrics']:
                fixed_metrics = []
                for metric in cleaned_data['metrics']:
                    if isinstance(metric, str):
                        # Convert string to Metric object
                        fixed_metrics.append(Metric(name=metric, aggregation="sum"))
                    elif isinstance(metric, dict):
                        # Already a dict, convert to Metric
                        fixed_metrics.append(Metric(**metric))
                    else:
                        # Already a Metric object
                        fixed_metrics.append(metric)
                cleaned_data['metrics'] = fixed_metrics

            # Fix filters format if needed
            if 'filters' in cleaned_data and cleaned_data['filters']:
                fixed_filters = []
                for filter_item in cleaned_data['filters']:
                    if isinstance(filter_item, dict):
                        fixed_filters.append(Filter(**filter_item))
                    else:
                        fixed_filters.append(filter_item)
                cleaned_data['filters'] = fixed_filters

            # Fix time format if needed
            if 'time' in cleaned_data and cleaned_data['time']:
                if isinstance(cleaned_data['time'], dict):
                    cleaned_data['time'] = TimeSpec(**cleaned_data['time'])

            logger.debug("🔧 [Assembler] LLM merge successful, cleaned and fixed data types")
            return Intent(**cleaned_data)

        except Exception as e:
            logger.warning(f"🔧 [Assembler] ⚠️  LLM merge failed: {e}, using manual assembly")
            return self._manual_assembly(scope_time, metrics, dimensions)

    def _manual_assembly(self, scope_time: ScopeTimeResult, metrics: MetricsResult,
                         dimensions: DimensionsResult) -> Intent:
        """Manual assembly fallback."""
        logger.debug("🔧 [Assembler] Using manual assembly fallback")

        # Build metrics
        metric_objects = [
            Metric(name=name, aggregation=agg)
            for name, agg in zip(metrics.metrics, metrics.aggregations)
        ]

        # Build filters
        filter_objects = None
        if dimensions.filters:
            filter_objects = [
                Filter(
                    dimension=f.dimension,
                    operator=f.operator,
                    value=f.value
                ) for f in dimensions.filters
            ]

        # Build time spec
        time_spec = None
        if scope_time.has_time_constraint:
            time_spec = TimeSpec(
                dimension="invoice_date",
                window=scope_time.time_window,
                start_date=scope_time.start_date,
                end_date=scope_time.end_date,
                granularity=scope_time.granularity
            )

        logger.debug("🔧 [Assembler] Manual assembly completed")
        return Intent(
            sales_scope=scope_time.sales_scope,
            metrics=metric_objects,
            group_by=dimensions.group_by,
            filters=filter_objects,
            time=time_spec
        )

    def _enforce_constraints(self, intent: Intent) -> Intent:
        """Phase 2: Binary constraint enforcement in Python per RULE D5."""
        logger.debug("🔧 [Assembler] Enforcing binary constraints")
        constraints_applied = []

        # Constraint 1: TimeSpec XOR validation
        if intent.time:
            has_window = intent.time.window is not None
            has_dates = intent.time.start_date is not None or intent.time.end_date is not None
            if has_window and has_dates:
                logger.warning("🔧 [Assembler] ⚠️  Both window and dates provided, clearing dates")
                intent.time.start_date = None
                intent.time.end_date = None
                constraints_applied.append("TimeSpec XOR (cleared dates)")

        # Constraint 2: invoice_date never in group_by (ANTI-PATTERN A2)
        if intent.group_by and "invoice_date" in intent.group_by:
            logger.warning("🔧 [Assembler] ⚠️  invoice_date found in group_by, removing")
            intent.group_by.remove("invoice_date")
            if not intent.group_by:  # List became empty
                intent.group_by = None
            constraints_applied.append("Removed invoice_date from group_by")

        # Constraint 3: PRIMARY scope forbids retailer dimensions
        if intent.sales_scope == "PRIMARY" and intent.group_by:
            forbidden_dims = [dim for dim in intent.group_by if dim in SECONDARY_ONLY_DIMENSIONS]
            if forbidden_dims:
                logger.warning(f"🔧 [Assembler] ⚠️  PRIMARY scope forbids dimensions {forbidden_dims}, removing")
                intent.group_by = [dim for dim in intent.group_by if dim not in SECONDARY_ONLY_DIMENSIONS]
                if not intent.group_by:
                    intent.group_by = None
                constraints_applied.append(f"Removed PRIMARY-forbidden dimensions: {forbidden_dims}")

        # Constraint 4: Similar filter validation for PRIMARY scope
        if intent.sales_scope == "PRIMARY" and intent.filters:
            valid_filters = [
                f for f in intent.filters
                if f.dimension not in SECONDARY_ONLY_DIMENSIONS
            ]
            if len(valid_filters) != len(intent.filters):
                logger.warning("🔧 [Assembler] ⚠️  Removed PRIMARY-incompatible filters")
                intent.filters = valid_filters if valid_filters else None
                constraints_applied.append("Removed PRIMARY-incompatible filters")

        if constraints_applied:
            logger.info(f"🔧 [Assembler] Applied {len(constraints_applied)} constraint fixes:")
            for constraint in constraints_applied:
                logger.info(f"🔧 [Assembler]   - {constraint}")
        else:
            logger.debug("🔧 [Assembler] No constraint violations found")

        return intent

    def _create_fallback_intent(self, metrics: MetricsResult) -> Intent:
        """Create minimal fallback intent."""
        metric_objects = [
            Metric(name=name, aggregation=agg)
            for name, agg in zip(metrics.metrics, metrics.aggregations)
        ]

        return Intent(
            sales_scope="SECONDARY",
            metrics=metric_objects
        )