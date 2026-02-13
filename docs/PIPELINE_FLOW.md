# Insight Refiner - Complete Pipeline Flow

## Pipeline Stages

```
┌─────────────────────────────────────────────────────────────────────┐
│                           USER QUERY                                │
│                    "Show me sales by region"                        │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1: Intent Extraction (LLM)                                   │
│  ─────────────────────────────────────────────────────────────      │
│  Input: NL Query + Previous QCO                                     │
│  Output: Raw Intent JSON                                            │
│  Tool: app.services.intent_extractor                                │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2: Intent Validation & Cube Query Build                      │
│  ────────────────────────────────────────────────────────────────   │
│  Input: Raw Intent                                                  │
│  Output: Validated Intent → Cube Query                             │
│  Tools: intent_validator, cube_query_builder                       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 3: Cube Query Execution                                      │
│  ─────────────────────────────────────────────────────────────────  │
│  Input: Cube Query                                                  │
│  Output: Raw Data Rows                                              │
│  Tool: cube_client                                                  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 4: Insight Generation (Deterministic Math)                   │
│  ─────────────────────────────────────────────────────────────────  │
│  Input: Raw Data + Intent + Previous QCO                            │
│  Output: InsightResult                                              │
│  Tool: app.services.insight_engine                                  │
│                                                                      │
│  Calculations:                                                       │
│  • Totals & Aggregates                                              │
│  • Top-N Concentration (Pareto analysis)                            │
│  • Outlier Detection (z-score > 2σ)                                 │
│  • Trend Analysis (linear regression, R²)                           │
│  • Period Comparison (% change)                                     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 5: Insight Refinement (LLM Enhancement) ⭐ NEW               │
│  ─────────────────────────────────────────────────────────────────  │
│  Input: InsightResult + Data Summary + QCO + Query                  │
│  Output: RefinedInsightResult                                       │
│  Tool: app.services.insight_refiner                                 │
│                                                                      │
│  LLM Refinements:                                                    │
│  ✓ Adjust headline language (executive-style)                       │
│  ✓ Upgrade/downgrade severity                                       │
│  ✓ Adjust confidence based on context                               │
│  ✓ Add context_note (business implications)                         │
│  ✓ Add executive_summary                                            │
│                                                                      │
│  Protected Fields (LLM CANNOT change):                               │
│  ✗ metric_value                                                      │
│  ✗ comparison_value                                                  │
│  ✗ change_pct                                                        │
│  ✗ All numeric calculations                                          │
│                                                                      │
│  Fallback: If LLM fails → use original InsightResult                │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 6: Visual Spec Generation                                    │
│  ─────────────────────────────────────────────────────────────────  │
│  Input: RefinedInsightResult (or InsightResult) + Raw Data          │
│  Output: VisualSpec (declarative chart specification)               │
│  Tool: app.services.visual_spec_generator                           │
│                                                                      │
│  Generates:                                                          │
│  • Chart type selection                                             │
│  • Data series with per-point emphasis ⭐ NEW                        │
│  • Annotations from insights                                        │
│  • Markers for outliers/trends                                      │
│  • Title, subtitle, axis labels                                     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR RESPONSE                            │
│  ──────────────────────────────────────────────────────────────────│
│  {                                                                   │
│    "success": true,                                                 │
│    "stage": "completed",                                            │
│    "data": [...],                                                   │
│    "insights": InsightResult,           // Original math-based      │
│    "refined_insights": RefinedInsightResult,  // LLM-enhanced ⭐    │
│    "visual_spec": VisualSpec,           // Frontend-ready           │
│  }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

## Example: Mumbai Sales Insight

### Stage 4 Output (InsightEngine)

```python
Insight(
    insight_type=InsightType.CONCENTRATION,
    severity=Severity.MEDIUM,
    label="top_contributor",
    headline="Mumbai accounts for 42% of sales.total_sales",
    metric_value=420000.0,
    change_pct=42.0,
    dimension="sales.region",
    dimension_value="Mumbai",
    confidence=1.0,
)
```

### Stage 5 Output (InsightRefiner - LLM Enhanced) ⭐

```python
RefinedInsight(
    # IMMUTABLE - Preserved from original
    insight_type="concentration",
    label="top_contributor",
    metric_value=420000.0,      # ✗ Cannot change
    change_pct=42.0,            # ✗ Cannot change
    dimension="sales.region",   # ✗ Cannot change
    dimension_value="Mumbai",   # ✗ Cannot change
    
    # MUTABLE - Refined by LLM
    headline="Mumbai drives nearly half of total sales and warrants strategic focus",  # ✓ Refined
    severity=Severity.HIGH,     # ✓ Upgraded from MEDIUM
    confidence=0.95,            # ✓ Adjusted from 1.0
    context_note="High concentration risk if Mumbai market weakens",  # ✓ NEW
)

# Plus executive_summary at result level:
executive_summary="Mumbai dominates sales at 42%. Consider diversification strategy."
```

### Stage 6 Output (VisualSpec)

```python
VisualSpec(
    chart_type=ChartType.BAR,
    series=[
        DataSeries(
            label="Total Sales",
            values=[420000, 250000, 180000, 150000],
            point_emphasis=[
                EmphasisLevel.STRONG,  # Mumbai - highlighted! ⭐
                EmphasisLevel.NONE,
                EmphasisLevel.NONE,
                EmphasisLevel.NONE,
            ]
        )
    ],
    annotations=[
        InsightAnnotation(
            text="Mumbai drives nearly half of total sales and warrants strategic focus",
            severity=Severity.HIGH,
            position="header"
        )
    ],
    markers=[
        Marker(
            marker_type=MarkerType.ANNOTATION,
            label="Top contributor",
            position="Mumbai",
            emphasis=EmphasisLevel.STRONG
        )
    ]
)
```

## Key Design Principles

### 1. Separation of Concerns
- **Math** = InsightEngine (deterministic)
- **Language** = InsightRefiner (LLM)
- **Presentation** = VisualSpecGenerator (declarative)

### 2. Non-Breaking Changes
- Original insights preserved
- Fallback to original if refinement fails
- Existing tests continue to pass

### 3. Immutability of Calculations
- Numbers never change
- Math is sacred
- LLM only refines interpretation

### 4. Progressive Enhancement
- System works without refinement
- Refinement adds value when successful
- Graceful degradation on failure

## Configuration

Located in `backend/app/prompts/insight_refiner.txt`:
- Clear instructions for LLM
- Strict rules about what can/cannot change
- JSON output schema
- Executive-style language guidance
