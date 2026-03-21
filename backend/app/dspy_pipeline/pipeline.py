"""
Main DSPy Pipeline for Intent Extraction.

Following RULE M2: Pipeline is a dspy.Module with single forward()
Following RULE M3: forward() is pure data flow, no business logic
Following RULE M5: current_date injected at pipeline level
"""

import logging
import time
from datetime import date
from typing import Optional

import dspy

from .modules import (
    ClassifierAgent,
    ScopeAgent,
    TimeAgent,
    ScopeTimeAgent,
    MetricsAgent,
    DimensionsAgent,
    Assembler
)
from .schemas import (
    ClassifiedQuery,
    ScopeResult,
    TimeResult,
    ScopeTimeResult,
    MetricsResult,
    DimensionsResult
)
from .clarification_tool import ClarificationRequiredException
from ..models.intent import Intent

logger = logging.getLogger(__name__)

# =============================================================================
# MAIN PIPELINE
# =============================================================================

class IntentExtractionPipeline(dspy.Module):
    """
    Main DSPy pipeline that orchestrates all intent extraction agents.

    This pipeline replaces the monolithic LLM prompt with a sequence of
    specialized agents, enabling independent optimization and better
    failure isolation.

    Architecture:
    1. ClassifierAgent - Term classification and semantic labeling
    2. ScopeAgent - Sales scope determination (PRIMARY/SECONDARY)
    3. TimeAgent - Time constraint resolution with decision rules
    4. MetricsAgent - Metric extraction and aggregation
    5. DimensionsAgent - Dimensions, filters, and context handling
    6. Assembler - Final assembly with binary constraint enforcement
    """

    def __init__(self):
        """Initialize all agents."""
        super().__init__()

        # Initialize agent modules
        self.classifier = ClassifierAgent()
        self.scope_agent = ScopeAgent()
        self.time_agent = TimeAgent()
        self.metrics_agent = MetricsAgent()
        self.dimensions_agent = DimensionsAgent()
        self.assembler = Assembler()

        logger.info("IntentExtractionPipeline initialized with 6 agents")

    def forward(self, query: str, previous_context: str = "", current_date: Optional[str] = None) -> Intent:
        """
        Extract intent from natural language query.

        Pure data flow per RULE M3 - no business logic, just agent chaining.

        Args:
            query: Natural language user query
            previous_context: Previous QCO context as JSON string (empty on first turn)
            current_date: Current date in YYYY-MM-DD format (defaults to today)

        Returns:
            Intent: Structured intent object ready for downstream validation

        Raises:
            Exception: If pipeline fails at any stage
        """
        # Inject current date per RULE M5
        if current_date is None:
            current_date = date.today().isoformat()

        logger.info("🚀 [DSPy Pipeline] ======================================")
        logger.info(f"🚀 [DSPy Pipeline] Starting intent extraction pipeline")
        logger.info(f"🚀 [DSPy Pipeline] Query: '{query[:100]}{'...' if len(query) > 100 else ''}'")
        logger.info(f"🚀 [DSPy Pipeline] Current date: {current_date}")
        logger.info(f"🚀 [DSPy Pipeline] Has context: {'Yes' if previous_context else 'No'}")
        if previous_context:
            logger.debug(f"🚀 [DSPy Pipeline] Context preview: {previous_context[:200]}...")
        logger.info("🚀 [DSPy Pipeline] ======================================")

        pipeline_start_time = time.time()

        try:
            # Stage 1: Term Classification
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 1/6: Term Classification")
            stage_start_time = time.time()
            classified_query: ClassifiedQuery = self.classifier(query)
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 1 completed in {stage_duration:.2f}s")

            # Stage 2: Scope Resolution
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 2/6: Scope Resolution")
            stage_start_time = time.time()
            scope_result: ScopeResult = self.scope_agent(classified_query)
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 2 completed in {stage_duration:.2f}s")

            # Stage 3: Time Resolution
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 3/6: Time Resolution")
            stage_start_time = time.time()

            # Infer intent category for time decision logic
            intent_category = self._infer_intent_category(classified_query)

            try:
                time_result: TimeResult = self.time_agent(
                    classified_query,
                    current_date,
                    intent_category,
                    previous_context
                )
            except ClarificationRequiredException as clar_exc:
                # Stages 1-2 succeeded — stamp their results as partial_output
                # so the resume path can build a complete valid intent.
                partial = {
                    "sales_scope": scope_result.sales_scope,
                    # Add default metrics for now - will be determined in stage 4
                    "metrics": [{"name": "net_value", "aggregation": "sum"}],
                }
                if isinstance(clar_exc.agent_context, dict):
                    clar_exc.agent_context["partial_output"] = partial
                else:
                    clar_exc.agent_context = {"partial_output": partial}
                logger.info(
                    f"🚀 [DSPy Pipeline] Clarification needed at Stage 3; "
                    f"injecting partial output: scope={partial['sales_scope']}"
                )
                raise
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 3 completed in {stage_duration:.2f}s")

            # Stage 4: Metrics Extraction
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 4/6: Metrics Extraction")
            stage_start_time = time.time()
            metrics_result: MetricsResult = self.metrics_agent(
                classified_query,
                scope_result.sales_scope
            )
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 4 completed in {stage_duration:.2f}s")

            # Stage 5: Dimensions & Context Resolution
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 5/6: Dimensions & Context Resolution")
            stage_start_time = time.time()
            try:
                dimensions_result: DimensionsResult = self.dimensions_agent(
                    classified_query,
                    scope_result.sales_scope,
                    previous_context
                )
            except ClarificationRequiredException as clar_exc:
                # Stages 1-4 succeeded — stamp their results as partial_output
                # so the resume path can build a complete valid intent.
                partial = {
                    "sales_scope": scope_result.sales_scope,
                    "metrics": [
                        {"name": name, "aggregation": agg}
                        for name, agg in zip(
                            metrics_result.metrics, metrics_result.aggregations
                        )
                    ],
                }
                if time_result.has_time_constraint:
                    partial["time"] = {
                        "dimension": "invoice_date",
                        "window": time_result.time_window,
                        "start_date": time_result.start_date,
                        "end_date": time_result.end_date,
                        "granularity": time_result.granularity,
                    }
                if isinstance(clar_exc.agent_context, dict):
                    clar_exc.agent_context["partial_output"] = partial
                else:
                    clar_exc.agent_context = {"partial_output": partial}
                logger.info(
                    f"🚀 [DSPy Pipeline] Clarification needed at Stage 5; "
                    f"injecting partial output: scope={partial['sales_scope']}, "
                    f"metrics={[m['name'] for m in partial['metrics']]}"
                )
                raise
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 5 completed in {stage_duration:.2f}s")

            # Stage 6: Final Assembly
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 6/6: Final Assembly")
            stage_start_time = time.time()
            final_intent: Intent = self.assembler(
                scope_result,
                time_result,
                metrics_result,
                dimensions_result
            )
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 6 completed in {stage_duration:.2f}s")

            pipeline_duration = time.time() - pipeline_start_time
            logger.info("🚀 [DSPy Pipeline] ======================================")
            logger.info(f"🚀 [DSPy Pipeline] 🎉 Pipeline completed successfully!")
            logger.info(f"🚀 [DSPy Pipeline] Total duration: {pipeline_duration:.2f}s")
            logger.info(f"🚀 [DSPy Pipeline] Final intent type: {final_intent.sales_scope}")
            logger.info(f"🚀 [DSPy Pipeline] Final metrics: {[m.name for m in final_intent.metrics]}")
            if final_intent.group_by:
                logger.info(f"🚀 [DSPy Pipeline] Final dimensions: {final_intent.group_by}")
            logger.info("🚀 [DSPy Pipeline] ======================================")

            return final_intent

        except Exception as e:
            pipeline_duration = time.time() - pipeline_start_time
            logger.error("🚀 [DSPy Pipeline] ======================================")
            logger.error(f"🚀 [DSPy Pipeline] ❌ Pipeline failed after {pipeline_duration:.2f}s")
            logger.error(f"🚀 [DSPy Pipeline] Error: {str(e)}")
            logger.error("🚀 [DSPy Pipeline] ======================================")
            raise

    def _infer_intent_category(self, classified_query: ClassifiedQuery) -> str:
        """Infer intent category from classified query terms for time decision logic."""
        query_lower = classified_query.query_text.lower()

        # Check for trend indicators
        if (classified_query.time_expressions and
            any(trend_word in query_lower for trend_word in ["trend", "over time", "daily", "weekly", "monthly"])):
            return "TREND"

        # Check for ranking indicators
        if classified_query.ranking_indicators or any(
            rank_word in query_lower for rank_word in ["top", "bottom", "highest", "lowest", "best", "worst"]
        ):
            return "RANKING"

        # Check for comparison indicators
        if classified_query.comparison_indicators or any(
            comp_word in query_lower for comp_word in ["vs", "versus", "compared", "compare", "growth", "change"]
        ):
            return "COMPARISON"

        # Check for distribution indicators
        if classified_query.dimension_terms and any(
            dist_word in query_lower for dist_word in ["by", "breakdown", "split", "across", "distribution"]
        ):
            return "DISTRIBUTION"

        # Check for structural/catalog queries
        if any(struct_word in query_lower for struct_word in
               ["what", "which", "list", "show", "available", "exist", "have"]):
            return "CATALOG"

        # Default to KPI for metric-focused queries
        if classified_query.metric_terms:
            return "KPI"

        return "UNKNOWN"

    def get_pipeline_info(self) -> dict:
        """Get information about the pipeline structure."""
        return {
            "pipeline_type": "DSPy Modular",
            "agents": [
                "ClassifierAgent",
                "ScopeAgent",
                "TimeAgent",
                "MetricsAgent",
                "DimensionsAgent",
                "Assembler"
            ],
            "compilation_ready": True,
            "optimization_mode": "BootstrapFewShot"
        }