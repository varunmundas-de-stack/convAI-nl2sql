from typing import Optional, List, Dict, Any, Union
import dspy
import json
import logging
import time
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.utils.tracer import _span_set

logger = logging.getLogger(__name__)
from app.dspy_pipeline.schemas import DecomposedQuery
from .signature import DecomposeQuery
tracer = get_tracer(__name__)



from opentelemetry.trace import Status, StatusCode

from app.utils.tracer import get_tracer
from app.dspy_pipeline.schemas.agent_outputs import DecomposedQuery
from .signature import DecomposeQuery

class QueryDecomposerModule(dspy.Module):
    """
    Decomposes compound queries into independent analytical sub-queries.

    This is the first agent in the pipeline and determines if a query
    contains multiple independent intents that should be processed separately.
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(DecomposeQuery)

    def forward(self, query: str, previous_context=None, overrides=None) -> DecomposedQuery:
        with tracer.start_as_current_span("dspy.decomposer") as span:
            _span_set(span,
                input_query=query,
                input_has_context=previous_context is not None,
                input_has_overrides=bool(overrides)
            )

            try:
                start_time = time.monotonic()

                context_str = ""
                if previous_context:
                    # Handle different context types
                    try:
                        if hasattr(previous_context, 'to_decomposer_context'):
                            # It's a QCO object
                            context_str = previous_context.to_decomposer_context()
                        elif isinstance(previous_context, dict):
                            # It's a dict, convert to QCO
                            from app.models.qco import QueryContextObject
                            qco = QueryContextObject(**previous_context)
                            context_str = qco.to_decomposer_context()
                        else:
                            # It's already a string
                            context_str = str(previous_context)
                    except Exception:
                        # Fallback to JSON if conversion fails
                        context_str = json.dumps(previous_context) if isinstance(previous_context, dict) else str(previous_context)

                # Inject resolved terms into context to prevent re-asking clarifications
                if overrides:
                    resolved_terms_context = ""
                    for key, value in overrides.items():
                        if "resolved_" in key and "terms" in key:
                            # Extract term mappings from resolved terms
                            if isinstance(value, dict):
                                term_type = key.replace("resolved_", "").replace("_terms", "")
                                for original_term, resolved_value in value.items():
                                    resolved_terms_context += f"\nPreviously resolved: '{original_term}' means '{resolved_value}'"

                    if resolved_terms_context:
                        context_str += f"\n\nResolved Terms:{resolved_terms_context}"
                        logger.debug(f"[DSPy Decomposer] Added resolved terms context: {resolved_terms_context}")

                prediction = self.predict(query=query, session_context=context_str)
                result = prediction.decomposed_query

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_is_compound=result.is_compound,
                    output_subquery_count=len(result.sub_queries),
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )

                logger.debug(f"[DSPy Decomposer] Completed in {duration_ms}ms | compound={result.is_compound} | subqueries={len(result.sub_queries)}")
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Decomposer] Error: {e}")
                raise

