"""
Training and optimization module for DSPy Intent Extraction Pipeline.

Following RULE T1: Use partial-credit metric, never exact match
Following RULE O1: Compile pipeline module, never individual agents
Following RULE O2: BootstrapFewShot first, MIPROv2 second
Following RULE O3: Save and load compiled state
Following RULE O4: Python validator runs after every LLM call
"""

import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
import json

import dspy
from dspy.teleprompt import BootstrapFewShotWithRandomSearch

from .pipeline import IntentExtractionPipeline
from .training_examples import get_training_examples, get_validation_examples
from ..models.intent import Intent

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
    """

    def __init__(self, pipeline: IntentExtractionPipeline):
        self.pipeline = pipeline
        self.compiled_pipeline = None

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

        logger.info("Pipeline optimization completed")
        return self.compiled_pipeline

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

def run_optimization_experiment(save_path: str = "optimized_intent_pipeline.json") -> Dict[str, Any]:
    """
    Run full optimization experiment.

    Returns experiment results including before/after metrics.
    """
    logger.info("Starting intent extraction optimization experiment")

    # Initialize pipeline
    pipeline = IntentExtractionPipeline()
    optimizer = IntentExtractionOptimizer(pipeline)

    # Evaluate before optimization
    logger.info("Evaluating unoptimized pipeline...")
    before_metrics = optimizer.evaluate()

    # Optimize
    logger.info("Running optimization...")
    optimized_pipeline = optimizer.bootstrap_optimize()

    # Evaluate after optimization
    logger.info("Evaluating optimized pipeline...")
    after_metrics = optimizer.evaluate()

    # Save optimized pipeline
    optimizer.save(save_path)

    results = {
        "before_optimization": before_metrics,
        "after_optimization": after_metrics,
        "improvement": after_metrics["mean_score"] - before_metrics["mean_score"],
        "training_examples": len(get_training_examples()),
        "validation_examples": len(get_validation_examples()),
        "saved_to": save_path
    }

    logger.info(f"Optimization complete. Improvement: {results['improvement']:.3f}")
    return results