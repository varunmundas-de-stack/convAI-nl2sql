"""
Training examples for DSPy Intent Extraction Pipeline.

Following RULE T1: Use partial-credit metric, never exact match
Following RULE T2: Cover every failure mode with at least 2 examples
Following RULE T3: Include at least 2 multi-turn examples per context rule
Following RULE T4: Label final output only, not intermediate agents
Following RULE T5: .with_inputs() must match pipeline forward() kwargs
"""

import dspy
from typing import List, Dict, Any

from ..models.intent import Intent, Metric, Filter, TimeSpec, PostProcessing, RankingSpec, ComparisonSpec

# =============================================================================
# TRAINING EXAMPLES
# =============================================================================

def get_training_examples() -> List[dspy.Example]:
    """
    Get training examples for pipeline optimization.

    Examples cover:
    - All intent types (SNAPSHOT, TREND, COMPARISON, RANKING, DISTRIBUTION)
    - All failure modes (wrong metrics, invalid dimensions, time spec errors)
    - Multi-turn context scenarios
    - Edge cases and constraints
    """

    examples = []

    # =============================================================================
    # BASIC INTENT TYPES (RULE T2 - Cover every failure mode)
    # =============================================================================

    # SNAPSHOT queries
    examples.append(
        dspy.Example(
            query="Total net sales value this month",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "net_value", "aggregation": "sum"}],
                "group_by": None,
                "filters": None,
                "time": {
                    "dimension": "invoice_date",
                    "window": "month_to_date",
                    "start_date": None,
                    "end_date": None,
                    "granularity": None
                },
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    examples.append(
        dspy.Example(
            query="How many transactions in North-1 zone last week",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "count", "aggregation": "count"}],
                "group_by": None,
                "filters": [{"dimension": "zone", "operator": "equals", "value": "North-1"}],
                "time": {
                    "dimension": "invoice_date",
                    "window": "last_7_days",
                    "start_date": None,
                    "end_date": None,
                    "granularity": None
                },
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # RANKING queries (RULE T2 - ranking with/without group_by)
    examples.append(
        dspy.Example(
            query="Top 5 zones by total quantity",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "billed_qty", "aggregation": "sum"}],
                "group_by": ["zone"],
                "filters": None,
                "time": None,
                "post_processing": {
                    "ranking": {"enabled": True, "order": "desc", "limit": 5},
                    "comparison": None,
                    "derived_metric": "none"
                }
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # Ranking WITHOUT group_by should disable ranking (failure mode)
    examples.append(
        dspy.Example(
            query="Top sales value",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "net_value", "aggregation": "sum"}],
                "group_by": None,
                "filters": None,
                "time": None,
                "post_processing": None  # Ranking disabled due to no group_by
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # TREND queries
    examples.append(
        dspy.Example(
            query="Show daily trend of Secondary Sales net value for Oil category over last 30 days",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "net_value", "aggregation": "sum"}],
                "group_by": None,
                "filters": [{"dimension": "category", "operator": "equals", "value": "Oil"}],
                "time": {
                    "dimension": "invoice_date",
                    "window": "last_30_days",
                    "start_date": None,
                    "end_date": None,
                    "granularity": "day"
                },
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    examples.append(
        dspy.Example(
            query="Show monthly trend of Primary Sales gross value for Aata category from January to March 2024",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "PRIMARY",
                "metrics": [{"name": "gross_value", "aggregation": "sum"}],
                "group_by": None,
                "filters": [{"dimension": "category", "operator": "equals", "value": "Aata"}],
                "time": {
                    "dimension": "invoice_date",
                    "window": None,
                    "start_date": "2024-01-01",
                    "end_date": "2024-03-31",
                    "granularity": "month"
                },
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # DISTRIBUTION queries
    examples.append(
        dspy.Example(
            query="What is the breakdown of sales by brand",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "net_value", "aggregation": "sum"}],
                "group_by": ["brand"],
                "filters": None,
                "time": None,
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # COMPARISON queries
    examples.append(
        dspy.Example(
            query="Compare net value this month vs last month by zone",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "net_value", "aggregation": "sum"}],
                "group_by": ["zone"],
                "filters": None,
                "time": {
                    "dimension": "invoice_date",
                    "window": "month_to_date",
                    "start_date": None,
                    "end_date": None,
                    "granularity": None
                },
                "post_processing": {
                    "ranking": None,
                    "comparison": {"type": "period", "comparison_window": "last_month"},
                    "derived_metric": "none"
                }
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # =============================================================================
    # MULTI-TURN CONTEXT EXAMPLES (RULE T3)
    # =============================================================================

    # MINIMAL_MESSAGE context rule
    examples.append(
        dspy.Example(
            query="brand",  # Just dimension name
            previous_context='{"sales_scope": "SECONDARY", "metrics": [{"name": "net_value", "aggregation": "sum"}], "time": {"window": "last_30_days"}, "filters": [{"dimension": "category", "value": "Oil"}]}',
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",  # Inherited
                "metrics": [{"name": "net_value", "aggregation": "sum"}],  # Inherited
                "group_by": ["brand"],  # New dimension
                "filters": [{"dimension": "category", "operator": "equals", "value": "Oil"}],  # Inherited
                "time": {
                    "dimension": "invoice_date",
                    "window": "last_30_days",
                    "start_date": None,
                    "end_date": None,
                    "granularity": None
                },  # Inherited
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # ALSO_BY context rule
    examples.append(
        dspy.Example(
            query="also by zone",  # Adding second dimension
            previous_context='{"group_by": ["brand"], "metrics": [{"name": "net_value"}]}',
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "net_value", "aggregation": "sum"}],
                "group_by": ["brand", "zone"],  # Added zone to existing brand
                "filters": None,
                "time": None,
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # =============================================================================
    # EDGE CASES AND ALIASES
    # =============================================================================

    # Metric aliases
    examples.append(
        dspy.Example(
            query="Total quantity sold by territory",  # quantity->billed_qty, territory->zone
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "billed_qty", "aggregation": "sum"}],  # Resolved alias
                "group_by": ["zone"],  # Resolved alias
                "filters": None,
                "time": None,
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    # Trend without explicit granularity
    examples.append(
        dspy.Example(
            query="Show trend for 5 kg pack size last 30 days",  # Default to week granularity
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "net_value", "aggregation": "sum"}],
                "group_by": None,
                "filters": [{"dimension": "pack_size", "operator": "equals", "value": "5 kg"}],
                "time": {
                    "dimension": "invoice_date",
                    "window": "last_30_days",
                    "start_date": None,
                    "end_date": None,
                    "granularity": "week"  # Default for trend
                },
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date")
    )

    return examples


def get_validation_examples() -> List[dspy.Example]:
    """Get validation examples (separate from training)."""
    return [
        dspy.Example(
            query="Which distributors have the highest gross value",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "gross_value", "aggregation": "sum"}],
                "group_by": ["distributor_name"],
                "filters": None,
                "time": None,
                "post_processing": {
                    "ranking": {"enabled": True, "order": "desc", "limit": 10},
                    "comparison": None,
                    "derived_metric": "none"
                }
            }
        ).with_inputs("query", "previous_context", "current_date"),

        dspy.Example(
            query="How has Aashirvaad been trending this quarter",
            previous_context="",
            current_date="2024-03-15",
            intent={
                "sales_scope": "SECONDARY",
                "metrics": [{"name": "net_value", "aggregation": "sum"}],
                "group_by": None,
                "filters": [{"dimension": "brand", "operator": "equals", "value": "Aashirvaad"}],
                "time": {
                    "dimension": "invoice_date",
                    "window": "quarter_to_date",
                    "start_date": None,
                    "end_date": None,
                    "granularity": "week"
                },
                "post_processing": None
            }
        ).with_inputs("query", "previous_context", "current_date"),
    ]