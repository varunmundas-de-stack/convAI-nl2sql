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
from app.services.insights.pivot_utils import merge_dual_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Post-processing keys (formerly in growth_computer)
# ---------------------------------------------------------------------------
_GROWTH_KEY       = "growth_rate"
_PREVIOUS_KEY     = "previous_value"
_CONTRIBUTION_KEY = "contribution_pct"


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


# =============================================================================
# LAYER 1: DETERMINISTIC METRICS FACTS (pure math, no LLM)
# =============================================================================

class MetricsFact(BaseModel):
    """
    Layer 1 output: structured deterministic metrics computed from raw data.

    Every field is traceable to a specific row, formula, or threshold.
    No LLM is involved at this layer.
    """
    # Data coverage
    data_points_used: int = 0
    period_count: int = 0

    # Totals / central tendency
    total_value: Optional[float] = None
    mean: Optional[float] = None
    std_dev: Optional[float] = None
    coefficient_of_variation: Optional[float] = None  # std_dev / mean
    volatility_flag: bool = False  # True when CV > 0.3

    # Time-series growth metrics
    growth_rates: list[Optional[float]] = Field(default_factory=list)  # per-period % changes
    percent_change_latest: Optional[float] = None    # last period WoW/MoM/etc (%)
    percent_change_overall: Optional[float] = None   # first-to-last (%)
    growth_acceleration: Optional[float] = None      # Δ avg growth rate (positive = accelerating)
    is_accelerating: Optional[bool] = None
    consecutive_growth_periods: int = 0
    consecutive_decline_periods: int = 0
    largest_drop_period: Optional[str] = None
    largest_drop_pct: Optional[float] = None
    largest_gain_period: Optional[str] = None
    largest_gain_pct: Optional[float] = None

    # Trend classification (deterministic rule)
    trend_class: str = "unknown"
    # Possible values:
    #   "consistent_growth" | "consistent_decline" | "volatile" |
    #   "flat" | "demand_cooling" | "recovery" | "mixed" | "unknown"

    # Anomaly detection (z-score based)
    anomaly_flag: bool = False
    anomaly_periods: list[str] = Field(default_factory=list)
    z_scores: dict[str, float] = Field(default_factory=dict)  # label → z-score

    # Concentration (for grouped / ranked data)
    top_contributor: Optional[str] = None
    top_contributor_pct: Optional[float] = None
    top3_contributor_pct: Optional[float] = None
    concentration_flag: bool = False  # True when top contributor > 50%


# =============================================================================
# LAYER 2: RULE-BASED INSIGHT OBJECTS (business logic, no LLM)
# =============================================================================

class RuleInsight(BaseModel):
    """
    Layer 2 output: a business-logic-triggered finding.

    Each instance is traceable to:
    - A specific MetricsFact field  (triggered_by)
    - A named rule                  (message_key)
    No LLM is involved at this layer.
    """
    type: str           # "trend" | "comparative" | "alert" | "opportunity"
    severity: Severity
    message_key: str    # e.g. "sharp_decline", "consistent_growth", "high_dependency_risk"
    description: str    # deterministic template string (no LLM)
    context: dict[str, Any] = Field(default_factory=dict)  # raw supporting facts
    triggered_by: str   # which MetricsFact field fired this rule

    # Scores assigned by prioritization engine
    impact_score: float = 0.0    # magnitude × contribution_weight
    urgency_score: float = 0.0   # magnitude × severity_weight
    confidence_score: float = 1.0  # penalised for volatile / sparse data


class InsightResult(BaseModel):
    """Complete insight output from the engine."""
    # Summary
    total_rows: int = 0
    total_value: Optional[float] = None
    total_formatted: Optional[str] = None

    # Layer 1: Deterministic metric facts (pure math, no LLM)
    metrics_facts: Optional[MetricsFact] = None

    # Layer 2: Rule-based insight objects (business logic, no LLM)
    rule_insights: list[RuleInsight] = Field(default_factory=list)

    # Prioritized selection: top 3 by score + 1 risk + 1 opportunity
    top_insights: list[RuleInsight] = Field(default_factory=list)
    top_risk: Optional[RuleInsight] = None
    top_opportunity: Optional[RuleInsight] = None

    # Legacy computed insights (kept for backward-compat with visual spec generator)
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
    strategy: Optional[str] = None,
    comparison_data: Optional[list[dict[str, Any]]] = None,
) -> "InsightResult":
    """
    Analyze query results and produce machine-readable insights.

    This is the single entry point for all data transformation + analysis.

    Pipeline position:
        execute → generate_insights()  ← HERE (post-process then analyze)
        → refine_insights() → visual_spec_generator()

    Step 0 (internal): post-process raw Cube data by strategy
        SINGLE_TIME_SERIES  → inject growth_rate per row
        DUAL_QUERY          → merge comparison rows, inject previous_value + growth_rate
        CONTRIBUTION        → inject contribution_pct per row
        SINGLE_QUERY        → pass-through

    Args:
        data:            Primary Cube result rows
        intent:          Validated intent (current query)
        previous_qco:    Previous QCO (for context-aware insights)
        baseline_data:   Optional previous-period data (legacy param, same as comparison_data)
        strategy:        QueryStrategy value string — drives post-processing
        comparison_data: Secondary Cube rows (comparison period or total query)

    Returns:
        InsightResult with post-processed data and computed insights
    """
    # Resolve metric name early for logging
    _log_metric = (
        intent.metrics[0].name
        if hasattr(intent, "metrics") and intent.metrics
        else "?"
    )
    logger.info(f"Generating insights: {len(data)} rows, metric={_log_metric}")

    if not data:
        return InsightResult(
            insights=[],
            primary_insight=None,
            summary="No data found for the selected period."
        )

    # ------------------------------------------------------------------
    # Step 0: Post-process raw Cube data by strategy
    # ------------------------------------------------------------------
    secondary = comparison_data or baseline_data  # support both param names
    data = _post_process_by_strategy(data, secondary, strategy, intent)

    # ------------------------------------------------------------------
    # Extract key fields from intent — support both Pydantic model and dict
    # ------------------------------------------------------------------
    if hasattr(intent, 'model_dump'):
        intent_dict = intent.model_dump()
    elif isinstance(intent, dict):
        intent_dict = intent
    else:
        intent_dict = {}

    # metric_key: new Intent stores metrics as a list; fall back to legacy 'metric' flat field
    metrics_list = intent_dict.get("metrics") or []
    if metrics_list:
        first = metrics_list[0]
        metric_key = (first.get("name", "") if isinstance(first, dict) else getattr(first, "name", ""))
    else:
        metric_key = intent_dict.get("metric", "")  # legacy fallback

    # dimensions: group_by list
    dimensions = intent_dict.get("group_by") or []

    # intent_type: derive deterministically if not already present
    raw_intent_type = intent_dict.get("intent_type", "")
    if not raw_intent_type:
        try:
            from app.models.intent import derive_intent_type
            raw_intent_type = derive_intent_type(intent).value
        except Exception:
            raw_intent_type = ""
    intent_type = raw_intent_type.value if hasattr(raw_intent_type, "value") else str(raw_intent_type)

    # ------------------------------------------------------------------
    # Step 0b: Layer 1 — Deterministic metrics facts (no LLM)
    # ------------------------------------------------------------------
    metrics_facts = compute_metrics_facts(data, metric_key, dimensions, intent_type, intent_dict)

    # ------------------------------------------------------------------
    # Step 0c: Layer 2 — Rule-based insight objects (no LLM)
    # ------------------------------------------------------------------
    rule_insights = apply_insight_rules(metrics_facts, data, metric_key, dimensions)

    # ------------------------------------------------------------------
    # Step 0d: Score and prioritize (top 3 + 1 risk + 1 opportunity)
    # ------------------------------------------------------------------
    top_insights, top_risk, top_opportunity = _score_and_prioritize(rule_insights, metrics_facts)

    result = InsightResult(
        total_rows=len(data),
        metric=metric_key,
        dimensions=dimensions,
        intent_type=intent_type,
        has_previous_context=previous_qco is not None,
        metrics_facts=metrics_facts,
        rule_insights=rule_insights,
        top_insights=top_insights,
        top_risk=top_risk,
        top_opportunity=top_opportunity,
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
# POST-PROCESSING (formerly growth_computer.py)
# =============================================================================

def _post_process_by_strategy(
    data_a: list[dict[str, Any]],
    data_b: list[dict[str, Any]] | None,
    strategy: str | None,
    intent: Any,
) -> list[dict[str, Any]]:
    """
    Dispatch to the correct math function based on QueryStrategy.
    Called as Step 0 inside generate_insights() before any statistical analysis.
    """
    from app.services.cube.period_planner import QueryStrategy  # local import avoids circular

    if strategy == QueryStrategy.SINGLE_TIME_SERIES.value:
        return _compute_row_wise_growth(data_a, _metric_key(intent), _time_col_key(intent))

    if strategy == QueryStrategy.DUAL_QUERY.value:
        return merge_dual_query(data_a, data_b or [], _group_keys(intent), _metric_key(intent))

    if strategy == QueryStrategy.CONTRIBUTION.value:
        return _compute_contribution(data_a, data_b or [], _metric_key(intent))

    return data_a  # SINGLE_QUERY — pass-through


def _compute_row_wise_growth(
    data: list[dict[str, Any]],
    metric_key: str,
    time_col: str,
) -> list[dict[str, Any]]:
    """Row-wise growth between consecutive time buckets (SINGLE_TIME_SERIES)."""
    if not data:
        return []
    sorted_data = sorted(data, key=lambda r: r.get(time_col, "") or "")
    result: list[dict[str, Any]] = []
    for i, row in enumerate(sorted_data):
        new_row = dict(row)
        if i == 0:
            new_row[_GROWTH_KEY] = None
        else:
            curr = _pp_to_float(row.get(metric_key))
            prev = _pp_to_float(sorted_data[i - 1].get(metric_key))
            new_row[_GROWTH_KEY] = _pp_safe_growth(curr, prev)
        result.append(new_row)
    return result


def _merge_and_compute_growth(
    data_a: list[dict[str, Any]],
    data_b: list[dict[str, Any]],
    metric_key: str,
    group_keys: list[str],
) -> list[dict[str, Any]]:
    """Merge two period datasets and compute period-over-period growth (DUAL_QUERY)."""
    if not data_a:
        return []
    lookup_b: dict[tuple, float] = {}
    for row in data_b:
        key = _pp_group_key(row, group_keys)
        lookup_b[key] = _pp_to_float(row.get(metric_key)) or 0.0
    result: list[dict[str, Any]] = []
    for row in data_a:
        new_row = dict(row)
        key = _pp_group_key(row, group_keys)
        curr = _pp_to_float(row.get(metric_key))
        prev = lookup_b.get(key, 0.0)
        new_row[_PREVIOUS_KEY] = prev
        new_row[_GROWTH_KEY] = _pp_safe_growth(curr, prev)
        result.append(new_row)
    return result


def _compute_contribution(
    data: list[dict[str, Any]],
    total_data: list[dict[str, Any]],
    metric_key: str,
) -> list[dict[str, Any]]:
    """Compute each row's % share of the grand total (CONTRIBUTION)."""
    if not data:
        return []
    total = sum(_pp_to_float(r.get(metric_key)) or 0.0 for r in total_data)
    result: list[dict[str, Any]] = []
    for row in data:
        new_row = dict(row)
        value = _pp_to_float(row.get(metric_key))
        new_row[_CONTRIBUTION_KEY] = (value / total * 100.0) if total and value is not None else None
        result.append(new_row)
    return result


# --- intent field extractors --------------------------------------------------

def _metric_key(intent: Any) -> str:
    if hasattr(intent, "metrics") and intent.metrics:
        return intent.metrics[0].name
    if isinstance(intent, dict):
        return intent.get("metric", "")
    return ""


def _time_col_key(intent: Any) -> str:
    if hasattr(intent, "time") and intent.time:
        col = intent.time.dimension or ""
        return f"{col}.{intent.time.granularity}" if intent.time.granularity else col
    return ""


def _group_keys(intent: Any) -> list[str]:
    if hasattr(intent, "group_by"):
        return intent.group_by or []
    if isinstance(intent, dict):
        return intent.get("group_by", [])
    return []


# --- numeric helpers ----------------------------------------------------------

def _pp_to_float(val: Any) -> Optional[float]:
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


def _pp_safe_growth(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / prev


def _pp_group_key(row: dict[str, Any], group_keys: list[str]) -> tuple:
    return tuple(str(row.get(k, "")) for k in group_keys)


# =============================================================================
# LAYER 1: compute_metrics_facts — Deterministic metric computation
# =============================================================================

def compute_metrics_facts(
    data: list[dict[str, Any]],
    metric_key: str,
    dimensions: list[str],
    intent_type: str,
    intent_dict: dict[str, Any],
) -> MetricsFact:
    """
    Layer 1: Pure deterministic metric computation.  NO LLM.

    Computes: % changes, growth rates, std_dev, CV, z-scores,
    trend_class, growth_acceleration, concentration metrics.
    Every output field is traceable to a specific row or formula.
    """
    fact = MetricsFact(data_points_used=len(data))
    if not data:
        return fact

    values = [v for v in (_extract_numeric(row, metric_key) for row in data) if v is not None]
    if not values:
        return fact

    fact.period_count = len(values)
    fact.total_value = sum(values)

    # --- Statistical moments ---
    mean = fact.total_value / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0
    fact.mean = round(mean, 4)
    fact.std_dev = round(std_dev, 4)
    fact.coefficient_of_variation = round(std_dev / mean, 4) if mean != 0 else None
    fact.volatility_flag = (fact.coefficient_of_variation or 0.0) > 0.3

    # --- Z-score anomaly detection ---
    if std_dev > 0:
        for i, row in enumerate(data):
            val = _extract_numeric(row, metric_key)
            if val is None:
                continue
            z = round((val - mean) / std_dev, 3)
            label = _get_row_label(row, intent_dict, dimensions, i)
            fact.z_scores[label] = z
            if abs(z) > 2.0:
                fact.anomaly_periods.append(label)
        fact.anomaly_flag = len(fact.anomaly_periods) > 0

    # --- Time-series growth metrics (from _compute_row_wise_growth enrichment) ---
    raw_growth = [_pp_to_float(row.get(_GROWTH_KEY)) for row in data]
    valid_growth = [g for g in raw_growth if g is not None]

    if valid_growth:
        # Convert fraction → % for readability
        fact.growth_rates = [round(g * 100, 2) if g is not None else None for g in raw_growth]

        fact.percent_change_latest = round(valid_growth[-1] * 100, 2)

        if len(values) >= 2 and values[0] != 0:
            fact.percent_change_overall = round((values[-1] - values[0]) / values[0] * 100, 2)

        # Growth acceleration: compare avg growth of first half vs second half
        mid = max(1, len(valid_growth) // 2)
        first_half = valid_growth[:mid]
        second_half = valid_growth[mid:]
        if first_half and second_half:
            first_avg = sum(first_half) / len(first_half)
            second_avg = sum(second_half) / len(second_half)
            fact.growth_acceleration = round((second_avg - first_avg) * 100, 2)
            fact.is_accelerating = fact.growth_acceleration > 0

        # Consecutive streaks (at end of series)
        fact.consecutive_growth_periods = _count_consecutive(valid_growth, positive=True)
        fact.consecutive_decline_periods = _count_consecutive(valid_growth, positive=False)

        # Largest drop and gain
        for i, row in enumerate(data):
            gr = _pp_to_float(row.get(_GROWTH_KEY))
            if gr is None:
                continue
            gr_pct = gr * 100
            label = _get_row_label(row, intent_dict, dimensions, i)
            if fact.largest_drop_pct is None or gr_pct < fact.largest_drop_pct:
                fact.largest_drop_pct = round(gr_pct, 2)
                fact.largest_drop_period = label
            if fact.largest_gain_pct is None or gr_pct > fact.largest_gain_pct:
                fact.largest_gain_pct = round(gr_pct, 2)
                fact.largest_gain_period = label

        fact.trend_class = _classify_trend(valid_growth, fact.coefficient_of_variation or 0.0)

    # --- Concentration (for grouped / ranked data) ---
    if dimensions and len(data) > 1 and fact.total_value and fact.total_value > 0:
        dim_key = dimensions[0]
        scored = [
            (str(_extract_dimension_value(row, dim_key) or ""), _extract_numeric(row, metric_key) or 0.0)
            for row in data
        ]
        scored = [(n, v) for n, v in scored if n]
        scored.sort(key=lambda x: x[1], reverse=True)
        if scored:
            top_name, top_val = scored[0]
            fact.top_contributor = top_name
            fact.top_contributor_pct = round(top_val / fact.total_value * 100, 1)
            fact.concentration_flag = fact.top_contributor_pct > 50
            if len(scored) >= 3:
                top3_val = sum(v for _, v in scored[:3])
                fact.top3_contributor_pct = round(top3_val / fact.total_value * 100, 1)

    return fact


def _classify_trend(growth_rates: list[float], cv: float) -> str:
    """Deterministic trend classification from growth rates."""
    if not growth_rates:
        return "unknown"
    if cv > 0.5:
        return "volatile"

    positives = sum(1 for g in growth_rates if g > 0)
    negatives = sum(1 for g in growth_rates if g < 0)

    if positives == len(growth_rates):
        return "consistent_growth"
    if negatives == len(growth_rates):
        return "consistent_decline"

    if len(growth_rates) >= 3:
        mid = len(growth_rates) // 2
        first_avg = sum(growth_rates[:mid]) / mid
        last_avg = sum(growth_rates[mid:]) / len(growth_rates[mid:])
        if first_avg > 0.05 and last_avg < -0.05:
            return "demand_cooling"
        if first_avg < -0.05 and last_avg > 0.05:
            return "recovery"

    abs_avg = sum(abs(g) for g in growth_rates) / len(growth_rates)
    if abs_avg < 0.02:
        return "flat"

    return "mixed"


def _count_consecutive(growth_rates: list[float], positive: bool) -> int:
    """Count consecutive positive or negative growth at the END of the series."""
    count = 0
    for g in reversed(growth_rates):
        if positive and g > 0:
            count += 1
        elif not positive and g < 0:
            count += 1
        else:
            break
    return count


def _get_row_label(
    row: dict[str, Any],
    intent_dict: dict[str, Any],
    dimensions: list[str],
    fallback_index: int,
) -> str:
    """Get a human-readable label for a data row (used for anomaly / period IDs)."""
    td = intent_dict.get("time_dimension")
    if td:
        col = td.get("dimension", "") if isinstance(td, dict) else getattr(td, "dimension", "")
        if col:
            for key in row:
                if key == col or key.startswith(col + "."):
                    return str(row[key])
    for dim in dimensions:
        if dim in row:
            return str(row[dim])
    return str(fallback_index)


# =============================================================================
# LAYER 2: apply_insight_rules — Business logic rule engine
# =============================================================================

def apply_insight_rules(
    facts: MetricsFact,
    data: list[dict[str, Any]],
    metric_key: str,
    dimensions: list[str],
) -> list[RuleInsight]:
    """
    Layer 2: Apply deterministic business-logic rules to MetricsFact.  NO LLM.

    Each rule maps a named condition → a RuleInsight with a message_key.
    Rules are evaluated independently; multiple can trigger simultaneously.
    """
    rules: list[RuleInsight] = []

    # ── TREND RULES ──────────────────────────────────────────────────────────

    if facts.trend_class == "consistent_growth":
        rules.append(RuleInsight(
            type="trend",
            severity=Severity.MEDIUM,
            message_key="consistent_growth",
            description=f"Consistent growth for {facts.consecutive_growth_periods} consecutive period(s)",
            context={"consecutive_periods": facts.consecutive_growth_periods,
                     "percent_change_overall": facts.percent_change_overall},
            triggered_by="trend_class",
        ))

    if facts.trend_class == "consistent_decline":
        rules.append(RuleInsight(
            type="alert",
            severity=Severity.HIGH,
            message_key="consistent_decline",
            description=f"Declining for {facts.consecutive_decline_periods} consecutive period(s)",
            context={"consecutive_periods": facts.consecutive_decline_periods,
                     "percent_change_overall": facts.percent_change_overall},
            triggered_by="trend_class",
        ))

    if facts.percent_change_latest is not None and facts.percent_change_latest < -20:
        rules.append(RuleInsight(
            type="alert",
            severity=Severity.HIGH,
            message_key="sharp_decline",
            description=f"Sharp decline of {abs(facts.percent_change_latest):.1f}% in latest period",
            context={"change_pct": facts.percent_change_latest,
                     "period": facts.largest_drop_period},
            triggered_by="percent_change_latest",
        ))

    if facts.percent_change_latest is not None and facts.percent_change_latest > 20:
        rules.append(RuleInsight(
            type="opportunity",
            severity=Severity.MEDIUM,
            message_key="sharp_growth",
            description=f"Strong growth of {facts.percent_change_latest:.1f}% in latest period",
            context={"change_pct": facts.percent_change_latest,
                     "period": facts.largest_gain_period},
            triggered_by="percent_change_latest",
        ))

    if facts.volatility_flag:
        rules.append(RuleInsight(
            type="alert",
            severity=Severity.MEDIUM,
            message_key="high_volatility",
            description=(f"High volatility detected "
                         f"(CV={facts.coefficient_of_variation:.2f}, σ={facts.std_dev:.1f})"),
            context={"coefficient_of_variation": facts.coefficient_of_variation,
                     "std_dev": facts.std_dev},
            triggered_by="volatility_flag",
        ))

    if facts.trend_class == "demand_cooling":
        rules.append(RuleInsight(
            type="alert",
            severity=Severity.HIGH,
            message_key="demand_cooling",
            description="Growth reversal after peak — possible demand cooling",
            context={"trend": "demand_cooling",
                     "growth_acceleration": facts.growth_acceleration},
            triggered_by="trend_class",
        ))

    if facts.trend_class == "recovery":
        rules.append(RuleInsight(
            type="opportunity",
            severity=Severity.MEDIUM,
            message_key="recovery",
            description="Recovery trend detected after prior decline",
            context={"trend": "recovery",
                     "growth_acceleration": facts.growth_acceleration},
            triggered_by="trend_class",
        ))

    if (facts.is_accelerating is not None
            and not facts.is_accelerating
            and (facts.percent_change_latest or 0) > 0):
        rules.append(RuleInsight(
            type="alert",
            severity=Severity.MEDIUM,
            message_key="growth_deceleration",
            description="Growth is slowing — positive direction but decelerating momentum",
            context={"growth_acceleration": facts.growth_acceleration,
                     "percent_change_latest": facts.percent_change_latest},
            triggered_by="growth_acceleration",
        ))

    # ── CONCENTRATION / COMPARATIVE RULES ────────────────────────────────────

    if facts.concentration_flag and facts.top_contributor_pct is not None:
        if facts.top_contributor_pct > 70:
            rules.append(RuleInsight(
                type="alert",
                severity=Severity.HIGH,
                message_key="extreme_concentration",
                description=(f"{facts.top_contributor} accounts for "
                             f"{facts.top_contributor_pct:.0f}% — extreme dependency risk"),
                context={"contributor": facts.top_contributor,
                         "pct": facts.top_contributor_pct},
                triggered_by="concentration_flag",
            ))
        else:
            rules.append(RuleInsight(
                type="alert",
                severity=Severity.MEDIUM,
                message_key="high_dependency_risk",
                description=(f"{facts.top_contributor} accounts for "
                             f"{facts.top_contributor_pct:.0f}% — high concentration risk"),
                context={"contributor": facts.top_contributor,
                         "pct": facts.top_contributor_pct},
                triggered_by="top_contributor_pct",
            ))

    if (facts.top_contributor_pct is not None
            and facts.top_contributor_pct < 30
            and len(data) > 3):
        rules.append(RuleInsight(
            type="opportunity",
            severity=Severity.LOW,
            message_key="healthy_distribution",
            description=(f"Healthy spread — top contributor is only "
                         f"{facts.top_contributor_pct:.0f}%"),
            context={"top_pct": facts.top_contributor_pct,
                     "top3_pct": facts.top3_contributor_pct},
            triggered_by="top_contributor_pct",
        ))

    # ── ALERT RULES ──────────────────────────────────────────────────────────

    if facts.anomaly_flag:
        rules.append(RuleInsight(
            type="alert",
            severity=Severity.CRITICAL if len(facts.anomaly_periods) > 2 else Severity.HIGH,
            message_key="anomaly_detected",
            description=(f"Statistical anomaly in "
                         f"{len(facts.anomaly_periods)} period(s) "
                         f"(|z| > 2σ)"),
            context={"anomaly_periods": facts.anomaly_periods,
                     "z_scores": facts.z_scores},
            triggered_by="anomaly_flag",
        ))

    # Material risk: declining + high concentration
    if (facts.percent_change_latest is not None
            and facts.percent_change_latest < 0
            and facts.concentration_flag):
        rules.append(RuleInsight(
            type="alert",
            severity=Severity.CRITICAL,
            message_key="material_risk",
            description=(f"Negative growth ({facts.percent_change_latest:.1f}%) combined with "
                         f"high concentration ({facts.top_contributor_pct:.0f}%) — material risk"),
            context={"change_pct": facts.percent_change_latest,
                     "top_contributor_pct": facts.top_contributor_pct,
                     "top_contributor": facts.top_contributor},
            triggered_by="percent_change_latest+concentration_flag",
        ))

    return rules


# =============================================================================
# INSIGHT PRIORITIZATION ENGINE
# =============================================================================

def _score_and_prioritize(
    rule_insights: list[RuleInsight],
    metrics_fact: MetricsFact,
) -> tuple[list[RuleInsight], Optional[RuleInsight], Optional[RuleInsight]]:
    """
    Score every RuleInsight and return:
      - top_insights: top 3 by composite score (avoids user overwhelm)
      - top_risk:     highest-impact alert insight
      - top_opportunity: highest-impact opportunity insight

    Scores:
      impact_score  = magnitude × severity_weight × (1 + contribution_weight)
      urgency_score = magnitude × severity_weight
      confidence_score = penalised for volatile / sparse data
    """
    if not rule_insights:
        return [], None, None

    severity_weight = {
        Severity.CRITICAL: 1.0,
        Severity.HIGH: 0.75,
        Severity.MEDIUM: 0.5,
        Severity.LOW: 0.25,
    }

    magnitude = abs(
        metrics_fact.percent_change_latest
        or metrics_fact.percent_change_overall
        or 0.0
    ) / 100.0
    contribution = (metrics_fact.top_contributor_pct or 0.0) / 100.0
    data_consistency = 0.7 if metrics_fact.volatility_flag else 1.0

    for ri in rule_insights:
        sev_w = severity_weight.get(ri.severity, 0.5)
        ri.impact_score = round(magnitude * sev_w * (1.0 + contribution), 4)
        ri.urgency_score = round(magnitude * sev_w, 4)
        ri.confidence_score = round(data_consistency, 4)

    scored = sorted(
        rule_insights,
        key=lambda r: (r.impact_score + r.urgency_score) * r.confidence_score,
        reverse=True,
    )

    top_insights = scored[:3]
    risks = [r for r in scored if r.type == "alert"]
    opportunities = [r for r in scored if r.type == "opportunity"]

    return top_insights, (risks[0] if risks else None), (opportunities[0] if opportunities else None)


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
    """Format a number for human display using Indian numbering system."""
    if abs(value) >= 1_00_00_000:  # 1 crore
        return f"{value / 1_00_00_000:.1f}Cr"
    elif abs(value) >= 1_00_000:  # 1 lakh
        return f"{value / 1_00_000:.1f}L"
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
