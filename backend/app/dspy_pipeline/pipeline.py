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
    ScopeTimeAgent,
    MetricsAgent,
    DimensionsAgent,
    Assembler
)
from .schemas import (
    ClassifiedQuery,
    ScopeTimeResult,
    MetricsResult,
    DimensionsResult
)
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
    2. ScopeTimeAgent - Sales scope and time resolution
    3. MetricsAgent - Metric extraction and aggregation
    4. DimensionsAgent - Dimensions, filters, and context handling
    5. Assembler - Final assembly with binary constraint enforcement
    """

    def __init__(self):
        """Initialize all agents."""
        super().__init__()

        # Initialize agent modules
        self.classifier = ClassifierAgent()
        self.scope_time_agent = ScopeTimeAgent()
        self.metrics_agent = MetricsAgent()
        self.dimensions_agent = DimensionsAgent()
        self.assembler = Assembler()

        logger.info("IntentExtractionPipeline initialized")

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
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 1/5: Term Classification")
            stage_start_time = time.time()
            classified_query: ClassifiedQuery = self.classifier(query)
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 1 completed in {stage_duration:.2f}s")

            # Stage 2: Scope & Time Resolution
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 2/5: Scope & Time Resolution")
            stage_start_time = time.time()
            scope_time_result: ScopeTimeResult = self.scope_time_agent(classified_query, current_date)
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 2 completed in {stage_duration:.2f}s")

            # Stage 3: Metrics Extraction
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 3/5: Metrics Extraction")
            stage_start_time = time.time()
            metrics_result: MetricsResult = self.metrics_agent(
                classified_query,
                scope_time_result.sales_scope
            )
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 3 completed in {stage_duration:.2f}s")

            # Stage 4: Dimensions & Context Resolution
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 4/5: Dimensions & Context Resolution")
            stage_start_time = time.time()
            dimensions_result: DimensionsResult = self.dimensions_agent(
                classified_query,
                scope_time_result.sales_scope,
                previous_context
            )
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 4 completed in {stage_duration:.2f}s")

            # Stage 5: Final Assembly
            logger.info("🚀 [DSPy Pipeline] 📍 Stage 5/5: Final Assembly")
            stage_start_time = time.time()
            final_intent: Intent = self.assembler(
                scope_time_result,
                metrics_result,
                dimensions_result
            )
            stage_duration = time.time() - stage_start_time
            logger.info(f"🚀 [DSPy Pipeline] ✅ Stage 5 completed in {stage_duration:.2f}s")

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

    def get_pipeline_info(self) -> dict:
        """Get information about the pipeline structure."""
        return {
            "pipeline_type": "DSPy Modular",
            "agents": [
                "ClassifierAgent",
                "ScopeTimeAgent",
                "MetricsAgent",
                "DimensionsAgent",
                "Assembler"
            ],
            "compilation_ready": True,
            "optimization_mode": "BootstrapFewShot"
        }