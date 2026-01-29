"""
Intent Service - Orchestration layer for intent handling.

This is the CONTROLLER that orchestrates the intent pipeline:
1. Accept user query
2. Call intent_extractor (LLM extraction)
3. Call intent_validator (semantic validation)
4. Return validated intent or structured error

DESIGN PRINCIPLES:
- Single entry point for intent handling
- Clean control flow with explicit error handling
- No LLM details leak to callers
- Easy to test (clear dependencies)
- Centralized error transformation

This module does NOT:
- Contain LLM logic (that's in intent_extractor)
- Contain validation logic (that's in intent_validator)
- Contain catalog logic (that's in catalog_manager)
"""

from dataclasses import dataclass
from typing import Any, Optional
import logging

from app.models.intent import Intent
from app.services.intent_extractor import (
    extract_intent,
    ExtractionError,
    LLMCallError,
    LLMTimeoutError,
    JSONParseError,
    EmptyResponseError,
)
from app.services.intent_validator import IntentValidator
from app.services.intent_errors import IntentValidationError
from app.services.catalog_manager import CatalogManager


# =============================================================================
# LOGGING
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT TYPES
# =============================================================================

@dataclass(frozen=True)
class IntentResult:
    """
    Result of intent processing.
    
    Either success (intent is set) or failure (error is set).
    Never both. Never neither.
    """
    success: bool
    intent: Optional[Intent] = None
    error: Optional[dict[str, Any]] = None
    
    def __post_init__(self):
        if self.success and self.intent is None:
            raise ValueError("Success result must have intent")
        if not self.success and self.error is None:
            raise ValueError("Failure result must have error")


def _success(intent: Intent) -> IntentResult:
    """Create a success result."""
    return IntentResult(success=True, intent=intent, error=None)


def _failure(
    error_code: str,
    error_type: str,
    message: str,
    **metadata: Any
) -> IntentResult:
    """Create a failure result with structured error."""
    error_dict = {
        "error_code": error_code,
        "error_type": error_type,
        "message": message,
        **metadata
    }
    return IntentResult(success=False, intent=None, error=error_dict)


# =============================================================================
# SERVICE CLASS
# =============================================================================

class IntentService:
    """
    Orchestrates intent extraction and validation.
    
    This is the main entry point for processing user queries into
    validated intents. It coordinates:
    
    1. intent_extractor: LLM-based extraction (untrusted output)
    2. intent_validator: Semantic validation against catalog
    
    Usage:
        catalog = CatalogManager("path/to/catalog.yaml")
        service = IntentService(catalog)
        result = service.process_query("total sales by region last month")
        
        if result.success:
            intent = result.intent
        else:
            error = result.error
    """
    
    def __init__(self, catalog: CatalogManager):
        """
        Initialize the intent service.
        
        Args:
            catalog: CatalogManager instance for validation
        """
        self.catalog = catalog
        self.validator = IntentValidator(catalog)
    
    def process_query(self, query: str) -> IntentResult:
        """
        Process a natural language query into a validated intent.
        
        This is the ONLY public method. It orchestrates:
        1. Extract raw intent from LLM
        2. Validate against catalog
        3. Return success or structured error
        
        Args:
            query: Natural language user query
            
        Returns:
            IntentResult with either:
            - success=True, intent=Intent object
            - success=False, error=structured error dict
            
        This method NEVER raises exceptions. All errors are captured
        and returned as IntentResult with success=False.
        """
        logger.info("Processing query", extra={"query": query})
        
        # Step 1: Extract raw intent from LLM
        try:
            raw_intent = extract_intent(query)
        except LLMTimeoutError as e:
            logger.error("LLM timeout during extraction", extra={"query": query, "error": str(e)})
            return _failure(
                error_code="LLM_TIMEOUT",
                error_type="LLMTimeoutError",
                message="The request timed out. Please try again.",
                query=query,
            )
        except LLMCallError as e:
            logger.error("LLM call failed during extraction", extra={"query": query, "error": str(e)})
            return _failure(
                error_code="LLM_ERROR",
                error_type="LLMCallError",
                message="Failed to process your query. Please try again.",
                query=query,
            )
        except JSONParseError as e:
            logger.error("Failed to parse LLM response", extra={"query": query, "error": str(e)})
            return _failure(
                error_code="PARSE_ERROR",
                error_type="JSONParseError",
                message="Failed to understand your query. Please rephrase.",
                query=query,
            )
        except EmptyResponseError as e:
            logger.error("LLM returned empty response", extra={"query": query, "error": str(e)})
            return _failure(
                error_code="EMPTY_RESPONSE",
                error_type="EmptyResponseError",
                message="Failed to process your query. Please try again.",
                query=query,
            )
        except FileNotFoundError as e:
            logger.error("Missing prompt or catalog file", extra={"error": str(e)})
            return _failure(
                error_code="CONFIG_ERROR",
                error_type="ConfigurationError",
                message="System configuration error. Please contact support.",
            )
        except ExtractionError as e:
            # Catch-all for any other extraction errors
            logger.error("Extraction failed", extra={"query": query, "error": str(e)})
            return _failure(
                error_code="EXTRACTION_ERROR",
                error_type="ExtractionError",
                message="Failed to process your query. Please try again.",
                query=query,
            )
        
        logger.debug("Raw intent extracted", extra={"query": query, "raw_intent": raw_intent})
        
        # Step 2: Check for null intent (LLM couldn't understand)
        if raw_intent.get("intent_type") is None and raw_intent.get("metric") is None:
            logger.warning("LLM returned null intent", extra={"query": query, "raw_intent": raw_intent})
            return _failure(
                error_code="UNCLEAR_QUERY",
                error_type="UnclearQueryError",
                message="I couldn't understand your query. Please be more specific about what metric you want to see.",
                query=query,
                raw_intent=raw_intent,
            )
        
        # Step 3: Validate against catalog
        try:
            validated_intent = self.validator.validate(raw_intent)
        except IntentValidationError as e:
            logger.warning(
                "Intent validation failed",
                extra={
                    "query": query,
                    "raw_intent": raw_intent,
                    "error_code": e.ERROR_CODE.value if e.ERROR_CODE else "UNKNOWN",
                    "error": str(e),
                }
            )
            return _failure(**e.to_dict(), query=query, raw_intent=raw_intent)
        except Exception as e:
            # Unexpected validation error
            logger.exception("Unexpected validation error", extra={"query": query, "raw_intent": raw_intent})
            return _failure(
                error_code="VALIDATION_ERROR",
                error_type="ValidationError",
                message="Failed to validate your query. Please try again.",
                query=query,
            )
        
        logger.info(
            "Query processed successfully",
            extra={
                "query": query,
                "intent_type": validated_intent.intent_type,
                "metric": validated_intent.metric,
            }
        )
        
        return _success(validated_intent)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def process_query(query: str, catalog: CatalogManager) -> IntentResult:
    """
    Convenience function to process a query.
    
    Creates an IntentService and processes the query in one call.
    
    Args:
        query: Natural language user query
        catalog: CatalogManager instance
        
    Returns:
        IntentResult with success/failure
        
    Example:
        >>> catalog = CatalogManager("path/to/catalog.yaml")
        >>> result = process_query("total sales by region", catalog)
        >>> if result.success:
        ...     print(result.intent.metric)
        ... else:
        ...     print(result.error["message"])
    """
    service = IntentService(catalog)
    return service.process_query(query)
