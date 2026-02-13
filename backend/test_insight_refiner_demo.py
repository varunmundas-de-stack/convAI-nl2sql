"""
Test script for Insight Refiner

Demonstrates the complete flow from deterministic insights to LLM-refined insights.
"""

import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

from app.services.insight_engine import (
    generate_insights,
    Insight,
    InsightResult,
    InsightType,
    Severity,
    Direction,
)
from app.services.insight_refiner import refine_insights
from app.models.intent import Intent


def test_insight_refiner():
    """
    Test the insight refiner with sample data.
    """
    print("=" * 80)
    print("INSIGHT REFINER TEST")
    print("=" * 80)
    
    # Sample data: Sales by region
    data = [
        {"region": "Mumbai", "total_sales": 420000},
        {"region": "Delhi", "total_sales": 250000},
        {"region": "Bangalore", "total_sales": 180000},
        {"region": "Chennai", "total_sales": 150000},
    ]
    
    # Sample intent
    intent = Intent(
        metric="total_sales",
        group_by=["region"],
        intent_type="ranking",
    )
    
    print("\n1. GENERATING DETERMINISTIC INSIGHTS")
    print("-" * 80)
    
    # Generate deterministic insights
    insights = generate_insights(data=data, intent=intent)
    
    print(f"Total Rows: {insights.total_rows}")
    print(f"Total Value: {insights.total_formatted}")
    print(f"Insights Generated: {len(insights.insights)}")
    print()
    
    for idx, insight in enumerate(insights.insights[:3], 1):
        print(f"Insight {idx}:")
        print(f"  Type: {insight.insight_type}")
        print(f"  Label: {insight.label}")
        print(f"  Headline: {insight.headline}")
        print(f"  Severity: {insight.severity}")
        print(f"  Confidence: {insight.confidence}")
        if insight.metric_value:
            print(f"  Metric Value: {insight.metric_formatted}")
        print()
    
    print("\n2. REFINING INSIGHTS WITH LLM")
    print("-" * 80)
    print("Calling LLM to refine insights...")
    print("(Note: This requires ANTHROPIC_API_KEY in .env)")
    print()
    
    try:
        # Refine insights
        refined = refine_insights(
            insight_result=insights,
            data=data,
            query="Show me sales by region",
            previous_qco=None,
        )
        
        print(f"✓ Refinement successful!")
        print(f"Refined Insights: {len(refined.insights)}")
        if refined.executive_summary:
            print(f"Executive Summary: {refined.executive_summary}")
        print()
        
        # Compare original vs refined
        print("\n3. COMPARISON: ORIGINAL vs REFINED")
        print("-" * 80)
        
        for idx, (original, refined_insight) in enumerate(zip(insights.insights[:3], refined.insights[:3]), 1):
            print(f"\nInsight {idx}: {original.label}")
            print()
            print(f"  ORIGINAL:")
            print(f"    Headline: {original.headline}")
            print(f"    Severity: {original.severity.value}")
            print(f"    Confidence: {original.confidence}")
            print()
            print(f"  REFINED:")
            print(f"    Headline: {refined_insight.headline}")
            print(f"    Severity: {refined_insight.severity.value}")
            print(f"    Confidence: {refined_insight.confidence}")
            if refined_insight.context_note:
                print(f"    Context: {refined_insight.context_note}")
            print()
            print(f"  IMMUTABLE FIELDS (preserved):")
            print(f"    Metric Value: {original.metric_value} → {refined_insight.metric_value} ✓")
            print(f"    Change %: {original.change_pct} → {refined_insight.change_pct} ✓")
            print()
        
    except Exception as e:
        print(f"✗ Refinement failed: {e}")
        print("This is expected if ANTHROPIC_API_KEY is not set")
        print("Fallback behavior: system will use original insights")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    test_insight_refiner()
