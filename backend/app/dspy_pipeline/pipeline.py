import dspy
import logging
import time
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

from .modules import (
    ClassifierModule,
    ScopeModule,
    TimeModule,
    MetricsModule,
    DimensionsModule,
    PostProcessingModule,
    AssemblerModule,
)
from .schemas import Intent


class IntentExtractionPipeline(dspy.Module):
    """
    Orchestrates the full NL → Intent pipeline.

    Flow:
        1. Classifier
        2. Scope
        3. Time
        4. Metrics
        5. Dimensions
        6. PostProcessing
        7. Assembly
        8. Final Validation (Pydantic)
    """

    def __init__(self):
        super().__init__()
        self.classifier = ClassifierModule()
        self.scope = ScopeModule()
        self.time = TimeModule()
        self.metrics = MetricsModule()
        self.dimensions = DimensionsModule()
        self.post_processing = PostProcessingModule()
        self.assembler = AssemblerModule()

    def forward(
        self,
        query: str,
        current_date: Optional[date] = None,
        previous_context: Optional[dict] = None,
        overrides: Optional[dict] = None,
    ) -> Intent:
        overrides = overrides or {}
        logger.info("[DSPy Pipeline] Starting intent extraction pipeline execution")
        if overrides:
            logger.info(f"[DSPy Pipeline] Pipeline received overrides: {overrides}")
        pipeline_start_time = time.monotonic()

        # -------------------------
        # 1. Classify
        # -------------------------
        logger.info("[DSPy Pipeline] [1/8] Executing Classifier")
        step_start = time.monotonic()
        classified_query = self.classifier(query=query)
        logger.info("[DSPy Pipeline] [1/8] Classifier completed in %dms", int((time.monotonic() - step_start) * 1000))
        logger.info("[DSPy Pipeline] [1/8] Output: %s", classified_query.model_dump_json() if hasattr(classified_query, "model_dump_json") else str(classified_query))

        # -------------------------
        # 2. Scope
        # -------------------------
        logger.info("[DSPy Pipeline] [2/8] Executing Scope")
        step_start = time.monotonic()
        scope_result = self.scope(classified_query=classified_query, overrides=overrides)
        logger.info("[DSPy Pipeline] [2/8] Scope completed in %dms", int((time.monotonic() - step_start) * 1000))
        logger.info("[DSPy Pipeline] [2/8] Output: %s", scope_result.model_dump_json() if hasattr(scope_result, "model_dump_json") else str(scope_result))

        # -------------------------
        # 3. Time
        # -------------------------
        logger.info("[DSPy Pipeline] [3/8] Executing Time")
        step_start = time.monotonic()
        time_result = self.time(
            classified_query=classified_query,
            current_date=current_date,
            previous_context=previous_context,
            overrides=overrides,
        )
        logger.info("[DSPy Pipeline] [3/8] Time completed in %dms", int((time.monotonic() - step_start) * 1000))
        logger.info("[DSPy Pipeline] [3/8] Output: %s", time_result.model_dump_json() if hasattr(time_result, "model_dump_json") else str(time_result))

        # -------------------------
        # 4. Metrics
        # -------------------------
        logger.info("[DSPy Pipeline] [4/8] Executing Metrics")
        step_start = time.monotonic()
        metrics_result = self.metrics(
            classified_query=classified_query,
            sales_scope=scope_result.sales_scope,
            overrides=overrides,
        )
        logger.info("[DSPy Pipeline] [4/8] Metrics completed in %dms", int((time.monotonic() - step_start) * 1000))
        logger.info("[DSPy Pipeline] [4/8] Output: %s", metrics_result.model_dump_json() if hasattr(metrics_result, "model_dump_json") else str(metrics_result))

        # -------------------------
        # 5. Dimensions
        # -------------------------
        logger.info("[DSPy Pipeline] [5/8] Executing Dimensions")
        step_start = time.monotonic()
        dimensions_result = self.dimensions(
            classified_query=classified_query,
            sales_scope=scope_result.sales_scope,
            previous_context=previous_context,
            overrides=overrides,
        )
        logger.info("[DSPy Pipeline] [5/8] Dimensions completed in %dms", int((time.monotonic() - step_start) * 1000))
        logger.info("[DSPy Pipeline] [5/8] Output: %s", dimensions_result.model_dump_json() if hasattr(dimensions_result, "model_dump_json") else str(dimensions_result))

        # -------------------------
        # 6. Post Processing
        # -------------------------
        logger.info("[DSPy Pipeline] [6/8] Executing Post Processing")
        step_start = time.monotonic()
        post_processing_result = self.post_processing(
            classified_query=classified_query,
            time_result=time_result,
            dimensions_result=dimensions_result,
        )
        logger.info("[DSPy Pipeline] [6/8] Post Processing completed in %dms", int((time.monotonic() - step_start) * 1000))
        logger.info("[DSPy Pipeline] [6/8] Output: %s", post_processing_result.model_dump_json() if hasattr(post_processing_result, "model_dump_json") else str(post_processing_result))

        # -------------------------
        # 7. Assemble
        # -------------------------
        logger.info("[DSPy Pipeline] [7/8] Executing Assembly")
        step_start = time.monotonic()
        intent = self.assembler.forward(
            classified_query=classified_query,
            scope_result=scope_result,
            time_result=time_result,
            metrics_result=metrics_result,
            dimensions_result=dimensions_result,
            post_processing_result=post_processing_result,
        )
        logger.info("[DSPy Pipeline] [7/8] Assembly completed in %dms", int((time.monotonic() - step_start) * 1000))
        logger.info("[DSPy Pipeline] [7/8] Output: %s", intent.model_dump_json() if hasattr(intent, "model_dump_json") else str(intent))

        # -------------------------
        # 8. Final Validation (CRITICAL)
        # -------------------------
        logger.info("[DSPy Pipeline] [8/8] Executing Final Validation")
        step_start = time.monotonic()
        intent = Intent.model_validate(intent)
        logger.info("[DSPy Pipeline] [8/8] Final Validation completed in %dms", int((time.monotonic() - step_start) * 1000))
        logger.info("[DSPy Pipeline] [8/8] Output: %s", intent.model_dump_json() if hasattr(intent, "model_dump_json") else str(intent))

        logger.info("[DSPy Pipeline] Pipeline execution completed successfully in %dms", int((time.monotonic() - pipeline_start_time) * 1000))
        return intent