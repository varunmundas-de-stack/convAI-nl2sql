"""
Intent Extractor - DSPy-based intent extraction.

This module provides the DSPy-based intent extraction pipeline
for converting natural language queries into structured intents.

DESIGN PRINCIPLES:
- DSPy-only: No monolithic LLM prompts
- Output is UNTRUSTED by design (semantically unvalidated)
- Hard fail only on TECHNICAL errors (pipeline failures, timeouts)
- Structured clarification support via DSPy agents
"""

import logging
import time
from typing import Any, Optional

from app.dspy_pipeline.config import get_dspy_pipeline
from app.dspy_pipeline.clarification_tool import ClarificationRequired, MultipleClarificationsRequired
from app.services.intent_errors import IntentIncompleteError
from app.models.intent import Intent
from datetime import date

from app.models.qco import QueryContextObject


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _process_clarification_overrides(overrides: dict) -> dict:
    """
    Process clarification overrides to handle sequential term resolution.

    This converts DSPy clarification answers into term-specific mappings
    that allow multiple terms of the same role to be resolved sequentially.

    Example:
        Input overrides might contain clarification metadata:
        {
            "metrics": "net_value",
            "dspy_clarification_request_id": "abc-123",
            "dspy_clarification_term": "sales"  # The specific term being clarified
        }

        Output adds term-specific mapping:
        {
            "metrics": "net_value",
            "resolved_metric_terms": {"sales": "net_value"},
            ...
        }
    """
    if not overrides:
        return overrides

    processed = dict(overrides)

    # Check for DSPy clarification metadata indicating a sequential term resolution
    clarification_request_id = processed.get("dspy_clarification_request_id")
    clarifying_term = processed.get("dspy_clarification_term")

    if clarification_request_id and clarifying_term:
        # This is a clarification answer - convert to term-specific mapping

        # Handle metric clarifications
        if "metrics" in processed:
            resolved_metric_terms = processed.get("resolved_metric_terms", {})
            resolved_metric_terms[clarifying_term] = processed["metrics"]
            processed["resolved_metric_terms"] = resolved_metric_terms

            logger.info(f" [DSPy Integration] Sequential clarification: '{clarifying_term}' -> '{processed['metrics']}'")
            logger.info(f" [DSPy Integration] Current resolved metrics: {resolved_metric_terms}")

        # Handle dimension clarifications
        elif "group_by" in processed:
            resolved_dimension_terms = processed.get("resolved_dimension_terms", {})
            resolved_dimension_terms[clarifying_term] = processed["group_by"]
            processed["resolved_dimension_terms"] = resolved_dimension_terms

            logger.info(f" [DSPy Integration] Sequential clarification: '{clarifying_term}' -> '{processed['group_by']}'")
            logger.info(f" [DSPy Integration] Current resolved dimensions: {resolved_dimension_terms}")

        # Clean up clarification metadata to avoid confusing downstream
        processed.pop("dspy_clarification_request_id", None)
        processed.pop("dspy_clarification_term", None)

    return processed


# =============================================================================
# LOGGING
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS (Technical errors only)
# =============================================================================

class ExtractionError(Exception):
    """Base exception for technical extraction failures."""
    pass


class LLMCallError(ExtractionError):
    """LLM API call failed."""
    pass


class LLMTimeoutError(ExtractionError):
    """LLM call timed out."""
    pass


class JSONParseError(ExtractionError):
    """LLM response was not valid JSON."""
    pass


class EmptyResponseError(ExtractionError):
    """LLM returned empty response."""
    pass


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

# def extract_intent(
#     query: str,
#     previous_qco: Optional[QueryContextObject] = None,
#     prompt_version: Optional[str] = None,
#     use_dspy: Optional[bool] = None,
#     skip_reset_overrides: bool = False,
#     overrides: Optional[dict] = None
# ) -> dict[str, Any]:
#     """
#     Extract intent from natural language query using DSPy pipeline.

#     Args:
#         query: Natural language user query
#         previous_qco: Optional QCO from the previous query in this session
#         prompt_version: Optional prompt version for RLHF (unused in DSPy mode)
#         use_dspy: Ignored - always uses DSPy pipeline
#         skip_reset_overrides: Pass to DSPy pipeline
#         overrides: Pipeline clarification overrides

#     Returns:
#         Raw intent dict (UNTRUSTED, semantically unvalidated)

#     Raises:
#         ExtractionError: Technical failure (pipeline error, timeout)
#         IntentIncompleteError: Clarification required

#     The returned dict is NOT validated against the catalog.
#     Semantic validation happens downstream in intent_validator.
#     """
#     start_time = time.monotonic()

#     # DSPy pipeline is the only extraction method
#     return _extract_intent_dspy(
#         query,
#         previous_qco,
#         start_time,
#         skip_reset_overrides,
#         overrides
#     )


def _handle_compound_query_results(compound_result: dict, start_time: float) -> dict[str, Any]:
    """
    Handle compound query results by converting them to a structured response.

    For compound queries with partial completion, we need to decide how to handle:
    1. Completed sub-queries: Return their results
    2. Pending sub-queries with clarifications: Convert to IntentIncompleteError
    3. Pending sub-queries with errors: Log and potentially fail

    Current strategy: If any sub-query requires clarification, convert the first
    clarification to IntentIncompleteError for the orchestrator to handle.
    """
    duration_ms = int((time.monotonic() - start_time) * 1000)

    completed = compound_result.get("completed_subqueries", [])
    pending = compound_result.get("pending_subqueries", [])

    logger.info(f" [DSPy Integration] Compound query: {len(completed)} completed, {len(pending)} pending")

    # Check for clarifications in pending sub-queries
    clarification_subquery = None
    for subquery in pending:
        if "clarification" in subquery:
            clarification_subquery = subquery
            break

    if clarification_subquery:
        # Convert first clarification to IntentIncompleteError
        clarification = clarification_subquery["clarification"]

        logger.info(f" [DSPy Integration] Sub-query {clarification_subquery['index']} requires clarification")
        logger.info(f" [DSPy Integration] Question: {clarification['question']}")

        partial_intent = {
            "compound_query_state": compound_result,
            "dspy_clarification_request_id": clarification["request_id"],
            "dspy_clarification_options": clarification["options"],
            "dspy_clarification_subquery_index": clarification_subquery["index"]
        }

        raise IntentIncompleteError(
            missing_fields=[clarification["field"]],
            clarification_message=clarification["question"],
            partial_intent=partial_intent,
            allowed_values=[str(opt) for opt in clarification["options"]]
        )

    # No clarifications needed - return compound result as-is
    # This will be a new type of response that the orchestrator needs to handle
    logger.info(f" [DSPy Integration] ✅ Compound query completed in {duration_ms}ms")
    logger.info(f" [DSPy Integration] All {len(completed)} sub-queries completed successfully")

    return compound_result


# =============================================================================
# DSPY INTEGRATION
# =============================================================================

def extract_intent(
    query: str,
    previous_qco: Optional[QueryContextObject],
    skip_reset_overrides: bool = False,
    overrides: Optional[dict] = None
) -> dict[str, Any]:
    """
    Extract intent using DSPy pipeline.

    Returns:
        Raw intent dict compatible with existing pipeline

    Raises:
        ExtractionError: Technical failure
        IntentIncompleteError: Clarification required
    """
    try:
        start_time = time.monotonic()

        logger.info(" [DSPy Integration] ======================================")
        logger.info(" [DSPy Integration] Using DSPy pipeline for intent extraction")
        logger.info(f" [DSPy Integration] Query length: {len(query)} characters")
        logger.info(f" [DSPy Integration] Has previous context: {'Yes' if previous_qco else 'No'}")
        logger.info(" [DSPy Integration] ======================================")

        # Get configured pipeline
        logger.debug(" [DSPy Integration] Loading DSPy pipeline configuration")
        pipeline = get_dspy_pipeline()

        # Format previous context from QCO for LLM prompt
        previous_context_str = previous_qco.to_prompt_context() if previous_qco else ""
        if previous_context_str:
            logger.debug(f" [DSPy Integration] Previous context length: {len(previous_context_str)} characters")

        # Process overrides for sequential clarification handling
        processed_overrides = _process_clarification_overrides(overrides) if overrides else None

        # Call DSPy pipeline - pass both QCO object and string context
        logger.info(" [DSPy Integration] Calling DSPy pipeline...")
        if processed_overrides:
            logger.info(f" [DSPy Integration] Using processed overrides: {processed_overrides}")
        result = pipeline(
            query=query,
            previous_context=previous_qco,  # Pass the QCO object for drill detection
            current_date=date.today().isoformat(),
            overrides=processed_overrides,
        )

        # Check if this is a compound query result
        if isinstance(result, dict) and result.get("type") == "compound_query_results":
            logger.info(" [DSPy Integration] Compound query detected - processing results")
            return _handle_compound_query_results(result, start_time)

        # Single query result - convert to dict format expected by downstream code
        intent_dict = result.model_dump()

        # Log successful extraction
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(" [DSPy Integration] ======================================")
        logger.info(" [DSPy Integration] ✅ DSPy extraction completed successfully!")
        logger.info(f" [DSPy Integration] Duration: {duration_ms}ms")
        logger.info(f" [DSPy Integration] Output scope: {intent_dict.get('sales_scope')}")
        logger.info(f" [DSPy Integration] Output metrics: {len(intent_dict.get('metrics', []))} items")
        if intent_dict.get('group_by'):
            logger.info(f" [DSPy Integration] Output dimensions: {len(intent_dict['group_by'])} items")
        if intent_dict.get('filters'):
            logger.info(f" [DSPy Integration] Output filters: {len(intent_dict['filters'])} items")
        logger.info(" [DSPy Integration] ======================================")

        return intent_dict

    except ClarificationRequired as e:
        # Convert DSPy clarification exception to the format expected by orchestrator
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(" [DSPy Integration] ======================================")
        logger.info(f" [DSPy Integration] Clarification required after {duration_ms}ms")
        logger.info(f" [DSPy Integration] Request ID: {e.clarification.request_id}")
        logger.info(f" [DSPy Integration] Question: {e.clarification.question}")
        logger.info(f" [DSPy Integration] Field: {e.clarification.field}")
        logger.info(f" [DSPy Integration] Options: {len(e.clarification.options)}")
        logger.info(" [DSPy Integration] ======================================")

        # Create compatible IntentIncompleteError
        missing_fields = [e.clarification.field]
        clarification_message = e.clarification.question
        if e.clarification.context:
            clarification_message += f" {e.clarification.context}"

        allowed_values = [str(opt) for opt in e.clarification.options]

        partial_intent = {
            "dspy_clarification_request_id": e.clarification.request_id,
            "dspy_clarification_options": e.clarification.options
        }

        # Convert to IntentIncompleteError format that orchestrator expects
        raise IntentIncompleteError(
            missing_fields=missing_fields,
            clarification_message=clarification_message,
            partial_intent=partial_intent,
            allowed_values=allowed_values
        ) from e

    except MultipleClarificationsRequired as e:
        # Convert DSPy multiple clarifications exception to the format expected by orchestrator
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(" [DSPy Integration] ======================================")
        logger.info(f" [DSPy Integration] Multiple clarifications required after {duration_ms}ms")
        logger.info(f" [DSPy Integration] Number of clarifications: {len(e.clarifications)}")
        for i, clarification in enumerate(e.clarifications):
            logger.info(f" [DSPy Integration] Clarification {i+1}: {clarification.question}")
            logger.info(f" [DSPy Integration]   Request ID: {clarification.request_id}")
            logger.info(f" [DSPy Integration]   Field: {clarification.field}")
            logger.info(f" [DSPy Integration]   Options: {len(clarification.options)}")
        logger.info(" [DSPy Integration] ======================================")

        # For multiple clarifications, we need to collect all fields and create a combined message
        missing_fields = [c.field for c in e.clarifications]
        questions = [c.question for c in e.clarifications]
        clarification_message = "Multiple clarifications needed: " + " | ".join(questions)

        # Collect all options for first-level compatibility
        all_options = []
        for clarification in e.clarifications:
            all_options.extend([str(opt) for opt in clarification.options])

        partial_intent = {
            "dspy_multiple_clarifications": True,
            "dspy_clarifications_data": [
                {
                    "request_id": c.request_id,
                    "field": c.field,
                    "question": c.question,
                    "options": c.options,
                    "context": c.context,
                    "multi_select": c.multi_select
                }
                for c in e.clarifications
            ]
        }

        # Convert to IntentIncompleteError format that orchestrator expects
        raise IntentIncompleteError(
            missing_fields=missing_fields,
            clarification_message=clarification_message,
            partial_intent=partial_intent,
            allowed_values=list(set(all_options))  # Remove duplicates
        ) from e

    except ImportError as e:
        logger.error(" [DSPy Integration] DSPy pipeline import failed")
        logger.error(f" [DSPy Integration] Import error: {e}")
        raise ExtractionError(f"DSPy pipeline not available: {e}") from e

    except IntentIncompleteError:
        # Re-raise IntentIncompleteError as-is (including those from compound query clarifications)
        # This ensures that clarifications from compound queries are handled correctly by the orchestrator
        raise

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error(" [DSPy Integration] ======================================")
        logger.error(f" [DSPy Integration] DSPy extraction failed after {duration_ms}ms")
        logger.error(f" [DSPy Integration] Error: {str(e)}")
        logger.error(" [DSPy Integration] ======================================")
        # Convert to extraction error for consistent error handling
        if "timeout" in str(e).lower():
            raise LLMTimeoutError(f"DSPy pipeline timeout: {e}") from e
        else:
            raise LLMCallError(f"DSPy pipeline error: {e}") from e