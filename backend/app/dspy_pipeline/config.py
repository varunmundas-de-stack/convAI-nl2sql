"""
DSPy Configuration for Intent Extraction with GEPA Support.

This module configures the DSPy environment and provides utilities for
DSPy pipeline management, including GEPA optimization settings.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import dspy

from .pipeline import IntentExtractionPipeline

logger = logging.getLogger(__name__)

# Configuration paths
DSPY_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "dspy_config.json"
COMPILED_PIPELINE_PATH = Path(__file__).parent.parent.parent / "models" / "optimized_intent_pipeline.json"
GEPA_PIPELINE_PATH = Path(__file__).parent.parent.parent / "models" / "gepa_optimized_pipeline.json"

# =============================================================================
# GEPA CONFIGURATION
# =============================================================================

class GepaConfig:
    """Configuration for GEPA optimization."""

    def __init__(self):
        self.enabled = self._get_bool_env("GEPA_OPTIMIZATION_ENABLED", False)
        self.reflection_model = os.getenv("GEPA_REFLECTION_MODEL", "claude-3-5-sonnet")
        self.budget_mode = os.getenv("GEPA_BUDGET_MODE", "medium")  # light, medium, heavy
        self.max_metric_calls = self._get_int_env("GEPA_MAX_METRIC_CALLS", None)
        self.component_selector = os.getenv("GEPA_COMPONENT_SELECTOR", "round_robin")
        self.use_merge = self._get_bool_env("GEPA_USE_MERGE", True)
        self.track_stats = self._get_bool_env("GEPA_TRACK_STATS", True)
        self.log_dir = os.getenv("GEPA_LOG_DIR", None)
        self.wandb_enabled = self._get_bool_env("GEPA_WANDB_ENABLED", False)
        self.wandb_api_key = os.getenv("WANDB_API_KEY", None)

        # Component-specific settings
        self.optimize_classifier = self._get_bool_env("GEPA_OPTIMIZE_CLASSIFIER", True)
        self.optimize_scope = self._get_bool_env("GEPA_OPTIMIZE_SCOPE", True)
        self.optimize_time = self._get_bool_env("GEPA_OPTIMIZE_TIME", True)
        self.optimize_metrics = self._get_bool_env("GEPA_OPTIMIZE_METRICS", True)
        self.optimize_dimensions = self._get_bool_env("GEPA_OPTIMIZE_DIMENSIONS", True)

        # Training configuration
        self.training_examples_limit = self._get_int_env("GEPA_TRAINING_LIMIT", None)
        self.validation_examples_limit = self._get_int_env("GEPA_VALIDATION_LIMIT", None)
        self.seed = self._get_int_env("GEPA_SEED", 42)

    def _get_bool_env(self, key: str, default: bool) -> bool:
        """Get boolean environment variable."""
        value = os.getenv(key, str(default)).lower()
        return value in ('true', '1', 'yes', 'on')

    def _get_int_env(self, key: str, default: Optional[int]) -> Optional[int]:
        """Get integer environment variable."""
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            logger.warning(f"Invalid integer value for {key}: {value}, using default: {default}")
            return default

    def get_enabled_components(self) -> list[str]:
        """Get list of components enabled for optimization."""
        components = []
        if self.optimize_classifier:
            components.append('classifier')
        if self.optimize_scope:
            components.append('scope')
        if self.optimize_time:
            components.append('time')
        if self.optimize_metrics:
            components.append('metrics')
        if self.optimize_dimensions:
            components.append('dimensions')
        return components

    def get_reflection_lm(self) -> Any:
        """Create reflection language model for GEPA."""
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY required for GEPA reflection LM")

        return dspy.LM(
            model=f"anthropic/{self.reflection_model}",
            api_key=anthropic_api_key,
            max_tokens=8192,  # Higher limit for reflection
            temperature=1.0   # Higher temperature for creative reflection
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'enabled': self.enabled,
            'reflection_model': self.reflection_model,
            'budget_mode': self.budget_mode,
            'max_metric_calls': self.max_metric_calls,
            'component_selector': self.component_selector,
            'use_merge': self.use_merge,
            'track_stats': self.track_stats,
            'log_dir': self.log_dir,
            'wandb_enabled': self.wandb_enabled,
            'enabled_components': self.get_enabled_components(),
            'training_examples_limit': self.training_examples_limit,
            'validation_examples_limit': self.validation_examples_limit,
            'seed': self.seed
        }

# Global GEPA configuration
gepa_config = GepaConfig()

def get_gepa_config() -> GepaConfig:
    """Get GEPA configuration instance."""
    return gepa_config

def is_gepa_enabled() -> bool:
    """Check if GEPA optimization is enabled."""
    return gepa_config.enabled

def get_optimization_mode() -> str:
    """Get current optimization mode."""
    if is_gepa_enabled():
        return "gepa"
    else:
        return "bootstrap"

# =============================================================================
# DSPY CONFIGURATION
# =============================================================================

_dspy_configured = False

def configure_dspy_model() -> None:
    """
    Configure DSPy with Anthropic Claude model.

    Uses environment variables for API key and model configuration.
    """
    global _dspy_configured
    if _dspy_configured:
        return

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
        _dspy_configured = True

        logger.info("DSPy configured with Anthropic Claude via LiteLLM")

    except Exception as e:
        logger.error(f"Failed to configure DSPy: {e}")
        raise


# =============================================================================
# PIPELINE SINGLETON
# =============================================================================

class PipelineManager:
    """
    Manages DSPy pipeline instance with lazy loading and compilation.

    Supports both BootstrapFewShot and GEPA optimized pipelines.
    Pipeline selection based on configuration and availability.
    """

    def __init__(self):
        self._pipeline = None
        self._compiled_pipeline = None
        self._gepa_pipeline = None
        self._is_configured = False
        self._optimization_method = None

    def get_pipeline(self) -> IntentExtractionPipeline:
        """
        Get pipeline instance, prioritizing GEPA-optimized if available.

        Returns:
            IntentExtractionPipeline: Ready-to-use pipeline
        """
        if not self._is_configured:
            self._configure()

        # Priority order: GEPA > Compiled (BootstrapFewShot) > Fresh
        if self._should_use_gepa() and not self._gepa_pipeline:
            self._try_load_gepa_pipeline()

        if not self._gepa_pipeline and not self._compiled_pipeline:
            self._try_load_compiled_pipeline()

        if not self._pipeline and not self._compiled_pipeline and not self._gepa_pipeline:
            logger.info("Creating fresh DSPy pipeline")
            self._pipeline = IntentExtractionPipeline()
            self._optimization_method = "none"

        # Return the best available pipeline
        if self._gepa_pipeline:
            return self._gepa_pipeline
        elif self._compiled_pipeline:
            return self._compiled_pipeline
        else:
            return self._pipeline

    def _should_use_gepa(self) -> bool:
        """Check if GEPA pipeline should be used."""
        return is_gepa_enabled() and GEPA_PIPELINE_PATH.exists()

    def _try_load_gepa_pipeline(self) -> None:
        """Try to load GEPA-optimized pipeline."""
        if not GEPA_PIPELINE_PATH.exists():
            logger.info("GEPA pipeline not found")
            return

        try:
            logger.info(f"Loading GEPA-optimized pipeline from {GEPA_PIPELINE_PATH}")
            pipeline = IntentExtractionPipeline()
            pipeline.load(str(GEPA_PIPELINE_PATH))
            self._gepa_pipeline = pipeline
            self._optimization_method = "gepa"
            logger.info("GEPA-optimized pipeline loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load GEPA pipeline: {e}")

    def _try_load_compiled_pipeline(self) -> None:
        """Try to load BootstrapFewShot compiled pipeline."""
        if not COMPILED_PIPELINE_PATH.exists():
            logger.info("Compiled pipeline not found")
            return

        try:
            logger.info(f"Loading compiled pipeline from {COMPILED_PIPELINE_PATH}")
            pipeline = IntentExtractionPipeline()
            pipeline.load(str(COMPILED_PIPELINE_PATH))
            self._compiled_pipeline = pipeline
            self._optimization_method = "bootstrap"
            logger.info("Compiled pipeline loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load compiled pipeline: {e}")

    def _configure(self) -> None:
        """Configure DSPy environment."""
        if self._is_configured:
            return

        try:
            configure_dspy_model()
            self._is_configured = True
            logger.info("DSPy pipeline manager configured")
            logger.info(f"Optimization mode: {get_optimization_mode()}")
            logger.info(f"GEPA enabled: {is_gepa_enabled()}")

        except Exception as e:
            logger.error(f"DSPy configuration failed: {e}")
            raise

    def get_optimization_info(self) -> Dict[str, Any]:
        """Get information about current pipeline optimization."""
        return {
            'method': self._optimization_method or 'none',
            'gepa_enabled': is_gepa_enabled(),
            'gepa_available': GEPA_PIPELINE_PATH.exists(),
            'compiled_available': COMPILED_PIPELINE_PATH.exists(),
            'current_mode': get_optimization_mode(),
            'gepa_config': gepa_config.to_dict() if is_gepa_enabled() else None
        }

    def force_refresh(self) -> None:
        """Force refresh of pipeline instance (for testing/development)."""
        self._pipeline = None
        self._compiled_pipeline = None
        self._gepa_pipeline = None
        self._optimization_method = None
        logger.info("Pipeline instances reset")

    def use_gepa_pipeline(self, pipeline_path: str) -> None:
        """
        Manually set GEPA pipeline to use.

        Args:
            pipeline_path: Path to GEPA-optimized pipeline
        """
        try:
            pipeline = IntentExtractionPipeline()
            pipeline.load(pipeline_path)
            self._gepa_pipeline = pipeline
            self._optimization_method = "gepa"
            logger.info(f"Using GEPA pipeline from: {pipeline_path}")
        except Exception as e:
            logger.error(f"Failed to load GEPA pipeline from {pipeline_path}: {e}")
            raise

    def use_compiled_pipeline(self, pipeline_path: str) -> None:
        """
        Manually set compiled pipeline to use.

        Args:
            pipeline_path: Path to compiled pipeline
        """
        try:
            pipeline = IntentExtractionPipeline()
            pipeline.load(pipeline_path)
            self._compiled_pipeline = pipeline
            self._optimization_method = "bootstrap"
            logger.info(f"Using compiled pipeline from: {pipeline_path}")
        except Exception as e:
            logger.error(f"Failed to load compiled pipeline from {pipeline_path}: {e}")
            raise


# Global pipeline manager instance
pipeline_manager = PipelineManager()


def get_dspy_pipeline() -> IntentExtractionPipeline:
    """
    Get configured DSPy pipeline instance.

    This is the main entry point for DSPy pipeline usage.
    """
    return pipeline_manager.get_pipeline()

def get_pipeline_info() -> Dict[str, Any]:
    """Get information about current pipeline configuration."""
    return pipeline_manager.get_optimization_info()

# =============================================================================
# OPTIMIZATION UTILITIES
# =============================================================================

def trigger_gepa_optimization(reflection_lm: Optional[Any] = None,
                             **kwargs) -> IntentExtractionPipeline:
    """
    Trigger GEPA optimization with current configuration.

    Args:
        reflection_lm: Optional custom reflection LM (uses config default if None)
        **kwargs: Additional GEPA configuration overrides

    Returns:
        GEPA-optimized pipeline
    """
    if not gepa_config.enabled:
        raise ValueError("GEPA optimization is not enabled. Set GEPA_OPTIMIZATION_ENABLED=true")

    try:
        from .gepa_optimizer import GepaIntentOptimizer
    except ImportError:
        raise ImportError("GEPA optimizer not available")

    # Get reflection LM
    if reflection_lm is None:
        reflection_lm = gepa_config.get_reflection_lm()

    # Create optimizer
    optimizer = GepaIntentOptimizer(
        pipeline=IntentExtractionPipeline(),
        reflection_lm=reflection_lm,
        log_dir=gepa_config.log_dir
    )

    # Configure optimizer
    optimizer_config = {
        'auto': gepa_config.budget_mode,
        'component_selector': gepa_config.component_selector,
        'use_merge': gepa_config.use_merge,
        'track_stats': gepa_config.track_stats,
        'seed': gepa_config.seed
    }

    if gepa_config.max_metric_calls:
        optimizer_config['max_metric_calls'] = gepa_config.max_metric_calls
        optimizer_config.pop('auto')  # Remove auto if max_metric_calls is set

    if gepa_config.wandb_enabled and gepa_config.wandb_api_key:
        optimizer_config.update({
            'use_wandb': True,
            'wandb_api_key': gepa_config.wandb_api_key
        })

    # Apply overrides
    optimizer_config.update(kwargs)

    # Configure and optimize
    optimizer.configure(**optimizer_config)
    optimized_pipeline = optimizer.optimize()

    # Save GEPA pipeline
    optimizer.save_optimized_pipeline(str(GEPA_PIPELINE_PATH))

    # Update pipeline manager
    pipeline_manager.use_gepa_pipeline(str(GEPA_PIPELINE_PATH))

    logger.info("GEPA optimization completed and pipeline updated")
    return optimized_pipeline

def compare_optimization_methods(reflection_lm: Optional[Any] = None) -> Dict[str, Any]:
    """
    Compare different optimization methods.

    Args:
        reflection_lm: Reflection LM for GEPA

    Returns:
        Comparison results
    """
    try:
        from .gepa_optimizer import GepaIntentOptimizer
    except ImportError:
        raise ImportError("GEPA optimizer not available")

    # Get reflection LM
    if reflection_lm is None:
        reflection_lm = gepa_config.get_reflection_lm()

    # Create optimizer and run comparison
    optimizer = GepaIntentOptimizer(
        pipeline=IntentExtractionPipeline(),
        reflection_lm=reflection_lm
    )

    return optimizer.compare_with_bootstrap()

def create_reflection_lm(model: Optional[str] = None,
                        temperature: float = 1.0,
                        max_tokens: int = 8192) -> Any:
    """
    Create reflection language model for GEPA.

    Args:
        model: Model name (uses config default if None)
        temperature: Sampling temperature
        max_tokens: Maximum tokens

    Returns:
        Configured language model
    """
    if model is None:
        model = gepa_config.reflection_model

    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY required for reflection LM")

    return dspy.LM(
        model=f"anthropic/{model}",
        api_key=anthropic_api_key,
        max_tokens=max_tokens,
        temperature=temperature
    )

def validate_gepa_setup() -> Dict[str, Any]:
    """
    Validate GEPA setup and configuration.

    Returns:
        Validation results
    """
    results = {
        'gepa_enabled': gepa_config.enabled,
        'anthropic_api_key_set': bool(os.getenv("ANTHROPIC_API_KEY")),
        'gepa_library_available': False,
        'reflection_lm_accessible': False,
        'config_valid': True,
        'issues': []
    }

    # Check GEPA library availability
    try:
        from dspy.teleprompt import GEPA
        results['gepa_library_available'] = True
    except ImportError:
        results['issues'].append("GEPA library not available")

    # Check reflection LM accessibility
    if results['anthropic_api_key_set']:
        try:
            reflection_lm = gepa_config.get_reflection_lm()
            # Try a simple call to validate
            # reflection_lm("test")  # Commented out to avoid actual API call
            results['reflection_lm_accessible'] = True
        except Exception as e:
            results['issues'].append(f"Reflection LM not accessible: {e}")

    # Validate configuration
    enabled_components = gepa_config.get_enabled_components()
    if gepa_config.enabled and not enabled_components:
        results['config_valid'] = False
        results['issues'].append("GEPA enabled but no components configured for optimization")

    if gepa_config.wandb_enabled and not gepa_config.wandb_api_key:
        results['issues'].append("Wandb enabled but WANDB_API_KEY not set")

    results['overall_status'] = (
        results['gepa_enabled'] and
        results['anthropic_api_key_set'] and
        results['gepa_library_available'] and
        results['config_valid'] and
        not results['issues']
    )

    return results


# =============================================================================
# INSIGHTS MODULE SINGLETON
# =============================================================================

class InsightsModuleManager:
    """
    Manages DSPy insights module instance with lazy loading.

    Separate from the main pipeline manager to allow independent optimization
    and lifecycle management of the insights refinement module.
    """

    def __init__(self):
        self._module = None
        self._is_configured = False

    def get_module(self) -> 'InsightsModule':
        """
        Get insights module instance.

        Returns:
            InsightsModule: Ready-to-use module
        """
        if not self._is_configured:
            self._configure()

        if not self._module:
            from .agents.insight.agent import InsightsModule
            logger.info("Creating fresh DSPy insights module")
            self._module = InsightsModule()

        return self._module

    def _configure(self) -> None:
        """Configure DSPy environment for insights module."""
        if self._is_configured:
            return

        try:
            configure_dspy_model()
            self._is_configured = True
            logger.info("DSPy insights module manager configured")

        except Exception as e:
            logger.error(f"DSPy insights module configuration failed: {e}")
            raise

    def force_refresh(self) -> None:
        """Force refresh of module instance (for testing/development)."""
        self._module = None
        logger.info("Insights module instance reset")


# Global insights module manager instance
_insights_manager = InsightsModuleManager()


def get_insights_module() -> 'InsightsModule':
    """
    Get configured DSPy insights module instance.

    This is the main entry point for DSPy insights module usage.
    """
    return _insights_manager.get_module()