"""
Insight Engine - Intelligence Layer

INPUTS:
- Validated intent (current query's resolved parameters)
- Query Context Object (previous intent, resolved entities, time ranges)
- Query result data (raw rows + aggregates)
- Optional baseline (previous period for comparison)

OUTPUTS:
- Machine-readable InsightResult object — NOT prose, NOT charts.
- Contains: headline, direction, magnitude, comparisons, anomalies, segments

DESIGN PRINCIPLES:
- Pure analysis: no rendering, no colors, no layout
- Deterministic where possible (math-based, not LLM-based)
- Insight types are explicit and enumerated
- Every insight has a confidence score
- The output is consumed by the Visual Spec Generator downstream
"""

import logging
import math
from typing import Any, Optional
from pydantic import BaseModel, Field
from enum import Enum

from app.models.intent import Intent
from app.models.qco import QueryContextObject

logger = logging.getLogger(__name__)


# =============================================================================
# INSIGHT TYPES
# =============================================================================

class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    """How noteworthy is this insight?"""
    LOW = "low"           # Normal fluctuation
    MEDIUM = "medium"     # Worth noting
    HIGH = "high"         # Significant change
    CRITICAL = "critical" # Anomalous


class InsightType(str, Enum):
    HEADLINE = "headline"           # The primary takeaway
    COMPARISON = "comparison"       # vs previous period / baseline
    CONCENTRATION = "concentration" # Top N account for X%
    OUTLIER = "outlier"             # A value far from the rest
    TREND = "trend"                 # Direction over time
    MISSING_DATA = "missing_data"   # Gaps or nulls worth flagging


# =============================================================================
# INSIGHT MODELS (Machine-readable, NOT prose)
# =============================================================================

class Insight(BaseModel):
    """A single machine-readable insight."""
    insight_type: InsightType
    severity: Severity = Severity.LOW
    label: str = Field(..., description="Short machine-friendly label, e.g. 'top_contributor'")
    headline: str = Field(..., description="One-line human summary, e.g. 'Mumbai accounts for 42% of sales'")
    
    # Quantitative data
    metric_value: Optional[float] = None
    metric_formatted: Optional[str] = None
    comparison_value: Optional[float] = None
    comparison_formatted: Optional[str] = None
    change_pct: Optional[float] = None
    direction: Direction = Direction.UNKNOWN
    
    # Context
    dimension: Optional[str] = None        # Which dimension this insight is about
    dimension_value: Optional[str] = None  # Specific value (e.g. "Mumbai")
    
    # Confidence (0.0 to 1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class InsightResult(BaseModel):
    """Complete insight output from the engine."""
    # Summary
    total_rows: int = 0
    total_value: Optional[float] = None
    total_formatted: Optional[str] = None
    
    # Computed insights
    insights: list[Insight] = Field(default_factory=list)
    
    # Recommended emphasis
    primary_insight: Optional[Insight] = None
    secondary_insight: Optional[Insight] = None
    
    # Context echoed back
    metric: Optional[str] = None
    dimensions: Optional[list[str]] = None
    intent_type: Optional[str] = None
    has_previous_context: bool = False


class InsightEngineError(Exception):
    """Raised when insight generation fails."""
    pass


# =============================================================================
# ENGINE
# =============================================================================

def generate_insights(
    data: list[dict[str, Any]],
    intent: Intent,
    previous_qco: Optional[QueryContextObject] = None,
    baseline_data: Optional[list[dict[str, Any]]] = None,
) -> InsightResult:
    """
    Analyze query results and produce machine-readable insights.
    
    This is the ONLY public function.
    
    Args:
        data: Raw query result rows
        intent: Validated intent (current query)
        previous_qco: Previous QCO (for context-aware insights)
        baseline_data: Optional previous-period data for comparison
        
    Returns:
        InsightResult with computed insights
    """
    logger.info(f"Generating insights: {len(data)} rows, metric={intent.metric}")
    
    # Handle both Pydantic models and dicts for intent
    if hasattr(intent, 'model_dump'):
        intent_dict = intent.model_dump()
    else:
        intent_dict = intent

    metric_key = intent_dict.get("metric", "")
    dimensions = intent_dict.get("group_by") or []
    intent_type = intent_dict.get("intent_type", "")
    if hasattr(intent_type, "value"):
        intent_type = intent_type.value
    
    result = InsightResult(
        total_rows=len(data),
        metric=metric_key,
        dimensions=dimensions,
        intent_type=intent_type,
        has_previous_context=previous_qco is not None,
    )
    
    if not data:
        result.insights.append(Insight(
            insight_type=InsightType.MISSING_DATA,
            severity=Severity.MEDIUM,
            label="no_data",
            headline="No data returned for this query",
        ))
        result.primary_insight = result.insights[0]
        result.secondary_insight = result.insights[1]
        return result
    
    # -------------------------------------------------------------------------
    # 1. HEADLINE: Total / aggregate
    # -------------------------------------------------------------------------
    total = _compute_total(data, metric_key)
    if total is not None:
        result.total_value = total
        result.total_formatted = _format_number(total)
        
        headline_insight = Insight(
            insight_type=InsightType.HEADLINE,
            severity=Severity.LOW,
            label="total",
            headline=f"Total {_format_label(metric_key)}: {_format_number(total)}",
            metric_value=total,
            metric_formatted=_format_number(total),
        )
        result.insights.append(headline_insight)
        result.primary_insight = headline_insight
    
    # -------------------------------------------------------------------------
    # 2. CONCENTRATION: Top N analysis (for ranked/grouped data)
    # -------------------------------------------------------------------------
    if dimensions and len(data) > 1 and total and total > 0:
        concentration_insights = _analyze_concentration(data, metric_key, dimensions[0], total)
        result.insights.extend(concentration_insights)
    
    # -------------------------------------------------------------------------
    # 3. OUTLIERS: Values significantly above/below mean
    # -------------------------------------------------------------------------
    if len(data) > 2:
        outlier_insights = _detect_outliers(data, metric_key, dimensions[0] if dimensions else None)
        result.insights.extend(outlier_insights)
    
    # -------------------------------------------------------------------------
    # 4. COMPARISON: vs baseline (previous period)
    # -------------------------------------------------------------------------
    if baseline_data:
        comparison_insights = _compare_to_baseline(data, baseline_data, metric_key, total)
        result.insights.extend(comparison_insights)
    
    # -------------------------------------------------------------------------
    # 5. TREND: Direction analysis (for time-series data)
    # -------------------------------------------------------------------------
    if intent_type == "trend" and len(data) > 2:
        # Extract time dimension for proper sorting
        time_col = None
        td = intent_dict.get("time_dimension")
        if td:
             # handle both dict (from model_dump) and object
            if isinstance(td, dict):
                time_col = td.get("dimension")
            elif hasattr(td, "dimension"):
                time_col = td.dimension
        
        trend_insights = _analyze_trend(data, metric_key, time_col)
        result.insights.extend(trend_insights)
    
    # Analyze and rank insights
    if result.insights:
        # Define severity weights
        severity_rank = {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1
        }
        
        # Sort by Severity (desc) -> Confidence (desc)
        sorted_insights = sorted(
            result.insights,
            key=lambda i: (
                severity_rank.get(i.severity, 0),
                i.confidence
            ),
            reverse=True
        )
        
        result.primary_insight = sorted_insights[0]
        
        # Assign secondary insight if available
        if len(sorted_insights) > 1:
            result.secondary_insight = sorted_insights[1]
    
    logger.info(f"Generated {len(result.insights)} insights, primary: {result.primary_insight.label if result.primary_insight else 'none'}")
    return result


# =============================================================================
# ANALYSIS FUNCTIONS (Pure math, no LLM)
# =============================================================================

def _compute_total(data: list[dict[str, Any]], metric_key: str) -> Optional[float]:
    """Sum all metric values across rows."""
    total = 0.0
    found = False
    
    for row in data:
        val = _extract_numeric(row, metric_key)
        if val is not None:
            total += val
            found = True
    
    return total if found else None


def _analyze_concentration(
    data: list[dict[str, Any]], 
    metric_key: str,
    dimension_key: str,
    total: float,
) -> list[Insight]:
    """
    Top-N concentration analysis.
    
    "Top 3 regions account for 72% of sales"
    """
    insights = []
    
    # Sort by metric value descending
    scored = []
    for row in data:
        val = _extract_numeric(row, metric_key)
        dim_val = _extract_dimension_value(row, dimension_key)
        if val is not None and dim_val:
            scored.append((dim_val, val))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    
    if not scored:
        return insights
    
    # Top contributor
    top_name, top_val = scored[0]
    top_pct = (top_val / total * 100) if total > 0 else 0
    
    severity = Severity.LOW
    if top_pct > 50:
        severity = Severity.HIGH
    elif top_pct > 30:
        severity = Severity.MEDIUM
    
    insights.append(Insight(
        insight_type=InsightType.CONCENTRATION,
        severity=severity,
        label="top_contributor",
        headline=f"{top_name} accounts for {top_pct:.0f}% of {_format_label(metric_key)}",
        metric_value=top_val,
        metric_formatted=_format_number(top_val),
        change_pct=top_pct,
        dimension=dimension_key,
        dimension_value=top_name,
    ))
    
    # Top 3 concentration (if enough data)
    if len(scored) >= 3:
        top3_val = sum(v for _, v in scored[:3])
        top3_pct = (top3_val / total * 100) if total > 0 else 0
        
        if top3_pct > 60:
            insights.append(Insight(
                insight_type=InsightType.CONCENTRATION,
                severity=Severity.MEDIUM,
                label="top3_concentration",
                headline=f"Top 3 account for {top3_pct:.0f}% of total",
                metric_value=top3_val,
                metric_formatted=_format_number(top3_val),
                change_pct=top3_pct,
            ))
    
    # Bottom performer
    if len(scored) >= 2:
        bottom_name, bottom_val = scored[-1]
        bottom_pct = (bottom_val / total * 100) if total > 0 else 0
        
        insights.append(Insight(
            insight_type=InsightType.CONCENTRATION,
            severity=Severity.LOW,
            label="bottom_performer",
            headline=f"{bottom_name} contributes only {bottom_pct:.1f}%",
            metric_value=bottom_val,
            metric_formatted=_format_number(bottom_val),
            change_pct=bottom_pct,
            dimension=dimension_key,
            dimension_value=bottom_name,
        ))
    
    return insights


def _detect_outliers(
    data: list[dict[str, Any]],
    metric_key: str,
    dimension_key: Optional[str],
) -> list[Insight]:
    """
    Detect values > 2 standard deviations from mean.
    """
    insights = []
    
    values = []
    for row in data:
        val = _extract_numeric(row, metric_key)
        if val is not None:
            dim = _extract_dimension_value(row, dimension_key) if dimension_key else None
            values.append((dim, val))
    
    if len(values) < 3:
        return insights
    
    nums = [v for _, v in values]
    mean = sum(nums) / len(nums)
    variance = sum((x - mean) ** 2 for x in nums) / len(nums)
    std_dev = math.sqrt(variance) if variance > 0 else 0
    
    if std_dev == 0:
        return insights
    
    for dim_val, val in values:
        z_score = (val - mean) / std_dev
        
        if abs(z_score) > 2.0:
            direction = Direction.UP if z_score > 0 else Direction.DOWN
            label_suffix = dim_val if dim_val else f"{val}"
            
            insights.append(Insight(
                insight_type=InsightType.OUTLIER,
                severity=Severity.HIGH if abs(z_score) > 3 else Severity.MEDIUM,
                label=f"outlier_{label_suffix}".lower().replace(" ", "_"),
                headline=f"{dim_val or 'A value'} is {abs(z_score):.1f}σ {'above' if z_score > 0 else 'below'} average",
                metric_value=val,
                metric_formatted=_format_number(val),
                comparison_value=mean,
                comparison_formatted=_format_number(mean),
                direction=direction,
                dimension=dimension_key,
                dimension_value=dim_val,
                confidence=min(1.0, (abs(z_score) / 4.0) * (min(len(values), 30) / 30.0)),
            ))
    
    return insights


def _compare_to_baseline(
    data: list[dict[str, Any]],
    baseline_data: list[dict[str, Any]],
    metric_key: str,
    current_total: Optional[float],
) -> list[Insight]:
    """Compare current data against a baseline period."""
    insights = []
    
    baseline_total = _compute_total(baseline_data, metric_key)
    
    if current_total is not None and baseline_total is not None and baseline_total > 0:
        change_pct = ((current_total - baseline_total) / baseline_total) * 100
        direction = Direction.UP if change_pct > 0 else Direction.DOWN if change_pct < 0 else Direction.FLAT
        
        severity = Severity.LOW
        if abs(change_pct) > 20:
            severity = Severity.HIGH
        elif abs(change_pct) > 10:
            severity = Severity.MEDIUM
        
        insights.append(Insight(
            insight_type=InsightType.COMPARISON,
            severity=severity,
            label="period_comparison",
            headline=f"{_format_label(metric_key)} is {'up' if change_pct > 0 else 'down'} {abs(change_pct):.1f}% vs previous period",
            metric_value=current_total,
            metric_formatted=_format_number(current_total),
            comparison_value=baseline_total,
            comparison_formatted=_format_number(baseline_total),
            change_pct=change_pct,
            direction=direction,
        ))
    
    return insights


def _analyze_trend(
    data: list[dict[str, Any]],
    metric_key: str,
    time_col: Optional[str] = None,
) -> list[Insight]:
    """
    Analyze time-series direction using simple linear regression.
    """
    insights = []
    
    # Sort by time dimension if known
    sorted_data = data
    if time_col:
        # Check if time_col exists in the first row to confirm
        if data and _extract_dimension_value(data[0], time_col):
             sorted_data = sorted(data, key=lambda row: _extract_dimension_value(row, time_col) or "")

    values = []
    for row in sorted_data:
        val = _extract_numeric(row, metric_key)
        if val is not None:
            values.append(val)
    
    if len(values) < 3:
        return insights
    
    # Simple linear regression: slope of y = mx + b
    n = len(values)
    x_vals = list(range(n))
    x_mean = sum(x_vals) / n
    y_mean = sum(values) / n
    
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, values))
    denominator = sum((x - x_mean) ** 2 for x in x_vals)
    
    if denominator == 0:
        return insights
    
    slope = numerator / denominator
    
    # Normalize slope to percentage of mean
    if y_mean != 0:
        normalized_slope = (slope / y_mean) * 100
    else:
        normalized_slope = 0
    
    # Determine direction
    abs_slope = abs(normalized_slope)
    
    if abs_slope <= 0.5:
        direction = Direction.FLAT
        headline = f"{_format_label(metric_key)} is flat ({normalized_slope:.1f}%)"
        severity = Severity.LOW
    elif abs_slope <= 2.0:
        direction = Direction.UP if normalized_slope > 0 else Direction.DOWN
        trend = "mild upward" if normalized_slope > 0 else "mild downward"
        headline = f"{_format_label(metric_key)} shows a {trend} trend ({normalized_slope:.1f}%)"
        severity = Severity.LOW
    else:
        direction = Direction.UP if normalized_slope > 0 else Direction.DOWN
        trend = "upward" if normalized_slope > 0 else "downward"
        headline = f"{_format_label(metric_key)} is trending {trend} ({normalized_slope:.1f}%)"
        severity = Severity.HIGH if abs_slope > 10 else Severity.MEDIUM
    
    # R² for confidence
    ss_res = sum((y - (slope * x + (y_mean - slope * x_mean))) ** 2 for x, y in zip(x_vals, values))
    ss_tot = sum((y - y_mean) ** 2 for y in values)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    
    insights.append(Insight(
        insight_type=InsightType.TREND,
        severity=severity,
        label="trend_direction",
        headline=headline,
        direction=direction,
        change_pct=normalized_slope,
        confidence=max(0.0, min(1.0, r_squared)),
    ))
    
    return insights


# =============================================================================
# HELPERS
# =============================================================================

def _extract_numeric(row: dict[str, Any], metric_key: str) -> Optional[float]:
    """Extract a numeric value from a row, trying exact key and fuzzy match."""
    # Exact match
    if metric_key in row:
        return _to_float(row[metric_key])
    
    # Try with common prefixes stripped/added
    for key, val in row.items():
        if key.endswith(f".{metric_key}") or metric_key.endswith(f".{key}"):
            return _to_float(val)
    
    return None


def _extract_dimension_value(row: dict[str, Any], dimension_key: str) -> Optional[str]:
    """Extract a dimension value from a row."""
    if dimension_key in row:
        return str(row[dimension_key])
    
    for key, val in row.items():
        if key.endswith(f".{dimension_key}") or dimension_key.endswith(f".{key}"):
            return str(val)
    
    return None


def _to_float(val: Any) -> Optional[float]:
    """Safely convert a value to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.replace(",", ""))
        except ValueError:
            return None
    return None


def _format_number(value: float) -> str:
    """Format a number for human display."""
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    elif abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    elif abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    elif isinstance(value, float) and value != int(value):
        return f"{value:,.2f}"
    else:
        return f"{int(value):,}"


def _format_label(key: str) -> str:
    """Format a column key into a human-readable label."""
    if "." in key:
        key = key.split(".")[-1]
    return key.replace("_", " ").title()
