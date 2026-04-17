#!/usr/bin/env python3
"""
Quick GEPA Utilities for DSPy Intent Extraction Pipeline.

This script provides quick utilities for common GEPA operations like
validation, quick optimization, and status checking.

Usage:
    python gepa_utils.py validate
    python gepa_utils.py optimize-quick
    python gepa_utils.py status
    python gepa_utils.py deploy-pipeline --path my_pipeline.pkl
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add the backend directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.dspy_pipeline.config import (
    validate_gepa_setup, get_pipeline_info, trigger_gepa_optimization,
    create_reflection_lm, pipeline_manager, GEPA_PIPELINE_PATH
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def cmd_validate(args):
    """Validate GEPA setup and configuration."""
    print("🔍 Validating GEPA setup...")

    validation = validate_gepa_setup()

    if validation['overall_status']:
        print("✅ GEPA setup is valid and ready for use!")
        print(f"   GEPA enabled: {validation['gepa_enabled']}")
        print(f"   API key configured: {validation['anthropic_api_key_set']}")
        print(f"   GEPA library available: {validation['gepa_library_available']}")
    else:
        print("❌ GEPA setup has issues:")
        for issue in validation['issues']:
            print(f"   - {issue}")

    if args.verbose:
        print("\nDetailed validation results:")
        print(json.dumps(validation, indent=2))

def cmd_status(args):
    """Show current pipeline status and configuration."""
    print("📊 Current Pipeline Status")
    print("=" * 50)

    # Get pipeline info
    info = get_pipeline_info()

    print(f"Optimization Method: {info.get('method', 'unknown')}")
    print(f"GEPA Enabled: {info.get('gepa_enabled', False)}")
    print(f"GEPA Available: {info.get('gepa_available', False)}")
    print(f"Compiled Available: {info.get('compiled_available', False)}")
    print(f"Current Mode: {info.get('current_mode', 'unknown')}")

    if info.get('gepa_config'):
        print("\nGEPA Configuration:")
        config = info['gepa_config']
        print(f"  Budget Mode: {config.get('budget_mode', 'unknown')}")
        print(f"  Component Selector: {config.get('component_selector', 'unknown')}")
        print(f"  Enabled Components: {', '.join(config.get('enabled_components', []))}")
        print(f"  Use Merge: {config.get('use_merge', False)}")
        print(f"  Track Stats: {config.get('track_stats', False)}")

    if args.verbose:
        print("\nFull pipeline info:")
        print(json.dumps(info, indent=2, default=str))

def cmd_optimize_quick(args):
    """Run quick GEPA optimization."""
    print("🚀 Running quick GEPA optimization...")

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set")
        return

    try:
        # Create reflection LM
        reflection_lm = create_reflection_lm(temperature=1.0)

        # Run quick optimization
        optimized_pipeline = trigger_gepa_optimization(
            reflection_lm=reflection_lm,
            auto='light',
            track_stats=True
        )

        print("✅ Quick optimization completed!")
        print(f"   Pipeline saved to: {GEPA_PIPELINE_PATH}")

        # Show updated status
        info = get_pipeline_info()
        print(f"   New optimization method: {info.get('method', 'unknown')}")

    except Exception as e:
        print(f"❌ Optimization failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()

def cmd_deploy_pipeline(args):
    """Deploy a GEPA-optimized pipeline."""
    pipeline_path = args.path

    if not pipeline_path:
        print("❌ Pipeline path required (use --path)")
        return

    if not Path(pipeline_path).exists():
        print(f"❌ Pipeline file not found: {pipeline_path}")
        return

    try:
        print(f"📦 Deploying pipeline from: {pipeline_path}")

        # Load the pipeline
        pipeline_manager.use_gepa_pipeline(pipeline_path)

        print("✅ Pipeline deployed successfully!")

        # Show status
        info = get_pipeline_info()
        print(f"   Current method: {info.get('method', 'unknown')}")

    except Exception as e:
        print(f"❌ Deployment failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()

def cmd_reset_pipeline(args):
    """Reset pipeline to unoptimized state."""
    print("🔄 Resetting pipeline to unoptimized state...")

    try:
        pipeline_manager.force_refresh()
        print("✅ Pipeline reset completed!")

        # Show status
        info = get_pipeline_info()
        print(f"   Current method: {info.get('method', 'unknown')}")

    except Exception as e:
        print(f"❌ Reset failed: {e}")

def cmd_create_config(args):
    """Create sample GEPA configuration."""
    config_content = """# GEPA Configuration Environment Variables
# Copy these to your .env file and adjust as needed

# Enable GEPA optimization
GEPA_OPTIMIZATION_ENABLED=true

# Reflection model for GEPA (higher quality = better optimization)
GEPA_REFLECTION_MODEL=claude-3-5-sonnet

# Optimization budget (light/medium/heavy)
GEPA_BUDGET_MODE=medium

# Component selection strategy
GEPA_COMPONENT_SELECTOR=round_robin

# Enable optimization for specific components
GEPA_OPTIMIZE_CLASSIFIER=true
GEPA_OPTIMIZE_SCOPE=true
GEPA_OPTIMIZE_TIME=true
GEPA_OPTIMIZE_METRICS=true
GEPA_OPTIMIZE_DIMENSIONS=true

# GEPA options
GEPA_USE_MERGE=true
GEPA_TRACK_STATS=true

# Optional: Custom limits
# GEPA_MAX_METRIC_CALLS=1000
# GEPA_TRAINING_LIMIT=100
# GEPA_VALIDATION_LIMIT=50

# Optional: Weights & Biases integration
# GEPA_WANDB_ENABLED=false
# WANDB_API_KEY=your_wandb_key

# Random seed for reproducibility
GEPA_SEED=42
"""

    config_path = args.output or "gepa_config.env"

    with open(config_path, 'w') as f:
        f.write(config_content)

    print(f"📝 Sample GEPA configuration created: {config_path}")
    print("   Copy these settings to your .env file and adjust as needed")

def main():
    parser = argparse.ArgumentParser(
        description="Quick GEPA utilities for DSPy Intent Extraction Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate GEPA setup')
    validate_parser.set_defaults(func=cmd_validate)

    # Status command
    status_parser = subparsers.add_parser('status', help='Show pipeline status')
    status_parser.set_defaults(func=cmd_status)

    # Quick optimization command
    optimize_parser = subparsers.add_parser('optimize-quick', help='Run quick GEPA optimization')
    optimize_parser.set_defaults(func=cmd_optimize_quick)

    # Deploy pipeline command
    deploy_parser = subparsers.add_parser('deploy-pipeline', help='Deploy GEPA pipeline')
    deploy_parser.add_argument('--path', '-p', required=True, help='Path to pipeline file')
    deploy_parser.set_defaults(func=cmd_deploy_pipeline)

    # Reset pipeline command
    reset_parser = subparsers.add_parser('reset-pipeline', help='Reset to unoptimized pipeline')
    reset_parser.set_defaults(func=cmd_reset_pipeline)

    # Create config command
    config_parser = subparsers.add_parser('create-config', help='Create sample GEPA configuration')
    config_parser.add_argument('--output', '-o', help='Output file path (default: gepa_config.env)')
    config_parser.set_defaults(func=cmd_create_config)

    # Global arguments
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        args.func(args)
    except Exception as e:
        print(f"❌ Command failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()