"""
Training and optimization module for DSPy Intent Extraction Pipeline.

Following RULE T1: Use partial-credit metric, never exact match
Following RULE O1: Compile pipeline module, never individual agents
Following RULE O2: BootstrapFewShot first, MIPROv2 second
Following RULE O3: Save and load compiled state
Following RULE O4: Python validator runs after every LLM call
"""

import logging
from typing import Dict, Any, List, Optional, Union
from pathlib import Path
import json

import dspy
from dspy.teleprompt import BootstrapFewShotWithRandomSearch
from dspy.teleprompt.gepa.gepa_utils import ScoreWithFeedback
from dspy import Example, Prediction

from .pipeline import IntentExtractionPipeline
from .training_examples import get_training_examples, get_validation_examples
from ..models.intent import Intent
from .gepa_feedback import FEEDBACK_FUNCTIONS

logger = logging.getLogger(__name__)

# =============================================================================
# METRIC FUNCTION (RULE T1)
# =============================================================================

def intent_extraction_metric(gold: Intent, pred: Intent, trace=None) -> float:
    """
    Partial-credit metric for intent extraction evaluation.

    Following RULE T1: Use partial-credit metric, never exact match.
    Field weights assigned based on failure frequency:
    - metrics: 0.20 (high failure mode)
    - group_by: 0.20 (high failure mode)
    - time: 0.20 (high failure mode)
    - sales_scope: 0.15 (medium failure mode)
    - filters: 0.15 (medium failure mode)
    - post_processing: 0.10 (low failure mode)

    Args:
        gold: Ground truth Intent
        pred: Predicted Intent
        trace: DSPy trace (unused)

    Returns:
        float: Score between 0.0 and 1.0
    """
    try:
        if not isinstance(pred, dict):
            pred = pred.model_dump() if hasattr(pred, 'model_dump') else pred

        if not isinstance(gold, dict):
            gold = gold.model_dump() if hasattr(gold, 'model_dump') else gold

        total_score = 0.0

        # Sales scope (0.15 weight)
        if gold.get("sales_scope") == pred.get("sales_scope"):
            total_score += 0.15

        # Metrics (0.20 weight - high failure mode)
        metrics_score = _score_metrics(gold.get("metrics", []), pred.get("metrics", []))
        total_score += metrics_score * 0.20

        # Group by (0.20 weight - high failure mode)
        group_by_score = _score_list_field(gold.get("group_by"), pred.get("group_by"))
        total_score += group_by_score * 0.20

        # Time (0.20 weight - high failure mode)
        time_score = _score_time_spec(gold.get("time"), pred.get("time"))
        total_score += time_score * 0.20

        # Filters (0.15 weight)
        filters_score = _score_filters(gold.get("filters"), pred.get("filters"))
        total_score += filters_score * 0.15

        # Post-processing (0.10 weight - low failure mode)
        post_proc_score = _score_post_processing(
            gold.get("post_processing"), pred.get("post_processing")
        )
        total_score += post_proc_score * 0.10

        return min(1.0, max(0.0, total_score))

    except Exception as e:
        logger.warning(f"Metric evaluation failed: {e}")
        return 0.0


def gepa_intent_extraction_metric(
    gold: Example,
    pred: Prediction,
    trace: Optional[Any] = None,
    pred_name: Optional[str] = None,
    pred_trace: Optional[Any] = None,
) -> Union[float, ScoreWithFeedback]:
    """
    GEPA-compatible metric for intent extraction evaluation.

    This metric supports both module-level and predictor-level scoring with feedback.
    When pred_name is provided, it returns component-specific feedback using the
    specialized feedback functions. Otherwise, it returns the overall intent score.

    Args:
        gold: Gold example with expected outputs
        pred: Predicted output from the pipeline
        trace: Optional trace of program execution
        pred_name: Optional name of specific predictor being evaluated
        pred_trace: Optional trace of specific predictor execution

    Returns:
        float: Overall pipeline score (when pred_name is None)
        ScoreWithFeedback: Component-specific score and feedback (when pred_name provided)
    """
    try:
        # If this is a predictor-level request, use component-specific feedback
        if pred_name and pred_trace:
            return _generate_component_feedback(gold, pred, trace, pred_name, pred_trace)

        # Otherwise, return overall intent extraction score
        return _calculate_overall_intent_score(gold, pred)

    except Exception as e:
        logger.warning(f"GEPA metric evaluation failed: {e}")
        return 0.0


def _generate_component_feedback(
    gold: Example,
    pred: Prediction,
    trace: Optional[Any],
    pred_name: str,
    pred_trace: Optional[Any],
) -> ScoreWithFeedback:
    """Generate component-specific feedback using specialized feedback functions."""

    # Map predictor names to feedback function keys
    predictor_name_mapping = {
        'classifier': 'classifier',
        'scope': 'scope',
        'time': 'time',
        'metrics': 'metrics',
        'dimensions': 'dimensions',
    }

    # Find the component name from the predictor name
    component_name = None
    for key in predictor_name_mapping:
        if key in pred_name.lower():
            component_name = predictor_name_mapping[key]
            break

    if not component_name or component_name not in FEEDBACK_FUNCTIONS:
        return ScoreWithFeedback(
            score=0.0,
            feedback=f"No feedback function available for predictor: {pred_name}"
        )

    # Get the feedback function
    feedback_fn = FEEDBACK_FUNCTIONS[component_name]

    # Extract predictor-specific inputs and outputs from trace
    if pred_trace and len(pred_trace) > 0:
        # Extract the last prediction from the trace (most recent)
        predictor_instance, predictor_inputs, predictor_output = pred_trace[-1]

        # Convert predictor output to dict if needed
        if hasattr(predictor_output, 'model_dump'):
            predictor_output_dict = predictor_output.model_dump()
        elif hasattr(predictor_output, '__dict__'):
            predictor_output_dict = predictor_output.__dict__
        else:
            predictor_output_dict = {}

        # Call the specialized feedback function
        return feedback_fn(
            predictor_output=predictor_output_dict,
            predictor_inputs=predictor_inputs,
            module_inputs=gold,
            module_outputs=pred,
            captured_trace=trace or [],
        )

    return ScoreWithFeedback(
        score=0.0,
        feedback=f"No trace data available for predictor: {pred_name}"
    )


def _calculate_overall_intent_score(gold: Example, pred: Prediction) -> float:
    """Calculate overall intent extraction score using existing metric."""

    # Extract expected outputs from gold example
    gold_outputs = getattr(gold, 'outputs', {})
    if not gold_outputs:
        return 0.0

    # Convert prediction to intent format
    if hasattr(pred, 'model_dump'):
        pred_intent = pred.model_dump()
    elif isinstance(pred, dict):
        pred_intent = pred
    else:
        # Try to extract intent from prediction attributes
        pred_intent = {}
        for attr in ['sales_scope', 'metrics', 'group_by', 'time', 'filters', 'post_processing']:
            if hasattr(pred, attr):
                pred_intent[attr] = getattr(pred, attr)

    # Use the existing intent extraction metric
    return intent_extraction_metric(gold_outputs, pred_intent)


def get_component_performance_breakdown(
    pipeline: IntentExtractionPipeline,
    test_examples: List[Example],
) -> Dict[str, Dict[str, float]]:
    """
    Evaluate pipeline components individually to identify performance bottlenecks.

    Returns a breakdown of performance scores for each component.
    This helps identify which components need the most optimization attention.
    """
    component_scores = {
        'classifier': {'total_score': 0.0, 'count': 0, 'scores': []},
        'scope': {'total_score': 0.0, 'count': 0, 'scores': []},
        'time': {'total_score': 0.0, 'count': 0, 'scores': []},
        'metrics': {'total_score': 0.0, 'count': 0, 'scores': []},
        'dimensions': {'total_score': 0.0, 'count': 0, 'scores': []},
    }

    for example in test_examples:
        try:
            # Run pipeline with trace capture to get component-level outputs
            prediction = pipeline(
                query=example.query,
                previous_context=getattr(example, 'previous_context', None),
                current_date=getattr(example, 'current_date', None)
            )

            # For each component, calculate its individual score
            for component_name in component_scores.keys():
                if component_name in FEEDBACK_FUNCTIONS:
                    # Use GEPA metric in component mode
                    feedback = gepa_intent_extraction_metric(
                        gold=example,
                        pred=prediction,
                        pred_name=component_name,
                        pred_trace=[],  # Simplified for now
                    )

                    if isinstance(feedback, ScoreWithFeedback):
                        score = feedback.score
                    else:
                        score = feedback if isinstance(feedback, (int, float)) else 0.0

                    component_scores[component_name]['scores'].append(score)
                    component_scores[component_name]['total_score'] += score
                    component_scores[component_name]['count'] += 1

        except Exception as e:
            logger.warning(f"Component evaluation failed for example: {e}")
            continue

    # Calculate average scores
    results = {}
    for component, data in component_scores.items():
        if data['count'] > 0:
            avg_score = data['total_score'] / data['count']
            results[component] = {
                'avg_score': avg_score,
                'count': data['count'],
                'scores': data['scores'],
                'min_score': min(data['scores']) if data['scores'] else 0.0,
                'max_score': max(data['scores']) if data['scores'] else 0.0,
            }
        else:
            results[component] = {
                'avg_score': 0.0,
                'count': 0,
                'scores': [],
                'min_score': 0.0,
                'max_score': 0.0,
            }

    return results


def _score_metrics(gold_metrics: List[Dict], pred_metrics: List[Dict]) -> float:
    """Score metrics with partial credit for correct names."""
    if not gold_metrics and not pred_metrics:
        return 1.0
    if not gold_metrics or not pred_metrics:
        return 0.0

    # Extract metric names for comparison
    gold_names = {m.get("name") for m in gold_metrics if m.get("name")}
    pred_names = {m.get("name") for m in pred_metrics if m.get("name")}

    if not gold_names or not pred_names:
        return 0.0

    # Jaccard similarity for metric names
    intersection = len(gold_names & pred_names)
    union = len(gold_names | pred_names)

    return intersection / union if union > 0 else 0.0


def _score_list_field(gold_list: Optional[List[str]], pred_list: Optional[List[str]]) -> float:
    """Score list fields (group_by) with partial credit."""
    if gold_list is None and pred_list is None:
        return 1.0
    if gold_list is None or pred_list is None:
        return 0.0

    gold_set = set(gold_list)
    pred_set = set(pred_list)

    if not gold_set and not pred_set:
        return 1.0
    if not gold_set or not pred_set:
        return 0.0

    # Jaccard similarity
    intersection = len(gold_set & pred_set)
    union = len(gold_set | pred_set)

    return intersection / union


def _score_time_spec(gold_time: Optional[Dict], pred_time: Optional[Dict]) -> float:
    """Score time specification with partial credit."""
    if gold_time is None and pred_time is None:
        return 1.0
    if gold_time is None or pred_time is None:
        return 0.0

    score = 0.0
    fields_scored = 0

    # Window (most important)
    if gold_time.get("window") == pred_time.get("window"):
        score += 0.4
    fields_scored += 1

    # Start/end dates (important for explicit ranges)
    if gold_time.get("start_date") == pred_time.get("start_date"):
        score += 0.2
    if gold_time.get("end_date") == pred_time.get("end_date"):
        score += 0.2
    fields_scored += 2

    # Granularity (important for trends)
    if gold_time.get("granularity") == pred_time.get("granularity"):
        score += 0.2
    fields_scored += 1

    return score


def _score_filters(gold_filters: Optional[List[Dict]], pred_filters: Optional[List[Dict]]) -> float:
    """Score filters with partial credit."""
    if gold_filters is None and pred_filters is None:
        return 1.0
    if gold_filters is None or pred_filters is None:
        return 0.0

    if not gold_filters and not pred_filters:
        return 1.0

    # Simple approach: count matching dimension/value pairs
    gold_pairs = {
        (f.get("dimension"), str(f.get("value")))
        for f in gold_filters if f.get("dimension")
    }
    pred_pairs = {
        (f.get("dimension"), str(f.get("value")))
        for f in pred_filters if f.get("dimension")
    }

    if not gold_pairs and not pred_pairs:
        return 1.0
    if not gold_pairs or not pred_pairs:
        return 0.0

    intersection = len(gold_pairs & pred_pairs)
    union = len(gold_pairs | pred_pairs)

    return intersection / union


def _score_post_processing(gold_post: Optional[Dict], pred_post: Optional[Dict]) -> float:
    """Score post-processing with partial credit."""
    if gold_post is None and pred_post is None:
        return 1.0
    if gold_post is None or pred_post is None:
        return 0.0

    score = 0.0

    # Ranking
    gold_ranking = gold_post.get("ranking")
    pred_ranking = pred_post.get("ranking")

    if gold_ranking is None and pred_ranking is None:
        score += 0.5
    elif gold_ranking and pred_ranking:
        if (gold_ranking.get("enabled") == pred_ranking.get("enabled") and
            gold_ranking.get("order") == pred_ranking.get("order")):
            score += 0.5

    # Comparison/derived metrics (simplified)
    gold_comparison = gold_post.get("comparison", {}).get("type") if gold_post.get("comparison") else None
    pred_comparison = pred_post.get("comparison", {}).get("type") if pred_post.get("comparison") else None

    if gold_comparison == pred_comparison:
        score += 0.3

    gold_derived = gold_post.get("derived_metric")
    pred_derived = pred_post.get("derived_metric")

    if gold_derived == pred_derived:
        score += 0.2

    return min(1.0, score)


# =============================================================================
# COMPILATION AND OPTIMIZATION (RULE O1-O4)
# =============================================================================

class IntentExtractionOptimizer:
    """
    Optimizer for Intent Extraction Pipeline.

    Following RULE O1: Compile pipeline module, never individual agents
    Following RULE O2: BootstrapFewShot first
    Following RULE O3: Save and load compiled state

    Supports both BootstrapFewShot and GEPA optimization methods.
    """

    def __init__(self, pipeline: IntentExtractionPipeline):
        self.pipeline = pipeline
        self.compiled_pipeline = None
        self.optimization_method = None

    def bootstrap_optimize(self,
                          max_bootstrapped_demos: int = 4,
                          metric_threshold: float = 0.75,
                          num_candidate_programs: int = 10) -> IntentExtractionPipeline:
        """
        Optimize pipeline using BootstrapFewShotWithRandomSearch.

        Following RULE O2: BootstrapFewShot first, MIPROv2 second.

        Args:
            max_bootstrapped_demos: Maximum demos per predictor (RULE O2)
            metric_threshold: Only keep near-perfect traces (RULE O2)
            num_candidate_programs: Number of candidate programs to try

        Returns:
            Optimized pipeline
        """
        logger.info("Starting BootstrapFewShot optimization")

        # Get training data
        trainset = get_training_examples()
        logger.info(f"Training with {len(trainset)} examples")

        # Configure optimizer per RULE O2
        optimizer = BootstrapFewShotWithRandomSearch(
            metric=intent_extraction_metric,
            max_bootstrapped_demos=max_bootstrapped_demos,
            metric_threshold=metric_threshold,
            num_candidate_programs=num_candidate_programs
        )

        # Compile pipeline (RULE O1 - compile module, not individual agents)
        logger.info("Compiling pipeline...")
        self.compiled_pipeline = optimizer.compile(
            self.pipeline,
            trainset=trainset
        )

        self.optimization_method = "BootstrapFewShot"
        logger.info("Pipeline optimization completed")
        return self.compiled_pipeline

    def gepa_optimize(self,
                     reflection_lm,
                     auto: str = "medium",
                     max_metric_calls: Optional[int] = None,
                     component_selector: str = "round_robin",
                     use_merge: bool = True,
                     track_stats: bool = True) -> IntentExtractionPipeline:
        """
        Optimize pipeline using GEPA (Generate, Evaluate, Propose, Apply).

        GEPA uses evolutionary optimization with reflection to improve
        individual pipeline components through textual feedback.

        Args:
            reflection_lm: Language model for reflection (e.g., dspy.LM('claude-3-5-sonnet'))
            auto: Budget setting ('light', 'medium', 'heavy')
            max_metric_calls: Override auto budget with specific metric call limit
            component_selector: Strategy for selecting components to optimize
            use_merge: Enable merging of successful program variants
            track_stats: Enable detailed result tracking

        Returns:
            GEPA-optimized pipeline
        """
        try:
            from dspy.teleprompt import GEPA
        except ImportError:
            raise ImportError("GEPA not available. Ensure GEPA library is installed.")

        logger.info("Starting GEPA optimization")

        # Get training and validation data
        trainset = get_training_examples()
        valset = get_validation_examples()
        logger.info(f"Training with {len(trainset)} examples, validating with {len(valset)} examples")

        # Configure GEPA optimizer
        gepa_config = {
            'metric': gepa_intent_extraction_metric,
            'reflection_lm': reflection_lm,
            'component_selector': component_selector,
            'use_merge': use_merge,
            'track_stats': track_stats,
            'failure_score': 0.0,
            'perfect_score': 1.0,
        }

        if max_metric_calls:
            gepa_config['max_metric_calls'] = max_metric_calls
        else:
            gepa_config['auto'] = auto

        optimizer = GEPA(**gepa_config)

        # Compile pipeline with GEPA
        logger.info("Compiling pipeline with GEPA...")
        self.compiled_pipeline = optimizer.compile(
            self.pipeline,
            trainset=trainset,
            valset=valset
        )

        self.optimization_method = "GEPA"
        logger.info("GEPA optimization completed")

        # Log optimization results if available
        if hasattr(self.compiled_pipeline, 'detailed_results'):
            results = self.compiled_pipeline.detailed_results
            logger.info(f"GEPA found {len(results.candidates)} candidates")
            logger.info(f"Best score: {results.val_aggregate_scores[results.best_idx]:.3f}")

        return self.compiled_pipeline

    def hybrid_optimize(self,
                       reflection_lm,
                       bootstrap_first: bool = True,
                       **gepa_kwargs) -> IntentExtractionPipeline:
        """
        Hybrid optimization: BootstrapFewShot followed by GEPA refinement.

        This approach first uses BootstrapFewShot to establish a good baseline,
        then applies GEPA for fine-grained component optimization.

        Args:
            reflection_lm: Language model for GEPA reflection
            bootstrap_first: Whether to run BootstrapFewShot first
            **gepa_kwargs: Additional arguments for GEPA optimization

        Returns:
            Hybrid-optimized pipeline
        """
        logger.info("Starting hybrid optimization (BootstrapFewShot + GEPA)")

        if bootstrap_first:
            logger.info("Phase 1: BootstrapFewShot optimization")
            self.bootstrap_optimize()

            # Use the bootstrap-optimized pipeline as input to GEPA
            pipeline_for_gepa = self.compiled_pipeline
        else:
            pipeline_for_gepa = self.pipeline

        logger.info("Phase 2: GEPA refinement")
        # Temporarily store the bootstrap result
        bootstrap_pipeline = self.compiled_pipeline

        # Reset pipeline for GEPA
        self.pipeline = pipeline_for_gepa
        self.compiled_pipeline = None

        # Run GEPA optimization
        gepa_pipeline = self.gepa_optimize(reflection_lm, **gepa_kwargs)

        self.optimization_method = "Hybrid (BootstrapFewShot + GEPA)"
        logger.info("Hybrid optimization completed")

        return gepa_pipeline

    def evaluate_optimization_methods(self,
                                    reflection_lm,
                                    test_examples: Optional[List[dspy.Example]] = None) -> Dict[str, Any]:
        """
        Compare different optimization methods on the same pipeline.

        Evaluates unoptimized, BootstrapFewShot, GEPA, and hybrid approaches.

        Returns:
            Comparison results with scores for each method
        """
        if test_examples is None:
            test_examples = get_validation_examples()

        logger.info(f"Comparing optimization methods on {len(test_examples)} test examples")

        results = {}

        # 1. Evaluate unoptimized pipeline
        logger.info("Evaluating unoptimized pipeline...")
        results['unoptimized'] = self.evaluate(test_examples)

        # Store original pipeline
        original_pipeline = self.pipeline
        original_compiled = self.compiled_pipeline

        # 2. Evaluate BootstrapFewShot
        logger.info("Evaluating BootstrapFewShot optimization...")
        self.compiled_pipeline = None
        bootstrap_pipeline = self.bootstrap_optimize()
        results['bootstrap'] = self.evaluate(test_examples)

        # 3. Evaluate GEPA
        logger.info("Evaluating GEPA optimization...")
        self.pipeline = original_pipeline
        self.compiled_pipeline = None
        gepa_pipeline = self.gepa_optimize(reflection_lm)
        results['gepa'] = self.evaluate(test_examples)

        # 4. Evaluate Hybrid
        logger.info("Evaluating hybrid optimization...")
        self.pipeline = original_pipeline
        self.compiled_pipeline = None
        hybrid_pipeline = self.hybrid_optimize(reflection_lm)
        results['hybrid'] = self.evaluate(test_examples)

        # Component-level analysis
        logger.info("Analyzing component-level performance...")
        results['component_breakdown'] = {
            'unoptimized': get_component_performance_breakdown(original_pipeline, test_examples[:10]),
            'bootstrap': get_component_performance_breakdown(bootstrap_pipeline, test_examples[:10]),
            'gepa': get_component_performance_breakdown(gepa_pipeline, test_examples[:10]),
            'hybrid': get_component_performance_breakdown(hybrid_pipeline, test_examples[:10]),
        }

        # Calculate improvements
        baseline_score = results['unoptimized']['mean_score']
        results['improvements'] = {
            'bootstrap': results['bootstrap']['mean_score'] - baseline_score,
            'gepa': results['gepa']['mean_score'] - baseline_score,
            'hybrid': results['hybrid']['mean_score'] - baseline_score,
        }

        logger.info("Optimization method comparison completed")
        logger.info(f"Improvements over baseline: {results['improvements']}")

        # Restore state
        self.pipeline = original_pipeline
        self.compiled_pipeline = original_compiled

        return results

    def evaluate(self, test_examples: Optional[List[dspy.Example]] = None) -> Dict[str, float]:
        """Evaluate pipeline on test set."""
        if test_examples is None:
            test_examples = get_validation_examples()

        if not self.compiled_pipeline:
            logger.warning("Pipeline not compiled, using unoptimized version")
            pipeline = self.pipeline
        else:
            pipeline = self.compiled_pipeline

        scores = []
        for example in test_examples:
            try:
                prediction = pipeline(
                    query=example.query,
                    previous_context=example.previous_context,
                    current_date=example.current_date
                )

                # Convert to Intent if needed
                if isinstance(prediction, dict):
                    prediction = Intent(**prediction)

                # Get expected output
                expected = Intent(**example.outputs)

                # Score
                score = intent_extraction_metric(expected, prediction)
                scores.append(score)

            except Exception as e:
                logger.warning(f"Evaluation failed for example: {e}")
                scores.append(0.0)

        return {
            "mean_score": sum(scores) / len(scores) if scores else 0.0,
            "num_examples": len(scores),
            "scores": scores
        }

    def save(self, filepath: str) -> None:
        """Save compiled pipeline state (RULE O3)."""
        if not self.compiled_pipeline:
            raise ValueError("No compiled pipeline to save")

        save_path = Path(filepath)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        self.compiled_pipeline.save(str(save_path))
        logger.info(f"Saved compiled pipeline to {filepath}")

    def load(self, filepath: str) -> IntentExtractionPipeline:
        """Load compiled pipeline state (RULE O3)."""
        load_path = Path(filepath)
        if not load_path.exists():
            raise FileNotFoundError(f"Compiled pipeline not found at {filepath}")

        # Create fresh pipeline instance
        fresh_pipeline = IntentExtractionPipeline()
        fresh_pipeline.load(str(load_path))

        self.compiled_pipeline = fresh_pipeline
        logger.info(f"Loaded compiled pipeline from {filepath}")
        return self.compiled_pipeline


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def run_optimization_experiment(method: str = "bootstrap",
                              save_path: str = "optimized_intent_pipeline.json",
                              reflection_lm = None,
                              **kwargs) -> Dict[str, Any]:
    """
    Run optimization experiment with specified method.

    Args:
        method: Optimization method ('bootstrap', 'gepa', 'hybrid', 'compare')
        save_path: Path to save optimized pipeline
        reflection_lm: Language model for GEPA (required for gepa/hybrid methods)
        **kwargs: Additional arguments for optimization method

    Returns:
        Experiment results including before/after metrics
    """
    logger.info(f"Starting {method} optimization experiment")

    # Initialize pipeline
    pipeline = IntentExtractionPipeline()
    optimizer = IntentExtractionOptimizer(pipeline)

    if method == "compare":
        if not reflection_lm:
            raise ValueError("reflection_lm required for comparison experiment")
        return optimizer.evaluate_optimization_methods(reflection_lm)

    # Evaluate before optimization
    logger.info("Evaluating unoptimized pipeline...")
    before_metrics = optimizer.evaluate()

    # Run specified optimization
    if method == "bootstrap":
        optimized_pipeline = optimizer.bootstrap_optimize(**kwargs)
    elif method == "gepa":
        if not reflection_lm:
            raise ValueError("reflection_lm required for GEPA optimization")
        optimized_pipeline = optimizer.gepa_optimize(reflection_lm, **kwargs)
    elif method == "hybrid":
        if not reflection_lm:
            raise ValueError("reflection_lm required for hybrid optimization")
        optimized_pipeline = optimizer.hybrid_optimize(reflection_lm, **kwargs)
    else:
        raise ValueError(f"Unknown optimization method: {method}")

    # Evaluate after optimization
    logger.info("Evaluating optimized pipeline...")
    after_metrics = optimizer.evaluate()

    # Save optimized pipeline
    optimizer.save(save_path)

    results = {
        "method": method,
        "before_optimization": before_metrics,
        "after_optimization": after_metrics,
        "improvement": after_metrics["mean_score"] - before_metrics["mean_score"],
        "training_examples": len(get_training_examples()),
        "validation_examples": len(get_validation_examples()),
        "saved_to": save_path,
        "optimization_method_used": optimizer.optimization_method
    }

    if method in ["gepa", "hybrid"] and hasattr(optimized_pipeline, 'detailed_results'):
        # Include GEPA-specific results
        gepa_results = optimized_pipeline.detailed_results
        results["gepa_details"] = {
            "candidates_explored": len(gepa_results.candidates),
            "best_score_achieved": gepa_results.val_aggregate_scores[gepa_results.best_idx],
            "total_metric_calls": gepa_results.total_metric_calls,
            "best_candidate_index": gepa_results.best_idx
        }

    logger.info(f"{method.title()} optimization complete. Improvement: {results['improvement']:.3f}")
    return results


def run_gepa_ablation_study(reflection_lm,
                           save_dir: str = "gepa_ablation_results") -> Dict[str, Any]:
    """
    Run ablation study to understand GEPA's component-level impact.

    Tests different component selector strategies and optimization settings.
    """
    logger.info("Starting GEPA ablation study")

    results = {}
    pipeline = IntentExtractionPipeline()

    # Test different component selectors
    selectors = ['round_robin', 'all']
    for selector in selectors:
        logger.info(f"Testing component selector: {selector}")
        optimizer = IntentExtractionOptimizer(pipeline)

        try:
            optimized = optimizer.gepa_optimize(
                reflection_lm=reflection_lm,
                auto="light",  # Use light budget for ablation
                component_selector=selector
            )
            results[f"selector_{selector}"] = optimizer.evaluate()

            # Save this variant
            save_path = f"{save_dir}/gepa_{selector}.json"
            optimizer.save(save_path)

        except Exception as e:
            logger.error(f"Failed to test selector {selector}: {e}")
            results[f"selector_{selector}"] = {"error": str(e)}

    # Test different budgets
    budgets = ['light', 'medium']
    for budget in budgets:
        logger.info(f"Testing budget: {budget}")
        optimizer = IntentExtractionOptimizer(pipeline)

        try:
            optimized = optimizer.gepa_optimize(
                reflection_lm=reflection_lm,
                auto=budget
            )
            results[f"budget_{budget}"] = optimizer.evaluate()

        except Exception as e:
            logger.error(f"Failed to test budget {budget}: {e}")
            results[f"budget_{budget}"] = {"error": str(e)}

    logger.info("GEPA ablation study completed")
    return results