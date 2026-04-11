from typing import Optional, List, Dict, Any, Union
import dspy
import json
import logging
import time
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.utils.tracer import _span_set

logger = logging.getLogger(__name__)
from app.dspy_pipeline.schemas import ScopeResult, ClassifiedQuery
from .signature import ResolveScope
tracer = get_tracer(__name__)

from app.dspy_pipeline.schemas import ScopeResult, ClassifiedQuery
from .signature import ResolveScope
from app.dspy_pipeline.clarification_tool import ClarificationRequired, build_scope_clarification



# =============================================================================
# AGENT 2 — ScopeModule
# =============================================================================

class ScopeModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolveScope)

    def forward(
        self,
        classified_query: ClassifiedQuery,
        overrides: Optional[dict] = None,
    ) -> ScopeResult:
        with tracer.start_as_current_span("dspy.scope") as span:
            scope_terms = [t for t in classified_query.classified_terms if t.role == "SCOPE"]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_scope_terms=len(scope_terms),
                input_explicit_scope=classified_query.explicit_scope or "",
                input_has_overrides=bool(overrides)
            )

            try:
                start_time = time.monotonic()
                overrides = overrides or {}

                # -------------------------
                # 1. Override
                # -------------------------
                if "sales_scope" in overrides:
                    result = ScopeResult(sales_scope=overrides["sales_scope"])
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="override",
                        output_scope=result.sales_scope,
                        output_duration_ms=duration_ms
                    )
                    logger.debug(f"[DSPy Scope] Override used: {result.sales_scope}")
                    return result

                # -------------------------
                # 2. LLM extraction
                # -------------------------
                relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role == "SCOPE"]
                prediction = self.predict(original_query=classified_query.original_query, classified_terms=json.dumps(relevant_terms))
                result: ScopeResult = prediction.scope_result

                # -------------------------
                # 3. Ambiguity / Missing handling
                # -------------------------

                # If LLM couldn't determine scope → clarify
                has_scope_term = any(
                    t.role == "SCOPE"
                    for t in classified_query.classified_terms
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)

                if not has_scope_term:
                    _span_set(span,
                        output_source="clarification_required",
                        output_duration_ms=duration_ms,
                        clarification_field="scope"
                    )
                    logger.debug(f"[DSPy Scope] Clarification required - no scope terms")
                    raise ClarificationRequired(build_scope_clarification())

                _span_set(span,
                    output_source="llm_extraction",
                    output_scope=result.sales_scope,
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )

                logger.debug(f"[DSPy Scope] Completed in {duration_ms}ms | scope={result.sales_scope}")
                return result

            except ClarificationRequired:
                # Re-raise clarifications without logging as errors
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Scope] Error: {e}")
                raise