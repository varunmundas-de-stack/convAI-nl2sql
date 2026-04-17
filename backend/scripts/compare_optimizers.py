#!/usr/bin/env python3
"""
Optimizer Comparison Script for DSPy Intent Extraction Pipeline.

This script provides comprehensive comparison between different optimization
methods (BootstrapFewShot vs GEPA vs hybrid approaches) with detailed
evaluation results and performance analysis.

Usage:
    python compare_optimizers.py --methods bootstrap gepa hybrid
    python compare_optimizers.py --evaluation-size 50 --output detailed_comparison.json
    python compare_optimizers.py --component-analysis --methods gepa hybrid
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Any

# Add the backend directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import dspy
from app.dspy_pipeline.config import configure_dspy_model, create_reflection_lm
from app.dspy_pipeline.pipeline import IntentExtractionPipeline
from app.dspy_pipeline.training import IntentExtractionOptimizer, get_component_performance_breakdown
from app.dspy_pipeline.training_examples import get_training_examples, get_validation_examples
from app.dspy_pipeline.gepa_optimizer import GepaIntentOptimizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# COMPARISON METHODS
# =============================================================================

class OptimizerComparison:
    """Class to manage comprehensive optimizer comparison."""

    def __init__(self,
                 reflection_lm: Any,
                 evaluation_size: int = 50,
                 seed: int = 42):
        self.reflection_lm = reflection_lm
        self.evaluation_size = evaluation_size
        self.seed = seed
        self.results = {}

    def run_comparison(self, methods: List[str]) -> Dict[str, Any]:
        """
        Run comparison between specified optimization methods.

        Args:
            methods: List of methods to compare ('baseline', 'bootstrap', 'gepa', 'hybrid')

        Returns:
            Comprehensive comparison results
        """
        logger.info(f"Running comparison for methods: {methods}")

        # Get datasets
        trainset = get_training_examples()
        valset = get_validation_examples()

        # Limit evaluation size for faster comparison
        if len(valset) > self.evaluation_size:
            valset = valset[:self.evaluation_size]
            logger.info(f"Limited evaluation to {self.evaluation_size} examples")

        results = {
            'comparison_info': {
                'methods_tested': methods,
                'training_examples': len(trainset),
                'evaluation_examples': len(valset),
                'seed': self.seed,
                'timestamp': time.time()
            },
            'method_results': {},
            'performance_analysis': {},
            'component_analysis': {},
            'summary': {}
        }

        # Run each method
        for method in methods:
            logger.info(f"Testing method: {method}")
            try:
                method_result = self._run_single_method(method, trainset, valset)
                results['method_results'][method] = method_result
            except Exception as e:
                logger.error(f"Method {method} failed: {e}")
                results['method_results'][method] = {'error': str(e)}

        # Analyze results
        results['performance_analysis'] = self._analyze_performance(results['method_results'])
        results['component_analysis'] = self._analyze_components(results['method_results'], valset)
        results['summary'] = self._generate_summary(results)

        self.results = results
        return results

    def _run_single_method(self,
                          method: str,
                          trainset: List,
                          valset: List) -> Dict[str, Any]:
        """Run a single optimization method."""
        start_time = time.time()

        if method == 'baseline':
            # Unoptimized pipeline
            pipeline = IntentExtractionPipeline()
            scores = self._evaluate_pipeline(pipeline, valset)
            method_time = time.time() - start_time

            return {
                'optimization_time': 0.0,  # No optimization
                'evaluation_time': method_time,
                'scores': scores,
                'pipeline_type': 'unoptimized'
            }

        elif method == 'bootstrap':
            # BootstrapFewShot optimization
            optimizer = IntentExtractionOptimizer(IntentExtractionPipeline())
            optimized = optimizer.bootstrap_optimize(
                max_bootstrapped_demos=3,  # Lighter for comparison
                num_candidate_programs=5
            )

            optimization_time = time.time() - start_time
            eval_start = time.time()
            scores = self._evaluate_pipeline(optimized, valset)
            eval_time = time.time() - eval_start

            return {
                'optimization_time': optimization_time,
                'evaluation_time': eval_time,
                'scores': scores,
                'pipeline_type': 'bootstrap_optimized',
                'optimization_method': optimizer.optimization_method
            }

        elif method == 'gepa':
            # GEPA optimization
            optimizer = GepaIntentOptimizer(
                pipeline=IntentExtractionPipeline(),
                reflection_lm=self.reflection_lm
            )

            optimizer.configure(
                auto='light',  # Lighter for comparison
                track_stats=True,
                seed=self.seed
            )

            optimized = optimizer.optimize(trainset, valset)
            optimization_time = time.time() - start_time

            eval_start = time.time()
            scores = self._evaluate_pipeline(optimized, valset)
            eval_time = time.time() - eval_start

            result = {
                'optimization_time': optimization_time,
                'evaluation_time': eval_time,
                'scores': scores,
                'pipeline_type': 'gepa_optimized',
                'optimization_status': optimizer.get_optimization_status()
            }

            # Add GEPA-specific details if available
            if hasattr(optimized, 'detailed_results'):
                gepa_details = optimized.detailed_results
                result['gepa_details'] = {
                    'candidates_explored': len(gepa_details.candidates),
                    'best_score': gepa_details.val_aggregate_scores[gepa_details.best_idx],
                    'metric_calls': gepa_details.total_metric_calls
                }

            return result

        elif method == 'hybrid':
            # Hybrid optimization (Bootstrap + GEPA)
            # First run BootstrapFewShot
            bootstrap_optimizer = IntentExtractionOptimizer(IntentExtractionPipeline())
            bootstrap_pipeline = bootstrap_optimizer.bootstrap_optimize(
                max_bootstrapped_demos=2,  # Very light for speed
                num_candidate_programs=3
            )

            # Then run GEPA on the bootstrap result
            gepa_optimizer = GepaIntentOptimizer(
                pipeline=bootstrap_pipeline,
                reflection_lm=self.reflection_lm
            )

            gepa_optimizer.configure(
                auto='light',
                seed=self.seed
            )

            final_pipeline = gepa_optimizer.optimize(trainset, valset)
            optimization_time = time.time() - start_time

            eval_start = time.time()
            scores = self._evaluate_pipeline(final_pipeline, valset)
            eval_time = time.time() - eval_start

            return {
                'optimization_time': optimization_time,
                'evaluation_time': eval_time,
                'scores': scores,
                'pipeline_type': 'hybrid_optimized',
                'optimization_methods': ['bootstrap', 'gepa']
            }

        else:
            raise ValueError(f"Unknown method: {method}")

    def _evaluate_pipeline(self, pipeline: IntentExtractionPipeline, examples: List) -> Dict[str, Any]:
        """Evaluate pipeline performance."""
        from app.dspy_pipeline.training import intent_extraction_metric
        from app.models.intent import Intent

        scores = []
        error_count = 0

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
                logger.debug(f"Evaluation error: {e}")
                scores.append(0.0)
                error_count += 1

        return {
            'mean_score': sum(scores) / len(scores) if scores else 0.0,
            'median_score': sorted(scores)[len(scores) // 2] if scores else 0.0,
            'min_score': min(scores) if scores else 0.0,
            'max_score': max(scores) if scores else 0.0,
            'std_dev': self._calculate_std_dev(scores),
            'num_examples': len(scores),
            'error_count': error_count,
            'error_rate': error_count / len(examples) if examples else 0.0,
            'scores': scores
        }

    def _calculate_std_dev(self, scores: List[float]) -> float:
        """Calculate standard deviation of scores."""
        if len(scores) < 2:
            return 0.0

        mean = sum(scores) / len(scores)
        variance = sum((x - mean) ** 2 for x in scores) / len(scores)
        return variance ** 0.5

    def _analyze_performance(self, method_results: Dict[str, Dict]) -> Dict[str, Any]:
        """Analyze performance across methods."""
        analysis = {
            'score_comparison': {},
            'optimization_time_comparison': {},
            'improvements': {},
            'ranking': []
        }

        # Get baseline score for improvement calculation
        baseline_score = 0.0
        if 'baseline' in method_results:
            baseline_score = method_results['baseline'].get('scores', {}).get('mean_score', 0.0)

        # Compare scores and times
        for method, results in method_results.items():
            if 'scores' in results:
                score = results['scores']['mean_score']
                analysis['score_comparison'][method] = score

                if baseline_score > 0:
                    improvement = score - baseline_score
                    analysis['improvements'][method] = improvement

            if 'optimization_time' in results:
                analysis['optimization_time_comparison'][method] = results['optimization_time']

        # Rank methods by performance
        ranking_data = [
            (method, score)
            for method, score in analysis['score_comparison'].items()
        ]
        ranking_data.sort(key=lambda x: x[1], reverse=True)
        analysis['ranking'] = [{'method': method, 'score': score} for method, score in ranking_data]

        return analysis

    def _analyze_components(self, method_results: Dict[str, Dict], valset: List) -> Dict[str, Any]:
        """Analyze component-level performance for each method."""
        component_analysis = {}

        # Only analyze methods that succeeded
        successful_methods = {
            method: results for method, results in method_results.items()
            if 'error' not in results and 'pipeline_type' in results
        }

        # For computational efficiency, limit component analysis
        component_valset = valset[:10] if len(valset) > 10 else valset

        for method, results in successful_methods.items():
            try:
                # Note: This would require pipeline instances to be stored
                # For now, we'll skip detailed component analysis
                component_analysis[method] = {
                    'note': 'Component analysis requires pipeline instances',
                    'available': False
                }
            except Exception as e:
                logger.debug(f"Component analysis failed for {method}: {e}")
                component_analysis[method] = {'error': str(e)}

        return component_analysis

    def _generate_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary of comparison results."""
        method_results = results['method_results']
        performance = results['performance_analysis']

        summary = {
            'total_methods_tested': len(method_results),
            'successful_methods': len([r for r in method_results.values() if 'error' not in r]),
            'failed_methods': [m for m, r in method_results.items() if 'error' in r]
        }

        if performance['ranking']:
            best_method = performance['ranking'][0]
            summary['best_method'] = best_method['method']
            summary['best_score'] = best_method['score']

            if len(performance['ranking']) > 1:
                worst_method = performance['ranking'][-1]
                summary['score_range'] = best_method['score'] - worst_method['score']

        # Time analysis
        times = performance.get('optimization_time_comparison', {})
        if times:
            summary['fastest_optimization'] = min(times, key=times.get)
            summary['slowest_optimization'] = max(times, key=times.get)

        # Improvement analysis
        improvements = performance.get('improvements', {})
        if improvements:
            summary['best_improvement'] = max(improvements, key=improvements.get)
            summary['max_improvement_value'] = max(improvements.values())

        return summary

# =============================================================================
# DETAILED ANALYSIS FUNCTIONS
# =============================================================================

def run_statistical_analysis(comparison_results: Dict[str, Any]) -> Dict[str, Any]:
    """Run statistical analysis on comparison results."""
    method_results = comparison_results['method_results']
    statistical_analysis = {}

    # Collect all scores for statistical tests
    method_scores = {}
    for method, results in method_results.items():
        if 'scores' in results and 'scores' in results['scores']:
            method_scores[method] = results['scores']['scores']

    # Calculate pairwise comparisons (simplified)
    comparisons = {}
    methods = list(method_scores.keys())

    for i, method1 in enumerate(methods):
        for method2 in methods[i+1:]:
            scores1 = method_scores[method1]
            scores2 = method_scores[method2]

            # Simple mean difference test
            mean1 = sum(scores1) / len(scores1) if scores1 else 0
            mean2 = sum(scores2) / len(scores2) if scores2 else 0

            comparisons[f"{method1}_vs_{method2}"] = {
                'mean_difference': mean2 - mean1,
                'method1_mean': mean1,
                'method2_mean': mean2,
                'better_method': method1 if mean1 > mean2 else method2
            }

    statistical_analysis['pairwise_comparisons'] = comparisons
    return statistical_analysis

def generate_detailed_report(comparison_results: Dict[str, Any], output_file: str):
    """Generate a detailed report with recommendations."""
    report = {
        'executive_summary': _generate_executive_summary(comparison_results),
        'detailed_results': comparison_results,
        'recommendations': _generate_recommendations(comparison_results),
        'statistical_analysis': run_statistical_analysis(comparison_results)
    }

    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"Detailed report saved to: {output_file}")

def _generate_executive_summary(results: Dict[str, Any]) -> Dict[str, Any]:
    """Generate executive summary of results."""
    summary = results.get('summary', {})
    performance = results.get('performance_analysis', {})

    executive_summary = {
        'key_findings': [],
        'performance_highlights': {},
        'time_efficiency': {},
        'recommendations_preview': []
    }

    # Key findings
    if summary.get('best_method'):
        best_score = summary.get('best_score', 0)
        executive_summary['key_findings'].append(
            f"Best performing method: {summary['best_method']} (score: {best_score:.3f})"
        )

    if summary.get('max_improvement_value', 0) > 0:
        executive_summary['key_findings'].append(
            f"Maximum improvement over baseline: {summary['max_improvement_value']:.3f}"
        )

    # Performance highlights
    if performance.get('score_comparison'):
        executive_summary['performance_highlights'] = performance['score_comparison']

    # Time efficiency
    if performance.get('optimization_time_comparison'):
        executive_summary['time_efficiency'] = performance['optimization_time_comparison']

    return executive_summary

def _generate_recommendations(results: Dict[str, Any]) -> List[str]:
    """Generate recommendations based on results."""
    recommendations = []

    summary = results.get('summary', {})
    performance = results.get('performance_analysis', {})

    # Performance-based recommendations
    if summary.get('best_method'):
        best_method = summary['best_method']
        best_score = summary.get('best_score', 0)

        if best_method == 'gepa' and best_score > 0.8:
            recommendations.append(
                "GEPA optimization shows strong performance. Consider using GEPA "
                "for production optimization with heavier budget settings."
            )
        elif best_method == 'hybrid':
            recommendations.append(
                "Hybrid approach (BootstrapFewShot + GEPA) provides best results. "
                "Recommend using hybrid optimization for maximum performance."
            )
        elif best_method == 'bootstrap':
            recommendations.append(
                "BootstrapFewShot optimization is sufficient for current needs. "
                "Consider GEPA if higher performance is required."
            )

    # Time-based recommendations
    times = performance.get('optimization_time_comparison', {})
    if times:
        fastest = min(times, key=times.get)
        if fastest == 'bootstrap' and times['bootstrap'] < times.get('gepa', float('inf')) / 2:
            recommendations.append(
                "BootstrapFewShot is significantly faster. Use for rapid prototyping "
                "and development cycles."
            )

    # Improvement-based recommendations
    improvements = performance.get('improvements', {})
    if improvements:
        max_improvement = max(improvements.values())
        if max_improvement < 0.1:
            recommendations.append(
                "All optimization methods show modest improvements. Consider "
                "collecting more diverse training data or reviewing pipeline architecture."
            )

    return recommendations

# =============================================================================
# MAIN SCRIPT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compare DSPy optimization methods",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --methods baseline bootstrap gepa
  %(prog)s --methods gepa hybrid --evaluation-size 30
  %(prog)s --component-analysis --output detailed_report.json
        """
    )

    parser.add_argument(
        '--methods', '-m',
        nargs='+',
        choices=['baseline', 'bootstrap', 'gepa', 'hybrid'],
        default=['baseline', 'bootstrap', 'gepa'],
        help='Optimization methods to compare'
    )

    parser.add_argument(
        '--evaluation-size', '-e',
        type=int,
        default=50,
        help='Number of examples to use for evaluation (default: 50)'
    )

    parser.add_argument(
        '--output', '-o',
        default='optimizer_comparison.json',
        help='Output file for results (default: optimizer_comparison.json)'
    )

    parser.add_argument(
        '--detailed-report',
        action='store_true',
        help='Generate detailed report with recommendations'
    )

    parser.add_argument(
        '--component-analysis',
        action='store_true',
        help='Include component-level performance analysis'
    )

    parser.add_argument(
        '--reflection-model',
        default='claude-3-5-sonnet',
        help='Model for GEPA reflection (default: claude-3-5-sonnet)'
    )

    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Random seed for reproducibility (default: 42)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check requirements
    if 'gepa' in args.methods or 'hybrid' in args.methods:
        try:
            from dspy.teleprompt import GEPA
        except ImportError:
            logger.error("GEPA library not available for GEPA/hybrid methods")
            sys.exit(1)

        if not os.getenv("ANTHROPIC_API_KEY"):
            logger.error("ANTHROPIC_API_KEY required for GEPA/hybrid methods")
            sys.exit(1)

    try:
        # Configure DSPy
        configure_dspy_model()

        # Create reflection LM for GEPA methods
        reflection_lm = None
        if 'gepa' in args.methods or 'hybrid' in args.methods:
            reflection_lm = create_reflection_lm(model=args.reflection_model)

        # Run comparison
        comparator = OptimizerComparison(
            reflection_lm=reflection_lm,
            evaluation_size=args.evaluation_size,
            seed=args.seed
        )

        logger.info("Starting optimizer comparison...")
        start_time = time.time()

        results = comparator.run_comparison(args.methods)

        total_time = time.time() - start_time
        results['total_comparison_time'] = total_time

        # Save results
        if args.detailed_report:
            generate_detailed_report(results, args.output)
        else:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)

        logger.info(f"Comparison completed in {total_time:.1f}s")
        logger.info(f"Results saved to: {args.output}")

        # Print summary
        if results.get('summary', {}).get('best_method'):
            best = results['summary']['best_method']
            score = results['summary']['best_score']
            logger.info(f"Best method: {best} (score: {score:.3f})")

    except Exception as e:
        logger.error(f"Comparison failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()