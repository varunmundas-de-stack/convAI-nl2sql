#!/usr/bin/env python3
"""
GEPA Optimization Script for DSPy Intent Extraction Pipeline.

This script provides a command-line interface for running GEPA optimization
experiments on the intent extraction pipeline. It supports various optimization
modes, configuration options, and result analysis.

Usage:
    python run_gepa_optimization.py --mode quick
    python run_gepa_optimization.py --mode production --save-path custom_path.pkl
    python run_gepa_optimization.py --mode compare --output results.json
    python run_gepa_optimization.py --mode ablation --components classifier metrics
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Add the backend directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import dspy
from app.dspy_pipeline.config import (
    configure_dspy_model, get_gepa_config, create_reflection_lm,
    validate_gepa_setup, is_gepa_enabled
)
from app.dspy_pipeline.gepa_optimizer import GepaIntentOptimizer, create_gepa_optimizer
from app.dspy_pipeline.pipeline import IntentExtractionPipeline
from app.dspy_pipeline.training import run_optimization_experiment

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# OPTIMIZATION MODES
# =============================================================================

def run_quick_optimization(args) -> Dict:
    """Run quick GEPA optimization for development/testing."""
    logger.info("Running quick GEPA optimization")

    # Configure DSPy
    configure_dspy_model()

    # Create reflection LM
    reflection_lm = create_reflection_lm(temperature=1.0)

    # Create optimizer with light settings
    optimizer = create_gepa_optimizer(
        reflection_lm=reflection_lm,
        auto='light',
        track_stats=True,
        seed=42
    )

    # Run optimization
    start_time = time.time()
    optimized_pipeline = optimizer.optimize()
    optimization_time = time.time() - start_time

    # Save results
    save_path = args.save_path or "quick_gepa_pipeline.pkl"
    optimizer.save_optimized_pipeline(save_path)

    results = {
        'mode': 'quick',
        'optimization_time': optimization_time,
        'saved_to': save_path,
        'status': optimizer.get_optimization_status()
    }

    # Save results
    results_path = args.output or "quick_gepa_results.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Quick optimization completed in {optimization_time:.1f}s")
    logger.info(f"Results saved to: {results_path}")

    return results

def run_production_optimization(args) -> Dict:
    """Run production-grade GEPA optimization."""
    logger.info("Running production GEPA optimization")

    # Configure DSPy
    configure_dspy_model()

    # Create reflection LM
    reflection_lm = create_reflection_lm(
        model='claude-3-5-sonnet',
        temperature=1.0,
        max_tokens=8192
    )

    # Create optimizer with heavy settings
    optimizer = create_gepa_optimizer(
        reflection_lm=reflection_lm,
        auto='heavy',
        track_stats=True,
        track_best_outputs=True,
        use_merge=True,
        seed=42
    )

    # Run optimization
    logger.info("Starting production optimization (this may take a while)...")
    start_time = time.time()
    optimized_pipeline = optimizer.optimize()
    optimization_time = time.time() - start_time

    # Save results
    save_path = args.save_path or "production_gepa_pipeline.pkl"
    optimizer.save_optimized_pipeline(save_path)

    # Get detailed results
    results = {
        'mode': 'production',
        'optimization_time': optimization_time,
        'saved_to': save_path,
        'status': optimizer.get_optimization_status()
    }

    # Add GEPA-specific details if available
    if hasattr(optimized_pipeline, 'detailed_results'):
        gepa_results = optimized_pipeline.detailed_results
        results['gepa_details'] = {
            'candidates_explored': len(gepa_results.candidates),
            'best_score': gepa_results.val_aggregate_scores[gepa_results.best_idx],
            'total_metric_calls': gepa_results.total_metric_calls,
            'num_full_evaluations': gepa_results.num_full_val_evals
        }

    # Save results
    results_path = args.output or "production_gepa_results.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Production optimization completed in {optimization_time:.1f}s")
    logger.info(f"Results saved to: {results_path}")

    return results

def run_comparison_mode(args) -> Dict:
    """Compare GEPA with BootstrapFewShot optimization."""
    logger.info("Running optimization method comparison")

    # Configure DSPy
    configure_dspy_model()

    # Create reflection LM
    reflection_lm = create_reflection_lm()

    # Create optimizer
    optimizer = GepaIntentOptimizer(
        pipeline=IntentExtractionPipeline(),
        reflection_lm=reflection_lm
    )

    # Run comparison
    start_time = time.time()
    results = optimizer.compare_with_bootstrap()
    comparison_time = time.time() - start_time

    results['comparison_time'] = comparison_time
    results['mode'] = 'comparison'

    # Save results
    results_path = args.output or "optimization_comparison.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Comparison completed in {comparison_time:.1f}s")
    logger.info(f"Results saved to: {results_path}")

    # Print summary
    if 'bootstrap' in results and 'gepa' in results:
        bootstrap_score = results['bootstrap'].get('scores', {}).get('mean_score', 0)
        gepa_score = results['gepa'].get('scores', {}).get('mean_score', 0)
        improvement = gepa_score - bootstrap_score

        logger.info(f"BootstrapFewShot score: {bootstrap_score:.3f}")
        logger.info(f"GEPA score: {gepa_score:.3f}")
        logger.info(f"GEPA improvement: {improvement:+.3f}")

    return results

def run_ablation_study(args) -> Dict:
    """Run ablation study to analyze component-level impacts."""
    logger.info("Running GEPA ablation study")

    # Configure DSPy
    configure_dspy_model()

    # Create reflection LM
    reflection_lm = create_reflection_lm()

    # Get components to test
    components = args.components
    if not components:
        from app.dspy_pipeline.gepa_feedback import get_available_components
        components = get_available_components()

    logger.info(f"Testing components: {components}")

    # Create optimizer
    optimizer = GepaIntentOptimizer(
        pipeline=IntentExtractionPipeline(),
        reflection_lm=reflection_lm
    )

    # Run ablation study
    start_time = time.time()
    results = optimizer.run_ablation_study(components=components)
    study_time = time.time() - start_time

    results['study_time'] = study_time
    results['mode'] = 'ablation'
    results['tested_components'] = components

    # Save results
    results_path = args.output or "ablation_study.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Ablation study completed in {study_time:.1f}s")
    logger.info(f"Results saved to: {results_path}")

    # Print summary
    if 'summary' in results:
        summary = results['summary']
        logger.info(f"Best component for optimization: {summary.get('best_component')}")
        logger.info(f"Maximum improvement: {summary.get('max_improvement', 0):.3f}")
        logger.info(f"Mean improvement: {summary.get('mean_improvement', 0):.3f}")

    return results

def run_validation_mode(args) -> Dict:
    """Validate GEPA setup and configuration."""
    logger.info("Validating GEPA setup")

    validation_results = validate_gepa_setup()

    # Save validation results
    results_path = args.output or "gepa_validation.json"
    with open(results_path, 'w') as f:
        json.dump(validation_results, f, indent=2, default=str)

    # Print validation summary
    if validation_results['overall_status']:
        logger.info("✅ GEPA setup is valid and ready for use")
    else:
        logger.error("❌ GEPA setup has issues:")
        for issue in validation_results['issues']:
            logger.error(f"  - {issue}")

    logger.info(f"Validation results saved to: {results_path}")

    return validation_results

# =============================================================================
# MAIN SCRIPT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="GEPA Optimization for DSPy Intent Extraction Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --mode quick
  %(prog)s --mode production --save-path my_pipeline.pkl
  %(prog)s --mode compare --output comparison.json
  %(prog)s --mode ablation --components classifier metrics
  %(prog)s --mode validate
        """
    )

    parser.add_argument(
        '--mode', '-m',
        choices=['quick', 'production', 'compare', 'ablation', 'validate'],
        default='quick',
        help='Optimization mode to run (default: quick)'
    )

    parser.add_argument(
        '--save-path', '-s',
        help='Path to save optimized pipeline (default: mode-specific name)'
    )

    parser.add_argument(
        '--output', '-o',
        help='Path to save results JSON (default: mode-specific name)'
    )

    parser.add_argument(
        '--components', '-c',
        nargs='+',
        help='Components to test in ablation mode (default: all)'
    )

    parser.add_argument(
        '--reflection-model',
        default='claude-3-5-sonnet',
        help='Model to use for GEPA reflection (default: claude-3-5-sonnet)'
    )

    parser.add_argument(
        '--budget',
        choices=['light', 'medium', 'heavy'],
        help='Override budget setting for optimization modes'
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
        logging.getLogger('app.dspy_pipeline').setLevel(logging.DEBUG)

    # Check if GEPA is available
    if args.mode != 'validate':
        try:
            from dspy.teleprompt import GEPA
        except ImportError:
            logger.error("GEPA library not available. Please install the gepa package.")
            sys.exit(1)

        # Check API key
        if not os.getenv("ANTHROPIC_API_KEY"):
            logger.error("ANTHROPIC_API_KEY environment variable not set")
            sys.exit(1)

    # Route to appropriate optimization mode
    try:
        if args.mode == 'quick':
            results = run_quick_optimization(args)
        elif args.mode == 'production':
            results = run_production_optimization(args)
        elif args.mode == 'compare':
            results = run_comparison_mode(args)
        elif args.mode == 'ablation':
            results = run_ablation_study(args)
        elif args.mode == 'validate':
            results = run_validation_mode(args)
        else:
            logger.error(f"Unknown mode: {args.mode}")
            sys.exit(1)

        logger.info("Optimization script completed successfully")

    except Exception as e:
        logger.error(f"Optimization failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()