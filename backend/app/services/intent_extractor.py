"""
Intent Extractor - Pure LLM adapter for intent extraction.

This module is a PARSER ADAPTER between:
- Natural language (unstructured input)
- Structured intent JSON (untrusted output)

DESIGN PRINCIPLES:
- Single responsibility: query + catalog + prompt → raw dict
- Output is UNTRUSTED by design (semantically unvalidated)
- No catalog logic (catalog is opaque text context)
- No business rules (no "trend requires time" logic)
- Hard fail only on TECHNICAL errors (LLM failure, timeout, invalid JSON)
- Prompt is external and immutable (loaded from file, never mutated)
- Explicit model configuration (no SDK defaults)
- Deterministic settings (low temperature for parsing, not generation)
- LLM is treated as replaceable infrastructure

This file does NOT:
- Validate against catalog
- Normalize or default values
- Raise domain errors (unknown metric, invalid dimension)
- Return Pydantic models
- Ask clarifying questions
- Retry with modified prompts
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from app.services.llm_service import call_claude, count_tokens
from app.models.qco import QueryContextObject
import anthropic


# Paths
PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "intent_extraction.txt"
CATALOG_PATH = Path(__file__).parent.parent.parent / "catalog" / "catalog.yaml"
LOG_DB_PATH = Path(__file__).parent.parent.parent / "logs" / "extraction_logs.db"

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
# INTERNAL HELPERS
# =============================================================================

def _load_prompt_template() -> str:
    """Load prompt template from file. Raises if file missing."""
    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Prompt template not found: {PROMPT_TEMPLATE_PATH}")
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


# def _load_catalog() -> str:
#     """Load catalog as raw text. Raises if file missing."""
#     if not CATALOG_PATH.exists():
#         raise FileNotFoundError(f"Catalog not found: {CATALOG_PATH}")
#     return CATALOG_PATH.read_text(encoding="utf-8")


def _compute_prompt_hash(prompt: str) -> str:
    """Compute short hash of prompt for logging/debugging."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def _build_prompt(query: str, template: str, previous_context: str = "") -> str:
    """
    Inject runtime values into prompt template.
    
    No conditional logic. No mutations. Pure string substitution.
    Uses simple string replacement instead of .format() to avoid
    conflicts with JSON curly braces in the template.
    """
    # Get current date in yyyy-mm-dd format
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # Build the previous context block
    if previous_context:
        context_block = f"## PREVIOUS QUERY CONTEXT\n{previous_context}"
    else:
        context_block = ""
    
    # result = template.replace("{catalog}", catalog)
    result = template.replace("{current_date}", current_date)
    result = result.replace("{previous_context}", context_block)
    result = result.replace("{query}", query)
    return result


def _parse_json_response(raw_response: str) -> dict[str, Any]:
    """
    Parse raw LLM response as JSON.
    
    Handles common LLM quirks:
    - Leading/trailing whitespace
    - Markdown code blocks (```json ... ```)
    
    Raises JSONParseError if parsing fails.
    """
    text = raw_response.strip()
    
    # Strip markdown code blocks if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()
    
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise JSONParseError(f"Invalid JSON from LLM: {e}") from e
    
    if not isinstance(parsed, dict):
        raise JSONParseError(f"Expected JSON object, got {type(parsed).__name__}")
    
    return parsed


def _call_llm(prompt: str, *, retry_once: bool = True) -> str:
    """
    Call LLM with explicit configuration.
    
    - Explicit model, temperature, max_tokens
    - Single verbatim retry on failure (no prompt mutation)
    - Returns raw text response
    
    Raises:
        LLMCallError: API call failed
        LLMTimeoutError: Request timed out
        EmptyResponseError: Empty response received
    """
    attempt = 0
    max_attempts = 2 if retry_once else 1
    last_error: Exception | None = None
    
    while attempt < max_attempts:
        attempt += 1
        try:
            response = call_claude(
                prompt=prompt
            )
            try:
                input_token_count = count_tokens(prompt)
                logger.info(f"Input token count: {input_token_count.input_tokens}")
            except Exception as e:
                logger.warning(f"Error counting tokens: {e}")
            
            # Extract text content
            if not response.content:
                raise EmptyResponseError("LLM returned empty content array")
            
            text_block = response.content[0]
            if not hasattr(text_block, "text") or not text_block.text:
                raise EmptyResponseError("LLM returned empty text")

            return text_block.text
            
        except anthropic.APITimeoutError as e:
            last_error = LLMTimeoutError(f"LLM call timed out after {TIMEOUT_SECONDS}s") 
            last_error.__cause__ = e
            logger.warning(f"LLM timeout on attempt {attempt}/{max_attempts}")
            
        except anthropic.APIError as e:
            last_error = LLMCallError(f"LLM API error: {e}")
            last_error.__cause__ = e
            logger.warning(f"LLM API error on attempt {attempt}/{max_attempts}: {e}")
            
        except EmptyResponseError:
            raise
    
    # All retries exhausted
    raise last_error  # type: ignore[misc]


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def extract_intent(query: str, previous_qco: Optional[QueryContextObject] = None, prompt_version: Optional[str] = None, use_dspy: Optional[bool] = None, skip_reset_overrides: bool = False, overrides: Optional[dict] = None) -> dict[str, Any]:
    """
    Extract intent from natural language query.

    This is the ONLY public function in this module.

    Args:
        query: Natural language user query
        previous_qco: Optional QCO from the previous query in this session
        prompt_version: Optional prompt version for RLHF
        use_dspy: Force DSPy mode (overrides environment variable)

    Returns:
        Raw intent dict (UNTRUSTED, semantically unvalidated)

    Raises:
        ExtractionError: Technical failure (LLM error, timeout, invalid JSON)
        FileNotFoundError: Prompt template or catalog missing

    The returned dict is NOT validated against the catalog.
    Semantic validation happens downstream in intent_validator.
    """
    import time
    start_time = time.monotonic()

    # Check if DSPy mode is requested
    should_use_dspy = use_dspy if use_dspy is not None else _should_use_dspy()

    if should_use_dspy:
        return _extract_intent_dspy(query, previous_qco, start_time, skip_reset_overrides, overrides)

    # Continue with monolithic extraction
    raw_response = None
    intent_dict = None
    error = None
    prompt_hash = None
    
    # Format previous context from QCO (empty string if no QCO)
    previous_context = previous_qco.to_prompt_context() if previous_qco else ""
    
    try:
        # Load external resources
        if prompt_version:
            try:
                from app.rlhf.prompt_manager import get_active_prompt
                template = get_active_prompt(prompt_version)
                logger.info(f"Using versioned prompt: {prompt_version}")
            except Exception as e:
                logger.warning(f"Failed to load versioned prompt {prompt_version}, falling back to default: {e}")
                template = _load_prompt_template()
        else:
            template = _load_prompt_template()
        # catalog = _load_catalog()
        
        # Build prompt (pure substitution, no logic)
        # prompt = _build_prompt(query=query, catalog=catalog, template=template)
        prompt = _build_prompt(query=query, template=template, previous_context=previous_context)
        prompt_hash = _compute_prompt_hash(prompt)
        
        # Log raw input
        logger.info(
            "Intent extraction started",
            extra={
                "query": query,
                "prompt_hash": prompt_hash,
            }
        )
    
        # Call LLM
        raw_response = _call_llm(prompt)
        
        # Log raw output
        logger.info(
            "Intent extraction completed",
            extra={
                "query": query,
                "prompt_hash": prompt_hash,
                "raw_response": raw_response,
            }
        )
        
        # Parse JSON (technical validation only)
        intent_dict = _parse_json_response(raw_response)
        
        return intent_dict
        
    except Exception as e:
        error = e
        raise


# =============================================================================
# DSPY INTEGRATION
# =============================================================================

def _should_use_dspy() -> bool:
    """Check if DSPy mode should be used."""
    try:
        from app.dspy_pipeline.config import is_dspy_mode
        return is_dspy_mode()
    except ImportError:
        logger.warning("DSPy pipeline not available, falling back to monolithic")
        return False


def _extract_intent_dspy(query: str, previous_qco: Optional[QueryContextObject], start_time: float, skip_reset_overrides: bool = False, overrides: Optional[dict] = None) -> dict[str, Any]:
    """
    Extract intent using DSPy pipeline.

    Args:
        query: Natural language query
        previous_qco: Previous query context
        start_time: Start time for duration tracking
        overrides: Pipeline clarification overrides

    Returns:
        Raw intent dict compatible with existing pipeline

    Raises:
        ExtractionError: Technical failure
    """
    try:
        from app.dspy_pipeline.config import get_dspy_pipeline
        from app.dspy_pipeline.clarification_tool import ClarificationRequired
        from app.services.intent_errors import IntentIncompleteError
        from app.models.intent import Intent
        from datetime import date

        logger.info("🎯 [DSPy Integration] ======================================")
        logger.info("🎯 [DSPy Integration] Using DSPy pipeline for intent extraction")
        logger.info(f"🎯 [DSPy Integration] Query length: {len(query)} characters")
        logger.info(f"🎯 [DSPy Integration] Has previous context: {'Yes' if previous_qco else 'No'}")
        logger.info("🎯 [DSPy Integration] ======================================")

        # Get configured pipeline
        logger.debug("🎯 [DSPy Integration] Loading DSPy pipeline configuration")
        pipeline = get_dspy_pipeline()

        # Format previous context from QCO
        previous_context = previous_qco.to_prompt_context() if previous_qco else ""
        if previous_context:
            logger.debug(f"🎯 [DSPy Integration] Previous context length: {len(previous_context)} characters")

        # Call DSPy pipeline
        logger.info("🎯 [DSPy Integration] 🚀 Calling DSPy pipeline...")
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
        logger.info("🎯 [DSPy Integration] ======================================")
        logger.info("🎯 [DSPy Integration] ✅ DSPy extraction completed successfully!")
        logger.info(f"🎯 [DSPy Integration] Duration: {duration_ms}ms")
        logger.info(f"🎯 [DSPy Integration] Output scope: {intent_dict.get('sales_scope')}")
        logger.info(f"🎯 [DSPy Integration] Output metrics: {len(intent_dict.get('metrics', []))} items")
        if intent_dict.get('group_by'):
            logger.info(f"🎯 [DSPy Integration] Output dimensions: {len(intent_dict['group_by'])} items")
        if intent_dict.get('filters'):
            logger.info(f"🎯 [DSPy Integration] Output filters: {len(intent_dict['filters'])} items")
        logger.info("🎯 [DSPy Integration] ======================================")

        return intent_dict

    except ClarificationRequired as e:
        # Convert DSPy clarification exception to the format expected by orchestrator
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info("🎯 [DSPy Integration] ======================================")
        logger.info(f"🎯 [DSPy Integration] 🤔 Clarification required after {duration_ms}ms")
        logger.info(f"🎯 [DSPy Integration] Request ID: {e.clarification.request_id}")
        logger.info(f"🎯 [DSPy Integration] Question: {e.clarification.question}")
        logger.info(f"🎯 [DSPy Integration] Field: {e.clarification.field}")
        logger.info(f"🎯 [DSPy Integration] Options: {len(e.clarification.options)}")
        logger.info("🎯 [DSPy Integration] ======================================")

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
        logger.error("🎯 [DSPy Integration] ❌ DSPy pipeline import failed")
        logger.error(f"🎯 [DSPy Integration] Import error: {e}")
        raise ExtractionError(f"DSPy pipeline not available: {e}") from e

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("🎯 [DSPy Integration] ======================================")
        logger.error(f"🎯 [DSPy Integration] ❌ DSPy extraction failed after {duration_ms}ms")
        logger.error(f"🎯 [DSPy Integration] Error: {str(e)}")
        logger.error("🎯 [DSPy Integration] ======================================")
        # Convert to extraction error for consistent error handling
        if "timeout" in str(e).lower():
            raise LLMTimeoutError(f"DSPy pipeline timeout: {e}") from e
        else:
            raise LLMCallError(f"DSPy pipeline error: {e}") from e
