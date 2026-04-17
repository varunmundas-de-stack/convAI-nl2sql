"""
GEPA-Compatible Feedback System for DSPy Intent Extraction Pipeline.

This module provides specialized feedback functions for each pipeline component
that GEPA can use for evolutionary optimization. Each feedback function analyzes:
- Input-output alignment with gold standard
- Common failure patterns
- Contextual appropriateness

Following GEPA protocol, feedback functions return ScoreWithFeedback objects
containing both numerical scores and textual feedback for optimization.
"""

import logging
from typing import Any, Dict, List, Optional, Union
from dspy import Example, Prediction
from dspy.teleprompt.gepa.gepa_utils import ScoreWithFeedback, DSPyTrace

from .schemas import (
    ClassifiedQuery,
    ScopeResult,
    TimeResult,
    MetricsResult,
    DimensionsResult,
    PostProcessingResult,
    Intent,
    CATALOG_METRICS,
    ALL_DIMENSIONS,
    COMMON_DIMENSIONS,
    SECONDARY_ONLY_DIMENSIONS,
    TIME_WINDOWS,
    TIME_GRANULARITIES
)

logger = logging.getLogger(__name__)

# =============================================================================
# UTILITY FUNCTIONS FOR FEEDBACK ANALYSIS
# =============================================================================

def _analyze_classification_accuracy(gold_query: ClassifiedQuery, pred_query: ClassifiedQuery) -> Dict[str, float]:
    """Analyze classification accuracy for different aspects."""
    scores = {}

    # Intent classification accuracy
    scores['intent'] = 1.0 if gold_query.query_intent == pred_query.query_intent else 0.0

    # Term classification accuracy (role assignment)
    gold_terms = {term.term: term.role for term in (gold_query.classified_terms or [])}
    pred_terms = {term.term: term.role for term in (pred_query.classified_terms or [])}

    if gold_terms:
        correct_roles = sum(1 for term, role in pred_terms.items()
                          if term in gold_terms and gold_terms[term] == role)
        scores['term_roles'] = correct_roles / len(gold_terms)
    else:
        scores['term_roles'] = 1.0 if not pred_terms else 0.0

    # Catalog match accuracy
    gold_matches = {term.term: term.catalog_match for term in (gold_query.classified_terms or [])
                   if term.catalog_match}
    pred_matches = {term.term: term.catalog_match for term in (pred_query.classified_terms or [])
                   if term.catalog_match}

    if gold_matches:
        correct_matches = sum(1 for term, match in pred_matches.items()
                            if term in gold_matches and gold_matches[term] == match)
        scores['catalog_matches'] = correct_matches / len(gold_matches)
    else:
        scores['catalog_matches'] = 1.0

    return scores

def _get_common_classification_errors(pred_query: ClassifiedQuery) -> List[str]:
    """Identify common classification errors."""
    errors = []

    # Check for invalid catalog matches
    for term in (pred_query.classified_terms or []):
        if term.catalog_match:
            if (term.role == "METRIC" and term.catalog_match not in CATALOG_METRICS):
                errors.append(f"Invalid metric '{term.catalog_match}' for term '{term.term}'")
            elif (term.role == "DIMENSION" and term.catalog_match not in ALL_DIMENSIONS):
                errors.append(f"Invalid dimension '{term.catalog_match}' for term '{term.term}'")

    # Check for missing critical role assignments
    has_metric = any(term.role == "METRIC" for term in (pred_query.classified_terms or []))
    has_dimension = any(term.role == "DIMENSION" for term in (pred_query.classified_terms or []))

    if pred_query.query_intent in ["DISTRIBUTION", "RANKING"] and not has_dimension:
        errors.append(f"Intent '{pred_query.query_intent}' requires dimension but none classified")

    return errors

def _analyze_scope_accuracy(gold_scope: ScopeResult, pred_scope: ScopeResult) -> float:
    """Analyze scope resolution accuracy."""
    return 1.0 if gold_scope.sales_scope == pred_scope.sales_scope else 0.0

def _analyze_time_accuracy(gold_time: TimeResult, pred_time: TimeResult) -> Dict[str, float]:
    """Analyze time resolution accuracy."""
    scores = {}

    # Time window accuracy
    scores['window'] = 1.0 if gold_time.time_window == pred_time.time_window else 0.0

    # Date range accuracy
    scores['start_date'] = 1.0 if gold_time.start_date == pred_time.start_date else 0.0
    scores['end_date'] = 1.0 if gold_time.end_date == pred_time.end_date else 0.0

    # Granularity accuracy
    scores['granularity'] = 1.0 if gold_time.granularity == pred_time.granularity else 0.0

    return scores

def _analyze_metrics_accuracy(gold_metrics: MetricsResult, pred_metrics: MetricsResult) -> Dict[str, float]:
    """Analyze metrics extraction accuracy."""
    scores = {}

    gold_names = set(m.name for m in (gold_metrics.metrics or []))
    pred_names = set(m.name for m in (pred_metrics.metrics or []))

    if gold_names:
        # Jaccard similarity for metric names
        intersection = len(gold_names & pred_names)
        union = len(gold_names | pred_names)
        scores['metric_selection'] = intersection / union if union > 0 else 0.0

        # Check if all predictions are valid catalog metrics
        invalid_metrics = pred_names - CATALOG_METRICS
        scores['catalog_validity'] = 1.0 if not invalid_metrics else 0.0
    else:
        scores['metric_selection'] = 1.0 if not pred_names else 0.0
        scores['catalog_validity'] = 1.0

    return scores

def _analyze_dimensions_accuracy(gold_dims: DimensionsResult, pred_dims: DimensionsResult,
                                sales_scope: str) -> Dict[str, float]:
    """Analyze dimensions resolution accuracy."""
    scores = {}

    # Group by accuracy
    gold_groupby = set(gold_dims.group_by or [])
    pred_groupby = set(pred_dims.group_by or [])

    if gold_groupby:
        intersection = len(gold_groupby & pred_groupby)
        union = len(gold_groupby | pred_groupby)
        scores['group_by'] = intersection / union if union > 0 else 0.0
    else:
        scores['group_by'] = 1.0 if not pred_groupby else 0.0

    # Scope constraint validation
    if sales_scope == "PRIMARY":
        invalid_dims = pred_groupby & SECONDARY_ONLY_DIMENSIONS
        scores['scope_constraint'] = 1.0 if not invalid_dims else 0.0
    else:
        scores['scope_constraint'] = 1.0

    # Filter accuracy (simplified)
    gold_filters = len(gold_dims.filters or [])
    pred_filters = len(pred_dims.filters or [])
    scores['filter_count'] = 1.0 if gold_filters == pred_filters else 0.0

    return scores

# =============================================================================
# COMPONENT-SPECIFIC FEEDBACK FUNCTIONS
# =============================================================================

def classifier_feedback(
    predictor_output: Dict[str, Any],
    predictor_inputs: Dict[str, Any],
    module_inputs: Example,
    module_outputs: Prediction,
    captured_trace: DSPyTrace,
) -> ScoreWithFeedback:
    """
    Generate feedback for the ClassifierModule.

    Analyzes term classification accuracy, intent detection, and catalog matching.
    """
    try:
        # Extract the classified query from prediction
        pred_query = predictor_output.get('classified_query')
        if isinstance(pred_query, dict):
            pred_query = ClassifiedQuery(**pred_query)

        # Get gold standard from module inputs
        gold_output = getattr(module_inputs, 'outputs', {})
        if isinstance(gold_output, dict) and 'classified_query' in gold_output:
            gold_query = ClassifiedQuery(**gold_output['classified_query'])
        else:
            # Fallback to overall intent if available
            gold_intent = Intent(**gold_output) if gold_output else None
            if gold_intent:
                # Create a simplified ClassifiedQuery for comparison
                gold_query = ClassifiedQuery(
                    original_query=predictor_inputs.get('query', ''),
                    query_intent=getattr(gold_intent, 'intent_type', 'SNAPSHOT'),
                    classified_terms=[],
                    filter_hints=[]
                )
            else:
                return ScoreWithFeedback(
                    score=0.0,
                    feedback="No gold standard available for classifier comparison"
                )

        # Analyze classification accuracy
        accuracy_scores = _analyze_classification_accuracy(gold_query, pred_query)
        common_errors = _get_common_classification_errors(pred_query)

        # Calculate overall score
        overall_score = (
            accuracy_scores['intent'] * 0.4 +
            accuracy_scores['term_roles'] * 0.4 +
            accuracy_scores['catalog_matches'] * 0.2
        )

        # Generate feedback text
        feedback_parts = []

        if accuracy_scores['intent'] < 1.0:
            feedback_parts.append(f"Intent mismatch: predicted '{pred_query.query_intent}' vs expected '{gold_query.query_intent}'")

        if accuracy_scores['term_roles'] < 0.8:
            feedback_parts.append(f"Term role classification needs improvement (accuracy: {accuracy_scores['term_roles']:.2f})")

        if accuracy_scores['catalog_matches'] < 0.8:
            feedback_parts.append(f"Catalog matching accuracy is low (accuracy: {accuracy_scores['catalog_matches']:.2f})")

        if common_errors:
            feedback_parts.append(f"Common errors: {'; '.join(common_errors)}")

        if not feedback_parts:
            feedback_parts.append("Classification is accurate")

        feedback_text = " | ".join(feedback_parts)

        return ScoreWithFeedback(score=overall_score, feedback=feedback_text)

    except Exception as e:
        logger.warning(f"Classifier feedback generation failed: {e}")
        return ScoreWithFeedback(score=0.0, feedback=f"Feedback generation error: {str(e)}")

def scope_feedback(
    predictor_output: Dict[str, Any],
    predictor_inputs: Dict[str, Any],
    module_inputs: Example,
    module_outputs: Prediction,
    captured_trace: DSPyTrace,
) -> ScoreWithFeedback:
    """
    Generate feedback for the ScopeModule.

    Analyzes PRIMARY vs SECONDARY scope detection accuracy.
    """
    try:
        # Extract scope result from prediction
        pred_scope = predictor_output.get('scope_result')
        if isinstance(pred_scope, dict):
            pred_scope = ScopeResult(**pred_scope)

        # Get gold standard
        gold_output = getattr(module_inputs, 'outputs', {})
        if isinstance(gold_output, dict):
            if 'scope_result' in gold_output:
                gold_scope = ScopeResult(**gold_output['scope_result'])
            else:
                # Extract from overall Intent
                intent_data = Intent(**gold_output)
                gold_scope = ScopeResult(sales_scope=intent_data.sales_scope)
        else:
            return ScoreWithFeedback(score=0.0, feedback="No gold standard available for scope comparison")

        # Analyze scope accuracy
        accuracy = _analyze_scope_accuracy(gold_scope, pred_scope)

        # Generate feedback
        if accuracy == 1.0:
            feedback = f"Scope correctly identified as '{pred_scope.sales_scope}'"
        else:
            feedback = f"Scope mismatch: predicted '{pred_scope.sales_scope}' vs expected '{gold_scope.sales_scope}'"

        return ScoreWithFeedback(score=accuracy, feedback=feedback)

    except Exception as e:
        logger.warning(f"Scope feedback generation failed: {e}")
        return ScoreWithFeedback(score=0.0, feedback=f"Feedback generation error: {str(e)}")

def time_feedback(
    predictor_output: Dict[str, Any],
    predictor_inputs: Dict[str, Any],
    module_inputs: Example,
    module_outputs: Prediction,
    captured_trace: DSPyTrace,
) -> ScoreWithFeedback:
    """
    Generate feedback for the TimeModule.

    Analyzes time window parsing, date range extraction, and granularity setting.
    """
    try:
        # Extract time result from prediction
        pred_time = predictor_output.get('time_result')
        if isinstance(pred_time, dict):
            pred_time = TimeResult(**pred_time)

        # Get gold standard
        gold_output = getattr(module_inputs, 'outputs', {})
        if isinstance(gold_output, dict):
            if 'time_result' in gold_output:
                gold_time = TimeResult(**gold_output['time_result'])
            else:
                # Extract from overall Intent
                intent_data = Intent(**gold_output)
                gold_time = TimeResult(
                    time_window=getattr(intent_data.time, 'window', None),
                    start_date=getattr(intent_data.time, 'start_date', None),
                    end_date=getattr(intent_data.time, 'end_date', None),
                    granularity=getattr(intent_data.time, 'granularity', None)
                )
        else:
            return ScoreWithFeedback(score=0.0, feedback="No gold standard available for time comparison")

        # Analyze time accuracy
        accuracy_scores = _analyze_time_accuracy(gold_time, pred_time)

        # Calculate overall score
        overall_score = (
            accuracy_scores['window'] * 0.4 +
            accuracy_scores['start_date'] * 0.2 +
            accuracy_scores['end_date'] * 0.2 +
            accuracy_scores['granularity'] * 0.2
        )

        # Generate feedback
        feedback_parts = []

        if accuracy_scores['window'] < 1.0:
            feedback_parts.append(f"Window mismatch: '{pred_time.time_window}' vs '{gold_time.time_window}'")

        if accuracy_scores['start_date'] < 1.0:
            feedback_parts.append(f"Start date mismatch: '{pred_time.start_date}' vs '{gold_time.start_date}'")

        if accuracy_scores['end_date'] < 1.0:
            feedback_parts.append(f"End date mismatch: '{pred_time.end_date}' vs '{gold_time.end_date}'")

        if accuracy_scores['granularity'] < 1.0:
            feedback_parts.append(f"Granularity mismatch: '{pred_time.granularity}' vs '{gold_time.granularity}'")

        # Check for constraint violations
        if pred_time.time_window and (pred_time.start_date or pred_time.end_date):
            feedback_parts.append("Constraint violation: both time_window and explicit dates set")

        if not feedback_parts:
            feedback_parts.append("Time parsing is accurate")

        feedback_text = " | ".join(feedback_parts)

        return ScoreWithFeedback(score=overall_score, feedback=feedback_text)

    except Exception as e:
        logger.warning(f"Time feedback generation failed: {e}")
        return ScoreWithFeedback(score=0.0, feedback=f"Feedback generation error: {str(e)}")

def metrics_feedback(
    predictor_output: Dict[str, Any],
    predictor_inputs: Dict[str, Any],
    module_inputs: Example,
    module_outputs: Prediction,
    captured_trace: DSPyTrace,
) -> ScoreWithFeedback:
    """
    Generate feedback for the MetricsModule.

    Analyzes metric resolution accuracy and catalog validity.
    """
    try:
        # Extract metrics result from prediction
        pred_metrics = predictor_output.get('metrics_result')
        if isinstance(pred_metrics, dict):
            pred_metrics = MetricsResult(**pred_metrics)

        # Get gold standard
        gold_output = getattr(module_inputs, 'outputs', {})
        if isinstance(gold_output, dict):
            if 'metrics_result' in gold_output:
                gold_metrics = MetricsResult(**gold_output['metrics_result'])
            else:
                # Extract from overall Intent
                intent_data = Intent(**gold_output)
                gold_metrics = MetricsResult(metrics=intent_data.metrics)
        else:
            return ScoreWithFeedback(score=0.0, feedback="No gold standard available for metrics comparison")

        # Analyze metrics accuracy
        accuracy_scores = _analyze_metrics_accuracy(gold_metrics, pred_metrics)

        # Calculate overall score
        overall_score = (
            accuracy_scores['metric_selection'] * 0.8 +
            accuracy_scores['catalog_validity'] * 0.2
        )

        # Generate feedback
        feedback_parts = []

        if accuracy_scores['metric_selection'] < 0.8:
            gold_names = [m.name for m in (gold_metrics.metrics or [])]
            pred_names = [m.name for m in (pred_metrics.metrics or [])]
            feedback_parts.append(f"Metric selection accuracy low: predicted {pred_names} vs expected {gold_names}")

        if accuracy_scores['catalog_validity'] < 1.0:
            invalid_metrics = set(m.name for m in (pred_metrics.metrics or [])) - CATALOG_METRICS
            feedback_parts.append(f"Invalid metrics detected: {list(invalid_metrics)}")

        # Check for missing metrics in queries that should have them
        if not (pred_metrics.metrics or []):
            feedback_parts.append("No metrics extracted - check if query requires metric identification")

        if not feedback_parts:
            feedback_parts.append("Metric extraction is accurate")

        feedback_text = " | ".join(feedback_parts)

        return ScoreWithFeedback(score=overall_score, feedback=feedback_text)

    except Exception as e:
        logger.warning(f"Metrics feedback generation failed: {e}")
        return ScoreWithFeedback(score=0.0, feedback=f"Feedback generation error: {str(e)}")

def dimensions_feedback(
    predictor_output: Dict[str, Any],
    predictor_inputs: Dict[str, Any],
    module_inputs: Example,
    module_outputs: Prediction,
    captured_trace: DSPyTrace,
) -> ScoreWithFeedback:
    """
    Generate feedback for the DimensionsModule.

    Analyzes dimension selection, scope constraints, and filter construction.
    """
    try:
        # Extract dimensions result from prediction
        pred_dims = predictor_output.get('dimensions_result')
        if isinstance(pred_dims, dict):
            pred_dims = DimensionsResult(**pred_dims)

        # Get sales scope from inputs
        sales_scope = predictor_inputs.get('sales_scope', 'SECONDARY')

        # Get gold standard
        gold_output = getattr(module_inputs, 'outputs', {})
        if isinstance(gold_output, dict):
            if 'dimensions_result' in gold_output:
                gold_dims = DimensionsResult(**gold_output['dimensions_result'])
            else:
                # Extract from overall Intent
                intent_data = Intent(**gold_output)
                gold_dims = DimensionsResult(
                    group_by=intent_data.group_by,
                    filters=intent_data.filters
                )
        else:
            return ScoreWithFeedback(score=0.0, feedback="No gold standard available for dimensions comparison")

        # Analyze dimensions accuracy
        accuracy_scores = _analyze_dimensions_accuracy(gold_dims, pred_dims, sales_scope)

        # Calculate overall score
        overall_score = (
            accuracy_scores['group_by'] * 0.5 +
            accuracy_scores['scope_constraint'] * 0.3 +
            accuracy_scores['filter_count'] * 0.2
        )

        # Generate feedback
        feedback_parts = []

        if accuracy_scores['group_by'] < 0.8:
            gold_groupby = gold_dims.group_by or []
            pred_groupby = pred_dims.group_by or []
            feedback_parts.append(f"Group by mismatch: predicted {pred_groupby} vs expected {gold_groupby}")

        if accuracy_scores['scope_constraint'] < 1.0:
            invalid_dims = set(pred_dims.group_by or []) & SECONDARY_ONLY_DIMENSIONS
            feedback_parts.append(f"Scope constraint violated: {list(invalid_dims)} not allowed in {sales_scope}")

        if accuracy_scores['filter_count'] < 1.0:
            gold_filter_count = len(gold_dims.filters or [])
            pred_filter_count = len(pred_dims.filters or [])
            feedback_parts.append(f"Filter count mismatch: {pred_filter_count} vs {gold_filter_count}")

        # Check for dimension limit violations
        if len(pred_dims.group_by or []) > 2:
            feedback_parts.append("Too many dimensions selected (limit: 2)")

        # Check for invalid dimensions
        invalid_dims = set(pred_dims.group_by or []) - ALL_DIMENSIONS
        if invalid_dims:
            feedback_parts.append(f"Invalid dimensions: {list(invalid_dims)}")

        if not feedback_parts:
            feedback_parts.append("Dimension resolution is accurate")

        feedback_text = " | ".join(feedback_parts)

        return ScoreWithFeedback(score=overall_score, feedback=feedback_text)

    except Exception as e:
        logger.warning(f"Dimensions feedback generation failed: {e}")
        return ScoreWithFeedback(score=0.0, feedback=f"Feedback generation error: {str(e)}")

# =============================================================================
# FEEDBACK FUNCTION REGISTRY
# =============================================================================

FEEDBACK_FUNCTIONS = {
    'classifier': classifier_feedback,
    'scope': scope_feedback,
    'time': time_feedback,
    'metrics': metrics_feedback,
    'dimensions': dimensions_feedback,
}

def get_feedback_function(component_name: str):
    """Get the appropriate feedback function for a component."""
    return FEEDBACK_FUNCTIONS.get(component_name)

def get_available_components() -> List[str]:
    """Get list of components that have feedback functions."""
    return list(FEEDBACK_FUNCTIONS.keys())