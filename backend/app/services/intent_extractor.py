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
from app.dspy_pipeline.clarification_tool import ClarificationRequired
from app.services.intent_errors import IntentIncompleteError
from app.models.intent import Intent
from datetime import date

from app.models.qco import QueryContextObject


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

        # Format previous context from QCO
        previous_context = previous_qco.to_prompt_context() if previous_qco else ""
        if previous_context:
            logger.debug(f" [DSPy Integration] Previous context length: {len(previous_context)} characters")

        # Call DSPy pipeline
        logger.info(" [DSPy Integration] Calling DSPy pipeline...")
        if overrides:
            logger.info(f" [DSPy Integration] Using overrides: {overrides}")
        intent_result: Intent = pipeline(
            query=query,
            previous_context=previous_context,
            current_date=date.today().isoformat(),
            overrides=overrides,
        )

        # Convert to dict format expected by downstream code
        intent_dict = intent_result.model_dump()

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

    except ImportError as e:
        logger.error(" [DSPy Integration] DSPy pipeline import failed")
        logger.error(f" [DSPy Integration] Import error: {e}")
        raise ExtractionError(f"DSPy pipeline not available: {e}") from e

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