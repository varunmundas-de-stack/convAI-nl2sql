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
    MetricsResult,
    DimensionsResult,
    FilterCondition,
    PostProcessingResult,
    Intent,
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
            # Call DSPy predictor - new signature returns complete ClassifiedQuery JSON
            logger.debug("🏷️  [ClassifierAgent] Calling DSPy ChainOfThought classifier")
            result = self.classifier(query=query)

            logger.debug(f"🏷️  [ClassifierAgent] Raw DSPy output: {result.classified_query}")

            # Parse the JSON result into ClassifiedQuery object
            if isinstance(result.classified_query, str):
                # If it's a JSON string, parse it
                import json
                classified_dict = json.loads(result.classified_query)
                classified = ClassifiedQuery(**classified_dict)
            elif isinstance(result.classified_query, dict):
                # If it's already a dict, use it directly
                classified = ClassifiedQuery(**result.classified_query)
            elif isinstance(result.classified_query, ClassifiedQuery):
                # If it's already a ClassifiedQuery object, use it
                classified = result.classified_query
            else:
                raise ValueError(f"Unexpected classified_query type: {type(result.classified_query)}")

            logger.info(f"🏷️  [ClassifierAgent] ✅ Classification successful")
            logger.info(f"🏷️  [ClassifierAgent] Query intent: {classified.query_intent}")
            logger.info(f"🏷️  [ClassifierAgent] Found {len(classified.classified_terms)} classified terms")
            logger.info(f"🏷️  [ClassifierAgent] Found {len(classified.filter_hints)} filter hints")
            if classified.explicit_scope:
                logger.info(f"🏷️  [ClassifierAgent] Explicit scope: {classified.explicit_scope}")

            # Log term breakdown by role
            term_counts = {}
            for term in classified.classified_terms:
                role = term.role
                term_counts[role] = term_counts.get(role, 0) + 1

            for role, count in term_counts.items():
                logger.info(f"🏷️  [ClassifierAgent] {role} terms: {count}")

            logger.debug(f"🏷️  [ClassifierAgent] Complete classification result: {classified.model_dump()}")
            return classified

        except Exception as e:
            logger.error(f"🏷️  [ClassifierAgent] ❌ Classification failed: {e}")
            logger.warning(f"🏷️  [ClassifierAgent] 🔄 Falling back to minimal classification")

            # Fallback: minimal classification with required fields
            return ClassifiedQuery(
                original_query=query,
                classified_terms=[],
                query_intent="KPI",  # Safe default
                filter_hints=[],
                explicit_scope=None
            )



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
        logger.debug(f"🏢 [ScopeAgent] Explicit scope: {classified_query.explicit_scope}")

        try:
            # Call DSPy predictor - pass ClassifiedQuery object directly per new signature
            logger.debug("🏢 [ScopeAgent] Calling DSPy scope resolver")
            result = self.resolver(classified_query=classified_query)

            logger.debug(f"🏢 [ScopeAgent] Raw DSPy output: {result.scope_result}")

            # Parse the JSON result into ScopeResult object
            if isinstance(result.scope_result, str):
                # If it's a JSON string, parse it
                import json
                scope_dict = json.loads(result.scope_result)
                scope_result = ScopeResult(**scope_dict)
            elif isinstance(result.scope_result, dict):
                # If it's already a dict, use it directly
                scope_result = ScopeResult(**result.scope_result)
            elif isinstance(result.scope_result, ScopeResult):
                # If it's already a ScopeResult object, use it
                scope_result = result.scope_result
            else:
                raise ValueError(f"Unexpected scope_result type: {type(result.scope_result)}")

            logger.info(f"🏢 [ScopeAgent] ✅ Scope resolution successful")
            logger.info(f"🏢 [ScopeAgent] Sales scope: {scope_result.sales_scope}")

            logger.debug(f"🏢 [ScopeAgent] Complete scope result: {scope_result.model_dump()}")
            return scope_result

        except Exception as e:
            logger.error(f"🏢 [ScopeAgent] ❌ Scope resolution failed: {e}")
            logger.warning(f"🏢 [ScopeAgent] 🔄 Falling back to default scope")
            # Fallback: default scope
            return ScopeResult(sales_scope="SECONDARY")



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

    def forward(self, classified_query: ClassifiedQuery, current_date: str, previous_context: str = "") -> TimeResult:
        """Resolve time specification with decision logic and clarification rules."""
        logger.info("⏰ [TimeAgent] Starting time resolution")
        logger.debug(f"⏰ [TimeAgent] Current date: {current_date}")
        logger.debug(f"⏰ [TimeAgent] Query intent: {classified_query.query_intent}")

        # Log time-related terms from classified query
        time_terms = [term for term in classified_query.classified_terms if term.role in ["TIME_RANGE", "TIME_GRANULARITY"]]
        logger.debug(f"⏰ [TimeAgent] Time-related terms: {[term.term for term in time_terms]}")
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
                granularity=None
            )

        try:
            # Call DSPy predictor - pass ClassifiedQuery object directly per new signature
            logger.debug("⏰ [TimeAgent] Calling DSPy time resolver")
            result = self.resolver(
                classified_query=classified_query,
                current_date=current_date,
                query_intent=classified_query.query_intent,
                previous_context=previous_context
            )

            logger.debug(f"⏰ [TimeAgent] Raw DSPy output: {result.time_result}")

            # Parse the JSON result into TimeResult object
            if isinstance(result.time_result, str):
                # If it's a JSON string, parse it
                import json
                time_dict = json.loads(result.time_result)
                time_result = TimeResult(**time_dict)
            elif isinstance(result.time_result, dict):
                # If it's already a dict, use it directly
                time_result = TimeResult(**result.time_result)
            elif isinstance(result.time_result, TimeResult):
                # If it's already a TimeResult object, use it
                time_result = result.time_result
            else:
                raise ValueError(f"Unexpected time_result type: {type(result.time_result)}")

            # Apply decision logic and clarification rules
            time_result = self._apply_time_decision_rules(
                time_result, classified_query, classified_query.query_intent, previous_context
            )

            # Handle clarification request if needed
            if time_result.has_time_constraint and not time_result.time_window and not time_result.start_date:
                # Need clarification if performance query but no time specified
                self._request_time_clarification(classified_query.original_query, classified_query.query_intent)

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

            logger.debug(f"⏰ [TimeAgent] Complete time result: {time_result.model_dump()}")
            return time_result

        except ClarificationRequiredException:
            # Re-raise clarification exceptions
            raise
        except Exception as e:
            logger.error(f"⏰ [TimeAgent] ❌ Time resolution failed: {e}")
            logger.warning(f"⏰ [TimeAgent] 🔄 Falling back to no time constraint")
            # Fallback: no time constraint
            return TimeResult()

    def _apply_time_decision_rules(self, time_result: TimeResult, classified_query: ClassifiedQuery,
                                 query_intent: str, previous_context: str) -> TimeResult:
        """Apply the time decision framework rules."""
        logger.debug("⏰ [TimeAgent] Applying time decision rules")

        # Check if query is structural/catalog-based
        is_structural_query = self._is_structural_query(classified_query, query_intent)

        if is_structural_query:
            # Structural queries don't need time
            logger.debug("⏰ [TimeAgent] Structural query detected - time not required")
            time_result.has_time_constraint = False
            time_result.requires_clarification = False
            return time_result

        # Performance queries require time
        # Check if query has time-related terms
        time_terms = [term for term in classified_query.classified_terms
                     if term.role in ["TIME_RANGE", "TIME_GRANULARITY"]]

        has_time_from_query = (
            time_result.time_window or
            time_result.start_date or
            bool(time_terms)
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

    def _is_structural_query(self, classified_query: ClassifiedQuery, query_intent: str) -> bool:
        """Check if query is asking about structure/membership rather than performance."""
        # Check for structural intent keywords
        structural_keywords = [
            "what", "which", "list", "show", "available", "exist", "have",
            "brands", "zones", "categories", "products", "retailers", "distributors"
        ]

        query_lower = classified_query.original_query.lower()

        # Check if query has metric-related terms
        metric_terms = [term for term in classified_query.classified_terms if term.role == "METRIC"]

        # If query asks "what/which X" without metrics, it's likely structural
        for keyword in structural_keywords:
            if keyword in query_lower:
                # Check if it's asking about entities without measuring them
                if not metric_terms and not any(
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

        query_lower = classified_query.original_query.lower()
        return any(indicator in query_lower for indicator in all_time_indicators)

    def _request_time_clarification(self, query_text: str, query_intent: str):
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

        question = clarification_prompts.get(query_intent, clarification_prompts["DEFAULT"])

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
            metadata={"query_intent": query_intent}
        )

        request_id = clarification_tool.request_clarification(
            clarification_type=ClarificationType.TIME,
            field_name="time",
            question=question,
            context=f"This {query_intent.lower()} query requires a time period to provide meaningful results.",
            options=options,
            allow_custom=True,
            metadata={"query_intent": query_intent}
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

        # Log metric-related terms from classified query
        metric_terms = [term for term in classified_query.classified_terms if term.role == "METRIC"]
        logger.debug(f"📊 [MetricsAgent] Metric terms: {[term.term for term in metric_terms]}")

        try:
            # Prepare available metrics for context
            available_metrics = [
                {
                    "name": name,
                    "label": name.replace("_", " ").title(),
                    "description": f"{name.replace('_', ' ').title()} metric"
                }
                for name in CATALOG_METRICS
            ]

            # Call DSPy predictor - pass ClassifiedQuery object directly per new signature
            logger.debug("📊 [MetricsAgent] Calling DSPy extractor")
            result = self.extractor(
                classified_query=classified_query,
                sales_scope=sales_scope,
                available_metrics=json.dumps(available_metrics)
            )

            logger.debug(f"📊 [MetricsAgent] Raw DSPy output: {result.metrics_result}")

            # Parse the JSON result into MetricsResult object
            if isinstance(result.metrics_result, str):
                # If it's a JSON string, parse it
                metrics_dict = json.loads(result.metrics_result)
                metrics_result = MetricsResult(**metrics_dict)
            elif isinstance(result.metrics_result, dict):
                # If it's already a dict, use it directly
                metrics_result = MetricsResult(**result.metrics_result)
            elif isinstance(result.metrics_result, MetricsResult):
                # If it's already a MetricsResult object, use it
                metrics_result = result.metrics_result
            else:
                raise ValueError(f"Unexpected metrics_result type: {type(result.metrics_result)}")

            # Validate and process the metrics
            metrics_result = self._validate_and_process_metrics(metrics_result)

            logger.info(f"📊 [MetricsAgent] ✅ Metric extraction successful")
            logger.info(f"📊 [MetricsAgent] Extracted {len(metrics_result.metrics)} metrics: {metrics_result.metrics}")
            logger.info(f"📊 [MetricsAgent] Aggregations: {metrics_result.aggregations}")

            logger.debug(f"📊 [MetricsAgent] Complete metrics result: {metrics_result.model_dump()}")
            return metrics_result

        except Exception as e:
            logger.error(f"📊 [MetricsAgent] ❌ Metric extraction failed: {e}")
            logger.warning(f"📊 [MetricsAgent] 🔄 Falling back to default metric")
            # Fallback: default net_value metric
            return MetricsResult(
                metrics=["net_value"],
                aggregations=["sum"]
            )

    def _validate_and_process_metrics(self, metrics_result: MetricsResult) -> MetricsResult:
        """Validate and process metrics from LLM output."""
        validated_metrics = []
        validated_aggregations = []

        for i, metric in enumerate(metrics_result.metrics):
            resolved_metric = resolve_metric_alias(metric)
            logger.debug(f"📊 [MetricsAgent] Resolving '{metric}' -> '{resolved_metric}'")

            if resolved_metric in CATALOG_METRICS:
                validated_metrics.append(resolved_metric)
                # Use provided aggregation or default
                if i < len(metrics_result.aggregations) and metrics_result.aggregations[i] in ["sum", "count", "avg"]:
                    validated_aggregations.append(metrics_result.aggregations[i])
                    logger.debug(f"📊 [MetricsAgent] Using provided aggregation: {metrics_result.aggregations[i]}")
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

        return MetricsResult(
            metrics=validated_metrics,
            aggregations=validated_aggregations
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

        # Log dimension-related terms from classified query
        dimension_terms = [term for term in classified_query.classified_terms if term.role == "DIMENSION"]
        filter_terms = [term for term in classified_query.classified_terms if term.role == "FILTER_VALUE"]
        logger.debug(f"🗂️  [DimensionsAgent] Dimension terms: {[term.term for term in dimension_terms]}")
        logger.debug(f"🗂️  [DimensionsAgent] Filter terms: {[term.term for term in filter_terms]}")
        logger.debug(f"🗂️  [DimensionsAgent] Has previous context: {'Yes' if previous_context else 'No'}")

        try:
            # Prepare available dimensions for context
            valid_dims = get_valid_dimensions_for_scope(sales_scope)
            available_dimensions = [
                {
                    "name": dim,
                    "label": dim.replace("_", " ").title(),
                    "description": f"{dim.replace('_', ' ').title()} dimension"
                }
                for dim in valid_dims
            ]

            # Call DSPy predictor - pass ClassifiedQuery object directly per new signature
            logger.debug("🗂️  [DimensionsAgent] Calling DSPy resolver")
            result = self.resolver(
                classified_query=classified_query,
                sales_scope=sales_scope,
                available_dimensions=json.dumps(available_dimensions),
                previous_context=previous_context
            )

            logger.debug(f"🗂️  [DimensionsAgent] Raw DSPy output: {result.dimensions_result}")

            # Parse the JSON result into DimensionsResult object
            if isinstance(result.dimensions_result, str):
                # If it's a JSON string, parse it
                dimensions_dict = json.loads(result.dimensions_result)
                dimensions_result = DimensionsResult(**dimensions_dict)
            elif isinstance(result.dimensions_result, dict):
                # If it's already a dict, use it directly
                dimensions_result = DimensionsResult(**result.dimensions_result)
            elif isinstance(result.dimensions_result, DimensionsResult):
                # If it's already a DimensionsResult object, use it
                dimensions_result = result.dimensions_result
            else:
                raise ValueError(f"Unexpected dimensions_result type: {type(result.dimensions_result)}")

            # Validate and process the dimensions
            dimensions_result = self._validate_and_process_dimensions(dimensions_result, sales_scope)

            logger.info(f"🗂️  [DimensionsAgent] ✅ Dimensions resolution successful")
            if dimensions_result.group_by:
                logger.info(f"🗂️  [DimensionsAgent] Group by: {dimensions_result.group_by}")
            if dimensions_result.filters:
                logger.info(f"🗂️  [DimensionsAgent] Filters: {len(dimensions_result.filters)} filter(s)")

            logger.debug(f"🗂️  [DimensionsAgent] Complete dimensions result: {dimensions_result.model_dump()}")
            return dimensions_result

        except Exception as e:
            logger.error(f"🗂️  [DimensionsAgent] ❌ Dimensions resolution failed: {e}")
            logger.warning(f"🗂️  [DimensionsAgent] 🔄 Falling back to no dimensions")
            # Fallback: no dimensions
            return DimensionsResult(group_by=None, filters=None)
    def _validate_and_process_dimensions(self, dimensions_result: DimensionsResult, sales_scope: str) -> DimensionsResult:
        """Validate and process dimensions from LLM output."""
        valid_dims = get_valid_dimensions_for_scope(sales_scope)

        # Validate group_by dimensions
        validated_group_by = None
        if dimensions_result.group_by:
            validated_group_by = []
            for dim in dimensions_result.group_by:
                resolved_dim = resolve_dimension_alias(dim)
                if resolved_dim in valid_dims:
                    validated_group_by.append(resolved_dim)
                    logger.debug(f"🗂️  [DimensionsAgent] Validated dimension: {resolved_dim}")
                else:
                    logger.warning(f"🗂️  [DimensionsAgent] ⚠️  Invalid dimension '{resolved_dim}' not in scope")

            # Apply hierarchy constraints (max 1 per hierarchy)
            validated_group_by = self._apply_hierarchy_constraints(validated_group_by)

            # Limit to 2 dimensions max
            if len(validated_group_by) > 2:
                logger.warning(f"🗂️  [DimensionsAgent] ⚠️  Too many dimensions, limiting to first 2")
                validated_group_by = validated_group_by[:2]

            if not validated_group_by:
                validated_group_by = None

        # Validate filters
        validated_filters = None
        if dimensions_result.filters:
            validated_filters = []
            for filter_cond in dimensions_result.filters:
                if filter_cond.dimension in valid_dims:
                    validated_filters.append(filter_cond)
                    logger.debug(f"🗂️  [DimensionsAgent] Validated filter: {filter_cond.dimension} {filter_cond.operator} {filter_cond.value}")
                else:
                    logger.warning(f"🗂️  [DimensionsAgent] ⚠️  Invalid filter dimension '{filter_cond.dimension}'")

            if not validated_filters:
                validated_filters = None

        return DimensionsResult(
            group_by=validated_group_by,
            filters=validated_filters
        )

    def _apply_hierarchy_constraints(self, dimensions: List[str]) -> List[str]:
        """Apply hierarchy constraints - max 1 dimension per hierarchy."""
        from .schemas import GEO_HIERARCHY, PRODUCT_HIERARCHY

        geo_dims = [d for d in dimensions if d in GEO_HIERARCHY]
        product_dims = [d for d in dimensions if d in PRODUCT_HIERARCHY]
        other_dims = [d for d in dimensions if d not in GEO_HIERARCHY and d not in PRODUCT_HIERARCHY]

        # Keep only first dimension from each hierarchy
        result = []
        if geo_dims:
            result.append(geo_dims[0])
            if len(geo_dims) > 1:
                logger.warning(f"🗂️  [DimensionsAgent] ⚠️  Multiple geo dimensions, keeping only: {geo_dims[0]}")

        if product_dims:
            result.append(product_dims[0])
            if len(product_dims) > 1:
                logger.warning(f"🗂️  [DimensionsAgent] ⚠️  Multiple product dimensions, keeping only: {product_dims[0]}")

        result.extend(other_dims)
        return result

# =============================================================================
# ASSEMBLER
# =============================================================================

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
                classified_query: ClassifiedQuery,
                scope_result: ScopeResult,
                time_result: TimeResult,
                metrics_result: MetricsResult,
                dimensions_result: DimensionsResult) -> Intent:
        """Assemble final intent from individual agent results."""
        logger.info("🔧 [Assembler] Starting final intent assembly")
        logger.debug(f"🔧 [Assembler] Query intent: {classified_query.query_intent}")
        logger.debug(f"🔧 [Assembler] Scope: {scope_result.sales_scope}")
        logger.debug(f"🔧 [Assembler] Time constraint: {time_result.has_time_constraint}")
        logger.debug(f"🔧 [Assembler] Metrics: {len(metrics_result.metrics)} items")
        logger.debug(f"🔧 [Assembler] Dimensions: {len(dimensions_result.group_by) if dimensions_result.group_by else 0} items")
        logger.debug(f"🔧 [Assembler] Filters: {len(dimensions_result.filters) if dimensions_result.filters else 0} items")

        try:
            # Phase 1: LLM-based merge using new signature
            logger.debug("🔧 [Assembler] Phase 1: LLM-based merge")
            merged_intent = self._llm_merge(classified_query, scope_result, time_result, metrics_result, dimensions_result)

            # Phase 2: Python constraint enforcement per RULE D6
            logger.debug("🔧 [Assembler] Phase 2: Python constraint enforcement")
            final_intent = self._enforce_constraints(merged_intent)

            logger.info(f"🔧 [Assembler] ✅ Intent assembly successful")
            logger.info(f"🔧 [Assembler] Final scope: {final_intent.sales_scope}")
            logger.info(f"🔧 [Assembler] Final metrics: {[m.name for m in final_intent.metrics]}")
            if final_intent.group_by:
                logger.info(f"🔧 [Assembler] Final group_by: {final_intent.group_by}")
            if final_intent.time:
                if final_intent.time.window:
                    logger.info(f"🔧 [Assembler] Final time: {final_intent.time.window}")
                else:
                    logger.info(f"🔧 [Assembler] Final time: {final_intent.time.start_date} to {final_intent.time.end_date}")

            logger.debug(f"🔧 [Assembler] Complete final intent: {final_intent.model_dump()}")
            return final_intent

        except Exception as e:
            logger.error(f"🔧 [Assembler] ❌ Intent assembly failed: {e}")
            logger.warning(f"🔧 [Assembler] 🔄 Falling back to manual assembly")
            # Fallback: manual assembly
            return self._manual_assembly(classified_query, scope_result, time_result, metrics_result, dimensions_result)

    def _llm_merge(self, classified_query: ClassifiedQuery, scope_result: ScopeResult,
                   time_result: TimeResult, metrics_result: MetricsResult,
                   dimensions_result: DimensionsResult) -> Intent:
        """Phase 1: LLM-based merge of upstream results."""
        logger.debug("🔧 [Assembler] Attempting LLM-based merge")
        try:
            # Call DSPy predictor with all individual results per new signature
            result = self.assembler(
                classified_query=classified_query,
                scope_result=scope_result,
                time_result=time_result,
                metrics_result=metrics_result,
                dimensions_result=dimensions_result
            )

            logger.debug(f"🔧 [Assembler] Raw LLM merge output: {result.final_intent}")

            # Parse the JSON result into Intent object
            if isinstance(result.final_intent, str):
                # If it's a JSON string, parse it
                intent_dict = json.loads(result.final_intent)
                intent = Intent(**intent_dict)
            elif isinstance(result.final_intent, dict):
                # If it's already a dict, use it directly
                intent = Intent(**result.final_intent)
            elif isinstance(result.final_intent, Intent):
                # If it's already an Intent object, use it
                intent = result.final_intent
            else:
                raise ValueError(f"Unexpected final_intent type: {type(result.final_intent)}")

            logger.debug("🔧 [Assembler] ✅ LLM merge successful")
            return intent

        except Exception as e:
            logger.warning(f"🔧 [Assembler] ⚠️  LLM merge failed: {e}")
            logger.debug("🔧 [Assembler] Falling back to manual assembly")
            # Fallback to manual assembly
            return self._manual_assembly(classified_query, scope_result, time_result, metrics_result, dimensions_result)

    def _manual_assembly(self, classified_query: ClassifiedQuery, scope_result: ScopeResult,
                         time_result: TimeResult, metrics_result: MetricsResult,
                         dimensions_result: DimensionsResult) -> Intent:
        """Manual assembly fallback."""
        logger.debug("🔧 [Assembler] Using manual assembly fallback")

        # Import schema classes from the new schema
        from .schemas import MetricSpec, TimeSpec, PostProcessingResult

        # Build metrics
        metrics = [
            MetricSpec(name=metrics_result.metrics[i], aggregation=metrics_result.aggregations[i])
            for i in range(len(metrics_result.metrics))
        ]

        # Build time specification
        time_spec = None
        if time_result.has_time_constraint:
            time_spec = TimeSpec(
                dimension="invoice_date",
                window=time_result.time_window,
                start_date=time_result.start_date,
                end_date=time_result.end_date,
                granularity=time_result.granularity
            )

        # Build post-processing based on query intent
        post_processing = None
        if classified_query.query_intent in ["RANKING", "COMPARISON", "TREND"]:
            post_processing = self._derive_post_processing(classified_query.query_intent, time_result)

        # Assemble final intent
        intent = Intent(
            sales_scope=scope_result.sales_scope,
            metrics=metrics,
            group_by=dimensions_result.group_by,
            filters=dimensions_result.filters,
            time=time_spec,
            post_processing=post_processing
        )

        logger.debug("🔧 [Assembler] ✅ Manual assembly successful")
        return intent

    def _derive_post_processing(self, query_intent: str, time_result: TimeResult) -> Optional[PostProcessingResult]:
        """Derive post-processing configuration from query intent."""
        from .schemas import RankingConfig, ComparisonConfig

        if query_intent == "RANKING":
            return PostProcessingResult(
                ranking=RankingConfig(enabled=True, order="desc", limit=10),
                comparison=None,
                derived_metric="none"
            )
        elif query_intent == "COMPARISON":
            if time_result.time_window:
                return PostProcessingResult(
                    ranking=None,
                    comparison=ComparisonConfig(type="period", comparison_window=time_result.time_window),
                    derived_metric="period_change"
                )
        elif query_intent == "TREND" and time_result.granularity:
            derived_metric = "none"
            if time_result.time_window and "month" in time_result.time_window:
                derived_metric = "mom_growth"
            elif time_result.time_window and "year" in time_result.time_window:
                derived_metric = "yoy_growth"

            return PostProcessingResult(
                ranking=None,
                comparison=None,
                derived_metric=derived_metric
            )

        return None
       

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
        from .schemas import MetricSpec
        metric_objects = [
            MetricSpec(name=name, aggregation=agg)
            for name, agg in zip(metrics.metrics, metrics.aggregations)
        ]

        return Intent(
            sales_scope="SECONDARY",
            metrics=metric_objects
        )