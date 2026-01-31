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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import anthropic

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# CONFIGURATION (Explicit, loaded from environment)
# =============================================================================

MODEL_ID = os.getenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-5")
TEMPERATURE = os.getenv("MODEL_TEMPERATURE", 0.0) # Deterministic: extraction is parsing, not generation
MAX_TOKENS = os.getenv("MODEL_MAX_TOKENS", 2048) # Sufficient for intent JSON output
TIMEOUT_SECONDS = os.getenv("MODEL_TIMEOUT_SECONDS", 30.0)

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


def _build_prompt(query: str, template: str) -> str:
    """
    Inject runtime values into prompt template.
    
    No conditional logic. No mutations. Pure string substitution.
    Uses simple string replacement instead of .format() to avoid
    conflicts with JSON curly braces in the template.
    """
    # result = template.replace("{catalog}", catalog)
    result = template.replace("{query}", query)
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
    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=TIMEOUT_SECONDS)
    
    attempt = 0
    max_attempts = 2 if retry_once else 1
    last_error: Exception | None = None
    
    while attempt < max_attempts:
        attempt += 1
        try:
            response = client.messages.create(
                model=MODEL_ID,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
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
# SQLITE LOGGING
# =============================================================================

def _init_log_db() -> None:
    """
    Initialize the SQLite logging database.
    
    Creates the logs directory and table if they don't exist.
    """
    # Ensure logs directory exists
    LOG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(LOG_DB_PATH))
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS extraction_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                prompt_hash TEXT,
                raw_response TEXT,
                parsed_intent TEXT,
                error_type TEXT,
                error_message TEXT,
                model_id TEXT,
                duration_ms INTEGER
            )
        """)
        conn.commit()
    finally:
        conn.close()


# def _log_extraction(
#     query: str,
#     prompt_hash: str,
#     raw_response: str | None,
#     parsed_intent: dict[str, Any] | None,
#     error: Exception | None,
#     duration_ms: int
# ) -> None:
#     """
#     Log an extraction attempt to SQLite database.
    
#     Args:
#         query: Original user query
#         prompt_hash: Hash of the full prompt
#         raw_response: Raw LLM response text (or None if failed)
#         parsed_intent: Parsed intent dict (or None if failed)
#         error: Exception if any occurred
#         duration_ms: Duration of the extraction in milliseconds
#     """
#     try:
#         _init_log_db()
        
#         conn = sqlite3.connect(str(LOG_DB_PATH))
#         try:
#             cursor = conn.cursor()
#             cursor.execute(
#                 """
#                 INSERT INTO extraction_logs (
#                     timestamp, query, prompt_hash, raw_response, 
#                     parsed_intent, error_type, error_message, model_id, duration_ms
#                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
#                 """,
#                 (
#                     datetime.now(timezone.utc).isoformat(),
#                     query,
#                     prompt_hash,
#                     raw_response,
#                     json.dumps(parsed_intent) if parsed_intent else None,
#                     type(error).__name__ if error else None,
#                     str(error) if error else None,
#                     MODEL_ID,
#                     duration_ms,
#                 )
#             )
#             conn.commit()
#         finally:
#             conn.close()
#     except Exception as e:
#         # Don't fail extraction due to logging errors
#         logger.warning(f"Failed to log extraction: {e}")


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def extract_intent(query: str) -> dict[str, Any]:
    """
    Extract intent from natural language query.
    
    This is the ONLY public function in this module.
    
    Args:
        query: Natural language user query
        
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
    
    raw_response = None
    intent_dict = None
    error = None
    prompt_hash = None
    
    try:
        # Load external resources
        template = _load_prompt_template()
        # catalog = _load_catalog()
        
        # Build prompt (pure substitution, no logic)
        # prompt = _build_prompt(query=query, catalog=catalog, template=template)
        prompt = _build_prompt(query=query, template=template)
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

        # # Log to JSON file
        # log_file_path = Path(__file__).parent.parent.parent / "logs" / "extraction_logs.json"
        # log_file_path.parent.mkdir(parents=True, exist_ok=True)
        # with open(log_file_path, "a") as f:
        #     json.dump({
        #         "query": query,
        #         "prompt_hash": prompt_hash,
        #         "raw_response": raw_response,
        #         "start_time": start_time,
        #         "duration_ms": int((time.monotonic() - start_time) * 1000),
        #     }, f)
        #     f.write("\n")  # Add newline for JSONL format

        
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
        
    finally:
        # Always log to SQLite, even on error
        duration_ms = int((time.monotonic() - start_time) * 1000)
        # _log_extraction(
        #     query=query,
        #     prompt_hash=prompt_hash or "",
        #     raw_response=raw_response,
        #     parsed_intent=intent_dict,
        #     error=error,
        #     duration_ms=duration_ms,
        # )
