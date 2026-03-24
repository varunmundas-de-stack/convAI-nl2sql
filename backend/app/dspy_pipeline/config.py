"""
DSPy Configuration for Intent Extraction.

This module configures the DSPy environment and provides utilities for
switching between monolithic and modular pipelines.
"""

import os
import logging
from typing import Optional
from pathlib import Path

import dspy

from .pipeline import IntentExtractionPipeline

logger = logging.getLogger(__name__)

# Configuration paths
DSPY_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "dspy_config.json"
COMPILED_PIPELINE_PATH = Path(__file__).parent.parent.parent / "models" / "optimized_intent_pipeline.json"

# =============================================================================
# DSPY CONFIGURATION
# =============================================================================

def configure_dspy_model() -> None:
    """
    Configure DSPy with Anthropic Claude model.

    Uses environment variables for API key and model configuration.
    """
    # Get Anthropic API key
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    # Configure DSPy with Claude using LiteLLM
    try:
        # Use LiteLLM to connect DSPy with Anthropic Claude
        import dspy

        # Get model from environment or use default
        model_id = os.getenv("ANTHROPIC_MODEL_ID", "claude-haiku-4-5")

        # Configure DSPy with Anthropic Claude via LiteLLM
        # LiteLLM handles the Anthropic API integration
        lm = dspy.LM(
            model=f"anthropic/{model_id}",  # Use anthropic/ prefix for LiteLLM
            api_key=anthropic_api_key,
            max_tokens=4096,
            temperature=0.1  # Low temperature for structured output
        )

        dspy.configure(lm=lm)

        logger.info("DSPy configured with Anthropic Claude via LiteLLM")

    except Exception as e:
        logger.error(f"Failed to configure DSPy: {e}")
        raise


def get_pipeline_mode() -> str:
    """
    Get the current pipeline mode from environment variable.

    Returns:
        str: "monolithic" or "dspy"
    """
    # Check multiple possible environment variables
    if os.getenv("USE_DSPY", "false").lower() == "true":
        return "dspy"
    elif os.getenv("INTENT_EXTRACTION_MODE", "monolithic").lower() == "dspy":
        return "dspy"
    else:
        return "monolithic"


def is_dspy_mode() -> bool:
    """Check if DSPy mode is enabled."""
    return get_pipeline_mode() == "dspy"


# =============================================================================
# PIPELINE SINGLETON
# =============================================================================

class PipelineManager:
    """
    Manages DSPy pipeline instance with lazy loading and compilation.

    Ensures single pipeline instance is reused across requests for efficiency.
    """

    def __init__(self):
        self._pipeline = None
        self._compiled_pipeline = None
        self._is_configured = False

    def get_pipeline(self) -> IntentExtractionPipeline:
        """
        Get pipeline instance, creating and loading compiled state if needed.

        Returns:
            IntentExtractionPipeline: Ready-to-use pipeline
        """
        if not self._is_configured:
            self._configure()

        # Check if we have a compiled pipeline to load
        if not self._compiled_pipeline and COMPILED_PIPELINE_PATH.exists():
            try:
                self._load_compiled_pipeline()
            except Exception as e:
                logger.warning(f"Failed to load compiled pipeline: {e}")
                # Fall back to uncompiled pipeline

        # Create fresh pipeline if needed
        if not self._pipeline and not self._compiled_pipeline:
            logger.info("Creating fresh DSPy pipeline")
            self._pipeline = IntentExtractionPipeline()

        return self._compiled_pipeline if self._compiled_pipeline else self._pipeline

    def _configure(self) -> None:
        """Configure DSPy environment."""
        if self._is_configured:
            return

        try:
            configure_dspy_model()
            self._is_configured = True
            logger.info("DSPy pipeline manager configured")

        except Exception as e:
            logger.error(f"DSPy configuration failed: {e}")
            raise

    def _load_compiled_pipeline(self) -> None:
        """Load compiled pipeline from disk."""
        logger.info(f"Loading compiled pipeline from {COMPILED_PIPELINE_PATH}")

        pipeline = IntentExtractionPipeline()
        pipeline.load(str(COMPILED_PIPELINE_PATH))

        self._compiled_pipeline = pipeline
        logger.info("Compiled pipeline loaded successfully")

    def force_refresh(self) -> None:
        """Force refresh of pipeline instance (for testing/development)."""
        self._pipeline = None
        self._compiled_pipeline = None
        logger.info("Pipeline instances reset")


# Global pipeline manager instance
pipeline_manager = PipelineManager()


def get_dspy_pipeline() -> IntentExtractionPipeline:
    """
    Get configured DSPy pipeline instance.

    This is the main entry point for DSPy pipeline usage.
    """
    return pipeline_manager.get_pipeline()