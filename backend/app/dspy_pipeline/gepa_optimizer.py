"""
GEPA Optimizer Integration for DSPy Intent Extraction Pipeline.

This module provides the GepaIntentOptimizer class that wraps the existing
IntentExtractionPipeline with GEPA optimization capabilities. It includes
configuration for reflection LM, budget settings, component selection,
and checkpoint/resume functionality for long optimization runs.
"""

import logging
import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import dspy
from dspy import Example, Prediction
from dspy.teleprompt.gepa.gepa_utils import ScoreWithFeedback

from .pipeline import IntentExtractionPipeline
from .training import gepa_intent_extraction_metric, get_component_performance_breakdown
from .training_examples import get_training_examples, get_validation_examples
from .gepa_feedback import FEEDBACK_FUNCTIONS, get_available_components

logger = logging.getLogger(__name__)

# =============================================================================
# GEPA OPTIMIZER CLASS
# =============================================================================

class GepaIntentOptimizer:
    """
    GEPA optimization wrapper for the Intent Extraction Pipeline.

    This class provides a high-level interface for GEPA optimization with:
    - Flexible configuration options
    - Component-specific optimization
    - Checkpoint and resume capabilities
    - Detailed performance analysis
    - Integration with existing training infrastructure
    """

    def __init__(self,
                 pipeline: Optional[IntentExtractionPipeline] = None,
                 reflection_lm: Optional[Any] = None,
                 log_dir: Optional[str] = None):
        """
        Initialize GEPA optimizer.

        Args:
            pipeline: Pipeline to optimize (creates new if None)
            reflection_lm: Language model for reflection (can be set later)
            log_dir: Directory for optimization logs and checkpoints
        """
        self.pipeline = pipeline or IntentExtractionPipeline()
        self.reflection_lm = reflection_lm
        self.optimized_pipeline = None
        self.optimization_results = None

        # Set up logging directory
        if log_dir:
            self.log_dir = Path(log_dir)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_dir = Path(f"gepa_runs/intent_extraction_{timestamp}")

        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Configuration
        self.config = self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default GEPA configuration."""
        return {
            # Budget configuration
            'auto': 'medium',
            'max_metric_calls': None,
            'max_full_evals': None,

            # Reflection configuration
            'reflection_minibatch_size': 3,
            'candidate_selection_strategy': 'pareto',
            'skip_perfect_score': True,
            'add_format_failure_as_feedback': False,
            'component_selector': 'round_robin',

            # Merge configuration
            'use_merge': True,
            'max_merge_invocations': 5,

            # Evaluation configuration
            'num_threads': None,
            'failure_score': 0.0,
            'perfect_score': 1.0,

            # Logging configuration
            'track_stats': True,
            'track_best_outputs': False,
            'use_wandb': False,
            'wandb_api_key': None,
            'wandb_init_kwargs': None,

            # Reproducibility
            'seed': 42,
        }

    def configure(self, **kwargs) -> 'GepaIntentOptimizer':
        """
        Update optimizer configuration.

        Args:
            **kwargs: Configuration parameters to update

        Returns:
            Self for method chaining
        """
        self.config.update(kwargs)
        return self

    def set_reflection_lm(self, reflection_lm: Any) -> 'GepaIntentOptimizer':
        """
        Set the reflection language model.

        Args:
            reflection_lm: Language model for reflection (e.g., dspy.LM('claude-3-5-sonnet'))

        Returns:
            Self for method chaining
        """
        self.reflection_lm = reflection_lm
        return self

    def optimize(self,
                 trainset: Optional[List[Example]] = None,
                 valset: Optional[List[Example]] = None,
                 resume: bool = True) -> IntentExtractionPipeline:
        """
        Run GEPA optimization on the pipeline.

        Args:
            trainset: Training examples (loads default if None)
            valset: Validation examples (loads default if None)
            resume: Whether to resume from checkpoint if available

        Returns:
            Optimized pipeline

        Raises:
            ValueError: If reflection_lm not set or GEPA not available
        """
        if not self.reflection_lm:
            raise ValueError("reflection_lm must be set before optimization")

        try:
            from dspy.teleprompt import GEPA
        except ImportError:
            raise ImportError("GEPA not available. Ensure gepa library is installed.")

        logger.info("Starting GEPA optimization")
        start_time = time.time()

        # Load datasets
        if trainset is None:
            trainset = get_training_examples()
        if valset is None:
            valset = get_validation_examples()

        logger.info(f"Training with {len(trainset)} examples")
        logger.info(f"Validating with {len(valset)} examples")

        # Check for existing checkpoint
        checkpoint_path = self.log_dir / "gepa_checkpoint.json"
        if resume and checkpoint_path.exists():
            logger.info(f"Resuming optimization from checkpoint: {checkpoint_path}")

        # Create GEPA optimizer
        gepa_config = self.config.copy()
        gepa_config.update({
            'metric': gepa_intent_extraction_metric,
            'reflection_lm': self.reflection_lm,
            'log_dir': str(self.log_dir),
        })

        optimizer = GEPA(**gepa_config)

        # Run optimization
        logger.info("Running GEPA optimization...")
        self.optimized_pipeline = optimizer.compile(
            self.pipeline,
            trainset=trainset,
            valset=valset
        )

        # Store results
        if hasattr(self.optimized_pipeline, 'detailed_results'):
            self.optimization_results = self.optimized_pipeline.detailed_results

        optimization_time = time.time() - start_time
        logger.info(f"GEPA optimization completed in {optimization_time:.1f} seconds")

        # Log optimization summary
        self._log_optimization_summary(optimization_time)

        # Save optimized pipeline
        self.save_optimized_pipeline()

        return self.optimized_pipeline

    def optimize_component(self,
                          component_name: str,
                          trainset: Optional[List[Example]] = None,
                          valset: Optional[List[Example]] = None) -> IntentExtractionPipeline:
        """
        Optimize a specific component only.

        Args:
            component_name: Name of component to optimize ('classifier', 'scope', etc.)
            trainset: Training examples
            valset: Validation examples

        Returns:
            Pipeline with optimized component
        """
        if component_name not in get_available_components():
            raise ValueError(f"Unknown component: {component_name}. "
                           f"Available: {get_available_components()}")

        logger.info(f"Optimizing component: {component_name}")

        # Configure for single component optimization
        original_selector = self.config.get('component_selector')
        self.configure(component_selector=component_name)

        try:
            optimized = self.optimize(trainset, valset)
        finally:
            # Restore original selector
            self.configure(component_selector=original_selector)

        return optimized

    def run_ablation_study(self,
                          components: Optional[List[str]] = None,
                          trainset: Optional[List[Example]] = None,
                          valset: Optional[List[Example]] = None) -> Dict[str, Any]:
        """
        Run ablation study to analyze component-level optimization impact.

        Args:
            components: Components to study (all available if None)
            trainset: Training examples
            valset: Validation examples

        Returns:
            Ablation study results
        """
        if components is None:
            components = get_available_components()

        logger.info(f"Running ablation study for components: {components}")

        if trainset is None:
            trainset = get_training_examples()
        if valset is None:
            valset = get_validation_examples()

        results = {
            'baseline': {},
            'components': {},
            'summary': {}
        }

        # Evaluate baseline (unoptimized) pipeline
        logger.info("Evaluating baseline pipeline...")
        baseline_scores = self._evaluate_pipeline(self.pipeline, valset)
        results['baseline'] = baseline_scores

        # Test each component individually
        for component in components:
            logger.info(f"Testing optimization of component: {component}")

            try:
                # Create fresh optimizer for this component
                component_optimizer = GepaIntentOptimizer(
                    pipeline=IntentExtractionPipeline(),
                    reflection_lm=self.reflection_lm,
                    log_dir=str(self.log_dir / f"ablation_{component}")
                )

                # Configure for lighter budget in ablation study
                component_optimizer.configure(
                    auto='light',
                    component_selector=component
                )

                # Optimize and evaluate
                optimized = component_optimizer.optimize(trainset, valset[:20])  # Smaller valset
                scores = self._evaluate_pipeline(optimized, valset[:20])

                results['components'][component] = {
                    'scores': scores,
                    'improvement': scores['mean_score'] - baseline_scores['mean_score']
                }

            except Exception as e:
                logger.error(f"Failed to optimize component {component}: {e}")
                results['components'][component] = {'error': str(e)}

        # Calculate summary statistics
        improvements = [
            comp_results.get('improvement', 0)
            for comp_results in results['components'].values()
            if 'improvement' in comp_results
        ]

        if improvements:
            results['summary'] = {
                'best_component': max(results['components'].keys(),
                                    key=lambda c: results['components'][c].get('improvement', -1)),
                'worst_component': min(results['components'].keys(),
                                     key=lambda c: results['components'][c].get('improvement', 1)),
                'mean_improvement': sum(improvements) / len(improvements),
                'max_improvement': max(improvements),
                'min_improvement': min(improvements)
            }

        # Save ablation results
        self._save_ablation_results(results)

        logger.info("Ablation study completed")
        return results

    def compare_with_bootstrap(self,
                              trainset: Optional[List[Example]] = None,
                              valset: Optional[List[Example]] = None) -> Dict[str, Any]:
        """
        Compare GEPA optimization with BootstrapFewShot.

        Args:
            trainset: Training examples
            valset: Validation examples

        Returns:
            Comparison results
        """
        logger.info("Comparing GEPA with BootstrapFewShot optimization")

        if trainset is None:
            trainset = get_training_examples()
        if valset is None:
            valset = get_validation_examples()

        results = {}

        # Evaluate baseline
        baseline_scores = self._evaluate_pipeline(self.pipeline, valset)
        results['baseline'] = baseline_scores

        # Test BootstrapFewShot
        logger.info("Testing BootstrapFewShot optimization...")
        try:
            from .training import IntentExtractionOptimizer
            bootstrap_optimizer = IntentExtractionOptimizer(IntentExtractionPipeline())
            bootstrap_pipeline = bootstrap_optimizer.bootstrap_optimize()
            bootstrap_scores = self._evaluate_pipeline(bootstrap_pipeline, valset)
            results['bootstrap'] = {
                'scores': bootstrap_scores,
                'improvement': bootstrap_scores['mean_score'] - baseline_scores['mean_score']
            }
        except Exception as e:
            logger.error(f"BootstrapFewShot optimization failed: {e}")
            results['bootstrap'] = {'error': str(e)}

        # Test GEPA
        logger.info("Testing GEPA optimization...")
        try:
            gepa_pipeline = self.optimize(trainset, valset)
            gepa_scores = self._evaluate_pipeline(gepa_pipeline, valset)
            results['gepa'] = {
                'scores': gepa_scores,
                'improvement': gepa_scores['mean_score'] - baseline_scores['mean_score']
            }

            if self.optimization_results:
                results['gepa']['optimization_details'] = {
                    'candidates_explored': len(self.optimization_results.candidates),
                    'best_score': self.optimization_results.val_aggregate_scores[self.optimization_results.best_idx],
                    'metric_calls': self.optimization_results.total_metric_calls
                }

        except Exception as e:
            logger.error(f"GEPA optimization failed: {e}")
            results['gepa'] = {'error': str(e)}

        # Save comparison results
        comparison_path = self.log_dir / "gepa_vs_bootstrap.json"
        with open(comparison_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        logger.info("Comparison completed")
        return results

    def _evaluate_pipeline(self, pipeline: IntentExtractionPipeline, examples: List[Example]) -> Dict[str, Any]:
        """Evaluate pipeline performance on given examples."""
        from .training import intent_extraction_metric, Intent

        scores = []
        for example in examples:
            try:
                prediction = pipeline(
                    query=example.query,
                    current_date=getattr(example, 'current_date', None),
                    previous_context=getattr(example, 'previous_context', None)
                )

                if isinstance(prediction, dict):
                    prediction = Intent(**prediction)

                expected = Intent(**example.outputs)
                score = intent_extraction_metric(expected, prediction)
                scores.append(score)

            except Exception as e:
                logger.warning(f"Evaluation failed for example: {e}")
                scores.append(0.0)

        return {
            'mean_score': sum(scores) / len(scores) if scores else 0.0,
            'num_examples': len(scores),
            'scores': scores,
            'min_score': min(scores) if scores else 0.0,
            'max_score': max(scores) if scores else 0.0
        }

    def _log_optimization_summary(self, optimization_time: float) -> None:
        """Log summary of optimization results."""
        summary = {
            'optimization_time_seconds': optimization_time,
            'configuration': self.config,
            'log_directory': str(self.log_dir)
        }

        if self.optimization_results:
            summary.update({
                'candidates_explored': len(self.optimization_results.candidates),
                'best_candidate_index': self.optimization_results.best_idx,
                'best_score_achieved': self.optimization_results.val_aggregate_scores[self.optimization_results.best_idx],
                'total_metric_calls': self.optimization_results.total_metric_calls,
                'num_full_evaluations': self.optimization_results.num_full_val_evals
            })

        # Save summary
        summary_path = self.log_dir / "optimization_summary.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        logger.info(f"Optimization summary saved to: {summary_path}")

        if self.optimization_results:
            logger.info(f"Explored {len(self.optimization_results.candidates)} candidates")
            logger.info(f"Best score: {self.optimization_results.val_aggregate_scores[self.optimization_results.best_idx]:.3f}")
            logger.info(f"Total metric calls: {self.optimization_results.total_metric_calls}")

    def _save_ablation_results(self, results: Dict[str, Any]) -> None:
        """Save ablation study results."""
        ablation_path = self.log_dir / "ablation_study.json"
        with open(ablation_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Ablation results saved to: {ablation_path}")

    def save_optimized_pipeline(self, path: Optional[str] = None) -> str:
        """
        Save the optimized pipeline.

        Args:
            path: Save path (default: log_dir/optimized_pipeline.pkl)

        Returns:
            Path where pipeline was saved
        """
        if not self.optimized_pipeline:
            raise ValueError("No optimized pipeline to save")

        if path is None:
            path = self.log_dir / "optimized_pipeline.pkl"

        self.optimized_pipeline.save(str(path))
        logger.info(f"Optimized pipeline saved to: {path}")
        return str(path)

    def load_optimized_pipeline(self, path: str) -> IntentExtractionPipeline:
        """
        Load a previously optimized pipeline.

        Args:
            path: Path to saved pipeline

        Returns:
            Loaded pipeline
        """
        pipeline = IntentExtractionPipeline()
        pipeline.load(path)
        self.optimized_pipeline = pipeline
        logger.info(f"Loaded optimized pipeline from: {path}")
        return pipeline

    def get_optimization_status(self) -> Dict[str, Any]:
        """Get current optimization status and results."""
        status = {
            'has_optimized_pipeline': self.optimized_pipeline is not None,
            'configuration': self.config,
            'log_directory': str(self.log_dir),
            'available_components': get_available_components()
        }

        if self.optimization_results:
            status.update({
                'optimization_completed': True,
                'candidates_explored': len(self.optimization_results.candidates),
                'best_score': self.optimization_results.val_aggregate_scores[self.optimization_results.best_idx],
                'total_metric_calls': self.optimization_results.total_metric_calls
            })
        else:
            status['optimization_completed'] = False

        return status

# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_gepa_optimizer(reflection_lm: Any,
                         pipeline: Optional[IntentExtractionPipeline] = None,
                         **config) -> GepaIntentOptimizer:
    """
    Create a GEPA optimizer with standard configuration.

    Args:
        reflection_lm: Language model for reflection
        pipeline: Pipeline to optimize (creates new if None)
        **config: Additional configuration options

    Returns:
        Configured GEPA optimizer
    """
    optimizer = GepaIntentOptimizer(pipeline=pipeline, reflection_lm=reflection_lm)
    if config:
        optimizer.configure(**config)
    return optimizer

def quick_gepa_optimize(reflection_lm: Any,
                       pipeline: Optional[IntentExtractionPipeline] = None) -> IntentExtractionPipeline:
    """
    Quick GEPA optimization with standard settings.

    Args:
        reflection_lm: Language model for reflection
        pipeline: Pipeline to optimize

    Returns:
        Optimized pipeline
    """
    optimizer = create_gepa_optimizer(
        reflection_lm=reflection_lm,
        pipeline=pipeline,
        auto='light',  # Quick optimization
        track_stats=True
    )
    return optimizer.optimize()

def production_gepa_optimize(reflection_lm: Any,
                            pipeline: Optional[IntentExtractionPipeline] = None) -> IntentExtractionPipeline:
    """
    Production-ready GEPA optimization with comprehensive settings.

    Args:
        reflection_lm: Language model for reflection
        pipeline: Pipeline to optimize

    Returns:
        Optimized pipeline
    """
    optimizer = create_gepa_optimizer(
        reflection_lm=reflection_lm,
        pipeline=pipeline,
        auto='heavy',  # Thorough optimization
        track_stats=True,
        track_best_outputs=True,
        use_merge=True
    )
    return optimizer.optimize()