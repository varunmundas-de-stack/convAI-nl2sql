from typing import Optional, List, Dict, Any, Union
import dspy
import json
import logging
import time
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.utils.tracer import _span_set

logger = logging.getLogger(__name__)
from app.dspy_pipeline.schemas import ClassifiedQuery, CATALOG_METRICS, ALL_DIMENSIONS
from .signature import ClassifyQuery
tracer = get_tracer(__name__)


# =============================================================================
# AGENT 1 — ClassifierModule
# =============================================================================
class ClassifierModule(dspy.Module):
    """
    Classifies each term in a natural-language query and determines query intent.

    Inputs  : raw query string
    Outputs : ClassifiedQuery (typed Pydantic model)
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ClassifyQuery)

    def forward(self, query: str, session_context=None) -> ClassifiedQuery:
        """
        Run ClassifyQuery signature and return a validated ClassifiedQuery.

        Args:
            query: Raw natural-language query from the user.
            session_context: Previous context from session for better intent determination.

        Returns:
            ClassifiedQuery with classified_terms, query_intent,
            filter_hints, and explicit_scope populated.
        """
        with tracer.start_as_current_span("dspy.classifier") as span:
            _span_set(span, input_query=query, input_has_context=session_context is not None)

            try:
                start_time = time.monotonic()

                # Handle different context types - convert to string for LLM
                context_str = ""
                if session_context:
                    if hasattr(session_context, 'to_prompt_context'):
                        # It's a QCO object
                        context_str = session_context.to_prompt_context()
                    elif isinstance(session_context, dict):
                        context_str = json.dumps(session_context)
                    else:
                        # Already a string
                        context_str = str(session_context)

                prediction = self.predict(query=query, session_context=context_str)
                classified: ClassifiedQuery = prediction.classified_query

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_intent=classified.query_intent,
                    output_terms_count=len(classified.classified_terms or []),
                    output_explicit_scope=classified.explicit_scope or "",
                    output_duration_ms=duration_ms,
                    output_value=classified.model_dump() if hasattr(classified, "model_dump") else str(classified)
                )

                logger.debug(f"[DSPy Classifier] Completed in {duration_ms}ms | intent={classified.query_intent} | terms={len(classified.classified_terms or [])}")

                # Validate catalog matches and retry if invalid ones are found
                classified = self._validate_and_retry_catalog_matches(classified, query, context_str, span)

                # No alias resolution — downstream modules handle ambiguity
                return classified

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Classifier] Error: {e}")
                raise

    def _validate_and_retry_catalog_matches(self, classified: ClassifiedQuery, query: str, context_str: str, span) -> ClassifiedQuery:
        """Validate catalog matches and retry classifier if invalid matches are found."""
        invalid_matches = []

        for term in classified.classified_terms or []:
            if term.catalog_match:
                # Validate metric matches
                if term.role == "METRIC" and term.catalog_match not in CATALOG_METRICS:
                    invalid_matches.append(f"'{term.term}' -> '{term.catalog_match}' (invalid metric)")
                # Validate dimension matches
                elif term.role == "DIMENSION" and term.catalog_match not in ALL_DIMENSIONS:
                    invalid_matches.append(f"'{term.term}' -> '{term.catalog_match}' (invalid dimension)")

        if invalid_matches:
            logger.warning(f"[DSPy Classifier] Invalid catalog matches found: {invalid_matches}")

            # Build feedback for retry
            feedback = (
                f"VALIDATION ERROR: Invalid catalog matches detected:\n"
                + "\n".join(f"- {match}" for match in invalid_matches) +
                f"\n\nValid metrics: {sorted(CATALOG_METRICS)}\n"
                f"Valid dimensions: {sorted(ALL_DIMENSIONS)}\n\n"
                f"Instructions:\n"
                f"- DO NOT guess catalog_match for terms not in the valid lists\n"
                f"- Set catalog_match=null for ambiguous terms like 'product', 'sales', 'region'\n"
                f"- Only use exact matches from the valid lists above\n\n"
                f"Please reclassify with correct catalog matches:"
            )

            try:
                logger.info(f"[DSPy Classifier] Retrying classification with validation feedback")

                # Add feedback to context
                retry_context = f"{context_str}\n\nFEEDBACK FROM PREVIOUS ATTEMPT:\n{feedback}"

                # Retry the prediction
                retry_prediction = self.predict(query=query, session_context=retry_context)
                retry_classified: ClassifiedQuery = retry_prediction.classified_query

                # Log the retry attempt
                logger.info(f"[DSPy Classifier] Retry completed | intent={retry_classified.query_intent}")

                # Validate the retry result
                retry_invalid = []
                for term in retry_classified.classified_terms or []:
                    if term.catalog_match:
                        if term.role == "METRIC" and term.catalog_match not in CATALOG_METRICS:
                            retry_invalid.append(f"'{term.term}' -> '{term.catalog_match}' (invalid metric)")
                        elif term.role == "DIMENSION" and term.catalog_match not in ALL_DIMENSIONS:
                            retry_invalid.append(f"'{term.term}' -> '{term.catalog_match}' (invalid dimension)")

                if retry_invalid:
                    logger.error(f"[DSPy Classifier] Retry still has invalid matches: {retry_invalid}, using original result with corrections")
                    # Fix invalid matches by setting them to null
                    for term in classified.classified_terms or []:
                        if term.catalog_match:
                            if ((term.role == "METRIC" and term.catalog_match not in CATALOG_METRICS) or
                                (term.role == "DIMENSION" and term.catalog_match not in ALL_DIMENSIONS)):
                                logger.info(f"[DSPy Classifier] Correcting invalid catalog_match: {term.term}.catalog_match = null")
                                term.catalog_match = None
                    return classified
                else:
                    logger.info(f"[DSPy Classifier] Retry successful, using retry result")
                    _span_set(span, retry_successful=True)
                    return retry_classified

            except Exception as retry_error:
                logger.error(f"[DSPy Classifier] Retry failed: {retry_error}, fixing original result")
                # Fix invalid matches by setting them to null
                for term in classified.classified_terms or []:
                    if term.catalog_match:
                        if ((term.role == "METRIC" and term.catalog_match not in CATALOG_METRICS) or
                            (term.role == "DIMENSION" and term.catalog_match not in ALL_DIMENSIONS)):
                            logger.info(f"[DSPy Classifier] Correcting invalid catalog_match: {term.term}.catalog_match = null")
                            term.catalog_match = None
                return classified

        return classified
