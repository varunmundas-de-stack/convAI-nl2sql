"""
Visual Spec Generator

WHAT IT DOES:
- Translates data + insights into a declarative visual specification
- One format. Always. A machine-readable VisualSpec object.
- The spec describes WHAT to show, not HOW to render it.

WHAT IT OUTPUTS:
- Chart type + data mapping
- Annotations derived from insights
- Color emphasis rules (which data points to highlight)
- Markers for outliers, trends, thresholds
- Title, subtitle, axis labels
"""

import logging
from typing import Any, Optional, Union
from pydantic import BaseModel, Field
from enum import Enum

from app.services.insight_engine import InsightResult, Direction, Severity, InsightType

logger = logging.getLogger(__name__)

# Constants
MAX_TITLE_LENGTH = 80
TABLE_THRESHOLD = 20
AXIS_TICK_COUNT = 5  # Target number of ticks for numeric axes


# =============================================================================
# SPEC TYPES
# =============================================================================

class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    NUMBER_CARD = "number_card"
    TABLE = "table"
    STACKED_BAR = "stacked_bar"
    HORIZONTAL_BAR = "horizontal_bar"


class EmphasisLevel(str, Enum):
    NONE = "none"
    SUBTLE = "subtle"       # Slightly highlighted
    STRONG = "strong"       # Clearly highlighted
    CRITICAL = "critical"   # Demands attention


class MarkerType(str, Enum):
    OUTLIER = "outlier"
    TREND_LINE = "trend_line"
    THRESHOLD = "threshold"
    ANNOTATION = "annotation"
    PEAK = "peak"
    TROUGH = "trough"


class ColorPalette:
    """Standard color palette for visuals."""
    PRIMARY = "#3b82f6"     # Blue
    POSITIVE = "#10b981"    # Green
    NEGATIVE = "#ef4444"    # Red
    WARNING = "#f59e0b"     # Amber
    MUTED = "#94a3b8"       # Slate
    NEUTRAL = "#64748b"     # Gray


# =============================================================================
# SPEC MODELS
# =============================================================================


class DataSeries(BaseModel):
    """A single data series to be plotted."""
    label: str
    values: list[Any]
    emphasis: EmphasisLevel = EmphasisLevel.NONE
    color_hint: Optional[str] = None  # Semantic hint: "positive", "negative", "primary", "muted"
    point_emphasis: Optional[list[EmphasisLevel]] = None
    point_colors: Optional[list[Optional[str]]] = None  # Per-point color mapping (e.g., ["#ff0000", "#00ff00"])


class Axis(BaseModel):
    """
    Axis specification.
    
    The 'values' field contains:
    - For categorical/time axes: Explicit tick labels (e.g., ["Jan", "Feb", "Mar"])
    - For numeric/linear axes: Computed tick positions (e.g., [0, 500, 1000, 1500, 2000])
    
    Note: For numeric axes, values are TICK POSITIONS, not the data itself.
    The actual data points are in series.values.
    
    Example:
        Data points: [2100, 2500, 2800]
        axis.values: [0, 500, 1000, 1500, 2000, 2500, 3000] (nice round numbers)
        series.values: [2100, 2500, 2800] (actual data)
    """
    label: str
    values: Optional[list[Any]] = None  # Categorical labels OR numeric tick positions
    format: Optional[str] = None  # "number", "currency", "percent", "date"
    axis_type: Optional[str] = None  # "time", "categorical", "linear" - helps frontend choose scale


class Marker(BaseModel):
    """An annotation or marker on the chart."""
    marker_type: MarkerType
    label: str
    position: Optional[Any] = None     # x-value, index, or category
    value: Optional[float] = None      # y-value
    emphasis: EmphasisLevel = EmphasisLevel.SUBTLE


class InsightAnnotation(BaseModel):
    """A machine-readable insight annotation for the visual."""
    text: str
    severity: Severity
    direction: Optional[Direction] = None
    position: Optional[str] = None  # "header", "footer", "inline", "tooltip"


class VisualSpec(BaseModel):
    """
    Complete declarative visual specification.
    
    This is the contract between backend intelligence and frontend rendering.
    The frontend receives this and decides HOW to render it.
    """
    # What to draw
    chart_type: ChartType
    
    # Data
    x_axis: Optional[Axis] = None
    y_axis: Optional[Axis] = None
    series: list[DataSeries] = Field(default_factory=list)
    
    # For number cards
    primary_value: Optional[str] = None
    primary_label: Optional[str] = None
    secondary_value: Optional[str] = None
    secondary_label: Optional[str] = None
    direction: Optional[Direction] = None
    
    # For tables
    columns: Optional[list[str]] = None
    rows: Optional[list[dict[str, Any]]] = None
    
    # Annotations from insights
    title: str = ""
    subtitle: Optional[str] = None
    annotations: list[InsightAnnotation] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    
    # Metadata
    total_rows: int = 0
    metric: Optional[str] = None
    empty: bool = False
    trend_slope: Optional[float] = None  # For trend visuals: normalized slope percentage





# =============================================================================
# GENERATOR
# =============================================================================

def generate_visual_spec(
    data: list[dict[str, Any]],
    insights: InsightResult,  # InsightResult or RefinedInsightResult (duck-typed for compatibility)
    chart_type_hint: Optional[str] = None,
    query: Optional[str] = None,
) -> VisualSpec:
    """
    Generate a declarative visual specification.
    
    This is the ONLY public function.
    
    Args:
        data: Raw query result rows
        insights: InsightResult or RefinedInsightResult from insight engine/refiner
        chart_type_hint: Suggested chart type from intent (e.g., "bar_chart", "line_chart", "pie_chart", 
                        "number_card", "table", "horizontal_bar_chart", "stacked_bar_chart"). Can be overridden.
        query: Original NL query for title generation. If None, title will be generated from metric/dimensions.
        
    Returns:
        VisualSpec — declarative spec for the frontend to render
        
    Raises:
        Exception: If spec generation fails critically (logged but not raised for non-fatal errors)
    """
    logger.info(f"Generating visual spec: {len(data)} rows, hint={chart_type_hint}")
    
    # Resolve chart type
    chart_type = _resolve_chart_type(chart_type_hint, insights, data)
    
    # Handle empty data
    if not data:
        return VisualSpec(
            chart_type=chart_type,
            title=_make_title(query, insights),
            empty=True,
            total_rows=0,
            metric=insights.metric,
            annotations=[InsightAnnotation(
                text="No data returned for this query",
                severity=Severity.MEDIUM,
                position="header",
            )],
        )
    
    # Dispatch to type-specific builder
    if chart_type == ChartType.NUMBER_CARD:
        spec = _build_number_card_spec(data, insights)
    elif chart_type == ChartType.TABLE:
        spec = _build_table_spec(data, insights)
    elif chart_type in (ChartType.BAR, ChartType.HORIZONTAL_BAR, ChartType.STACKED_BAR):
        spec = _build_bar_spec(data, insights, chart_type)
    elif chart_type == ChartType.LINE:
        spec = _build_line_spec(data, insights)
    elif chart_type == ChartType.PIE:
        spec = _build_pie_spec(data, insights)
    else:
        spec = _build_table_spec(data, insights)
    
    # Always attach the full raw data so the frontend table-view gets ALL columns,
    # not just the x-axis dim + metric the chart uses.
    # (TABLE spec already populates these; all other builders leave them None.)
    if spec.columns is None and data:
        spec.columns = list(data[0].keys())
        spec.rows = data

    # Enrich with insights
    spec.title = _make_title(query, insights)
    spec.subtitle = _make_subtitle(insights)
    spec.annotations = _insights_to_annotations(insights)
    spec.markers = _insights_to_markers(insights)
    spec.total_rows = len(data)
    spec.metric = insights.metric

    logger.info(f"Visual spec generated: chart_type={chart_type}, {len(spec.annotations)} annotations, {len(spec.markers)} markers")
    return spec



# =============================================================================
# CHART TYPE RESOLUTION
# =============================================================================

def _resolve_chart_type(hint: Optional[str], insights: InsightResult, data: list) -> ChartType:
    """Resolve the chart type from hint, intent, and data shape."""
    
    # If the query returns more than 2 columns (e.g. multiple dimensions + a metric),
    # our simple 2D charts (bar, pie, single-line) will drop data. Force a table view.
    if data and len(data[0].keys()) > 2:
        return ChartType.TABLE

    # Direct mapping from hint
    hint_map = {
        "bar_chart": ChartType.BAR,
        "line_chart": ChartType.LINE,
        "pie_chart": ChartType.PIE,
        "number_card": ChartType.NUMBER_CARD,
        "table": ChartType.TABLE,
        "horizontal_bar_chart": ChartType.HORIZONTAL_BAR,
        "stacked_bar_chart": ChartType.STACKED_BAR,
    }
    
    if hint and hint in hint_map:
        return hint_map[hint]
    
    # Auto-detect from data shape
    if len(data) == 1 and not insights.dimensions:
        return ChartType.NUMBER_CARD
    
    # Check intent_type safely (may not exist on all insight types)
    intent_type = getattr(insights, 'intent_type', None)
    if intent_type == "trend":
        return ChartType.LINE
    
    if intent_type == "distribution":
        return ChartType.PIE
    
    if intent_type == "ranking":
        return ChartType.HORIZONTAL_BAR
    
    if len(data) > TABLE_THRESHOLD:
        return ChartType.TABLE
    
    return ChartType.BAR


# =============================================================================
# SPEC BUILDERS (type-specific)
# =============================================================================

def _build_number_card_spec(data: list[dict], insights: InsightResult) -> VisualSpec:
    """Build a number card spec."""
    spec = VisualSpec(chart_type=ChartType.NUMBER_CARD)
    
    spec.primary_value = insights.total_formatted or "N/A"
    spec.primary_label = _clean_label(insights.metric) if insights.metric else "Value"
    
    # If there's a comparison insight, add secondary value
    for insight in insights.insights:
        if insight.insight_type == InsightType.COMPARISON:
            change_pct = insight.change_pct if insight.change_pct is not None else 0.0
            spec.secondary_value = f"{'+' if change_pct > 0 else ''}{change_pct:.1f}%"
            spec.secondary_label = "vs previous period"
            spec.direction = insight.direction
            break
    
    return spec


def _build_table_spec(data: list[dict], insights: InsightResult) -> VisualSpec:
    """Build a table spec."""
    spec = VisualSpec(chart_type=ChartType.TABLE)
    
    if data:
        # Keep original column names (not cleaned) so they match the row dict keys
        # Frontend will handle display formatting
        spec.columns = list(data[0].keys())
        spec.rows = data
    
    return spec


def _build_bar_spec(data: list[dict], insights: InsightResult, chart_type: ChartType) -> VisualSpec:
    """Build a bar chart spec."""
    spec = VisualSpec(chart_type=chart_type)
    
    metric_key = insights.metric or ""
    dim_key = insights.dimensions[0] if insights.dimensions and len(insights.dimensions) > 0 else None
    
    # Extract x-axis (dimension values) and y-axis (metric values)
    x_values = []
    y_values = []
    
    for row in data:
        x_val = _get_dim_value(row, dim_key) if dim_key else str(len(x_values))
        y_val = _get_metric_value(row, metric_key)
        x_values.append(x_val)
        y_values.append(y_val)
    
    # Determine axis type based on dimension
    axis_type = "categorical"
    if dim_key and any(kw in dim_key.lower() for kw in ["date", "time", "month", "year", "quarter"]):
        axis_type = "time"
    
    spec.x_axis = Axis(
        label=_clean_label(dim_key) if dim_key else "Category",
        values=x_values,
        axis_type=axis_type,
    )
    spec.y_axis = Axis(
        label=_clean_label(metric_key),
        values=_compute_axis_range(y_values),
        format="number",
        axis_type="linear",
    )
    
    # Determine emphasis per bar based on insights
    emphasis_map = _build_emphasis_map(insights, x_values)
    
    # Determine contextual colors per bar based on insights
    color_map = _build_color_map(insights, x_values)
    
    series = DataSeries(
        label=_clean_label(metric_key),
        values=y_values,
        emphasis=EmphasisLevel.NONE,
        color_hint="primary",
        point_emphasis=[emphasis_map.get(x, EmphasisLevel.NONE) for x in x_values],
        point_colors=[color_map.get(x) for x in x_values] if any(color_map.values()) else None,
    )
    spec.series = [series]
    
    # Populate primary/secondary values for non-table visuals
    if insights.total_value is not None:
        spec.primary_value = insights.total_formatted
        spec.primary_label = f"Total {_clean_label(metric_key)}"
        
        # If there's a top contributor, add as secondary
        for insight in insights.insights:
            if insight.label == "top_contributor" and insight.dimension_value:
                spec.secondary_value = insight.metric_formatted or ""
                spec.secondary_label = f"{insight.dimension_value} (Top)"
                break
    
    return spec


# Granularity names Cube appends to time dimension keys (e.g. invoice_date.week)
_GRANULARITY_SUFFIXES: dict[str, str] = {
    "day":     "Day",
    "week":    "Week",
    "month":   "Month",
    "quarter": "Quarter",
    "year":    "Year",
}


def _resolve_time_dim_key(
    dim_key: Optional[str],
    sample_row: dict,
) -> tuple[Optional[str], str]:
    """
    Detect the granularity-suffixed Cube key for a time dimension.

    Cube stores time-bucketed rows under a key like::

        fact_secondary_sales.invoice_date.week
        fact_secondary_sales.invoice_date.month

    rather than the bare ``invoice_date`` field.  This helper scans the
    first data row for such a key and returns:

    * the exact dict key to use when extracting x-values
    * a human-readable axis label ("Week", "Month", …, or "Time" as fallback)

    Two-pass strategy
    -----------------
    Pass 1 — expected pattern: look for ``{dim_key}.{granularity}`` in the row.
    Pass 2 — full-row scan: if dim_key is a group_by dimension (e.g. pack_size)
             rather than the time dimension, pass 1 finds nothing. Scan every
             row key for any key ending with a known granularity suffix and use
             the first match. This covers trend+group_by queries where
             ``insights.dimensions[0]`` is the group_by field, not the time field.
    """
    if not sample_row:
        return dim_key, "Time"

    # Pass 1: expected pattern using dim_key prefix
    if dim_key:
        for suffix, label in _GRANULARITY_SUFFIXES.items():
            candidate = f"{dim_key}.{suffix}"
            if candidate in sample_row:
                return candidate, label

    # Pass 2: full-row scan — finds invoice_date.week regardless of dim_key
    for key in sample_row:
        for suffix, label in _GRANULARITY_SUFFIXES.items():
            if key.endswith(f".{suffix}"):
                return key, label

    # No granularity suffix present — use the base key, generic label
    return dim_key, "Time"

def _format_time_label(iso_value: str, granularity_label: str) -> str:
    """
    Format a raw Cube ISO timestamp into a granularity-aware display label.

    Cube returns time-bucket keys as full ISO strings regardless of granularity,
    e.g. ``"2026-01-26T00:00:00.000"`` for a week bucket.  This converts them
    to the most readable form for the chosen granularity:

    ========= ======================== ==========
    Granularity  Input                   Output
    ========= ======================== ==========
    day        2026-01-26T00:00:00.000  Jan 26
    week       2026-01-26T00:00:00.000  Jan 26
    month      2026-02-01T00:00:00.000  Feb '26
    quarter    2026-01-01T00:00:00.000  Q1 2026
    year       2026-01-01T00:00:00.000  2026
    ========= ======================== ==========
    """
    from datetime import datetime

    try:
        # Cube timestamps: "2026-01-26T00:00:00.000" or "2026-01-26T00:00:00"
        clean = iso_value.split(".")[0]          # strip milliseconds
        dt = datetime.fromisoformat(clean)
    except (ValueError, AttributeError):
        return iso_value  # unknown format — return as-is

    g = granularity_label.lower()
    if g in ("day", "week"):
        return dt.strftime("%b %d")              # "Jan 26"
    elif g == "month":
        return dt.strftime("%b '%y")             # "Feb '26"
    elif g == "quarter":
        q = (dt.month - 1) // 3 + 1
        return f"Q{q} {dt.year}"                 # "Q1 2026"
    elif g == "year":
        return str(dt.year)                       # "2026"
    else:
        return dt.strftime("%b %d, %Y")          # fallback


def _build_line_spec(data: list[dict], insights: InsightResult) -> VisualSpec:
    """Build a line chart spec."""
    spec = VisualSpec(chart_type=ChartType.LINE)

    metric_key = insights.metric or ""
    dim_key = insights.dimensions[0] if insights.dimensions and len(insights.dimensions) > 0 else None

    # Resolve the exact Cube key (may include granularity suffix, e.g. invoice_date.week)
    # and derive the human-readable x-axis label from it.
    sample_row = data[0] if data else {}
    time_key, x_label = _resolve_time_dim_key(dim_key, sample_row)

    x_values = []
    y_values = []

    for row in data:
        x_val = _get_dim_value(row, time_key) if time_key else str(len(x_values))
        y_val = _get_metric_value(row, metric_key)
        x_values.append(x_val)
        y_values.append(y_val)

    # Format raw ISO timestamps into granularity-aware display labels
    x_values = [_format_time_label(v, x_label) for v in x_values]

    spec.x_axis = Axis(
        label=x_label,
        values=x_values,
        format="date",
        axis_type="time",
    )
    spec.y_axis = Axis(
        label=_clean_label(metric_key),
        values=_compute_axis_range(y_values),
        format="number",
        axis_type="linear",
    )

    # Determine color hint and trend slope from trend insight
    color_hint = "primary"
    trend_slope = None
    for insight in insights.insights:
        if insight.insight_type == InsightType.TREND:
            if insight.direction == Direction.UP:
                color_hint = "positive"
            elif insight.direction == Direction.DOWN:
                color_hint = "negative"
            if insight.change_pct is not None:
                trend_slope = insight.change_pct
            break

    spec.series = [DataSeries(
        label=_clean_label(metric_key),
        values=y_values,
        color_hint=color_hint,
    )]

    if trend_slope is not None:
        spec.trend_slope = trend_slope

    if insights.total_value is not None:
        spec.primary_value = insights.total_formatted
        spec.primary_label = f"Total {_clean_label(metric_key)}"

    return spec


def _build_pie_spec(data: list[dict], insights: InsightResult) -> VisualSpec:
    """Build a pie chart spec."""
    spec = VisualSpec(chart_type=ChartType.PIE)
    
    metric_key = insights.metric or ""
    dim_key = insights.dimensions[0] if insights.dimensions and len(insights.dimensions) > 0 else None
    
    labels = []
    values = []
    
    for row in data:
        label = _get_dim_value(row, dim_key) if dim_key else str(len(labels))
        val = _get_metric_value(row, metric_key)
        labels.append(label)
        values.append(val)
    
    spec.x_axis = Axis(label="Category", values=labels)
    spec.series = [DataSeries(
        label=_clean_label(metric_key),
        values=values,
        color_hint="primary",
    )]
    
    return spec


# =============================================================================
# INSIGHT → ANNOTATION/MARKER CONVERSION
# =============================================================================

def _insights_to_annotations(insights: InsightResult) -> list[InsightAnnotation]:
    """Convert insights into visual annotations."""
    annotations = []
    
    for insight in insights.insights:
        # Skip low-severity headlines (they're already the title)
        if insight.insight_type == InsightType.HEADLINE and insight.severity == Severity.LOW:
            continue
        
        position = "footer"
        if insight.severity in (Severity.HIGH, Severity.CRITICAL):
            position = "header"
        elif insight.insight_type == InsightType.OUTLIER:
            position = "inline"
        
        annotations.append(InsightAnnotation(
            text=insight.headline,
            severity=insight.severity,
            direction=insight.direction if insight.direction != Direction.UNKNOWN else None,
            position=position,
        ))
    
    return annotations


def _insights_to_markers(insights: InsightResult) -> list[Marker]:
    """Convert insights into chart markers."""
    markers = []
    
    for insight in insights.insights:
        if insight.insight_type == InsightType.OUTLIER and insight.dimension_value:
            markers.append(Marker(
                marker_type=MarkerType.OUTLIER,
                label=insight.headline,
                position=insight.dimension_value,
                value=insight.metric_value,
                emphasis=EmphasisLevel.STRONG if insight.severity == Severity.HIGH else EmphasisLevel.SUBTLE,
            ))

            # Add threshold marker at mean value for outlier reference (only once)
            if insight.comparison_value is not None:
                has_threshold = any(m.marker_type == MarkerType.THRESHOLD for m in markers)
                if not has_threshold:
                    markers.append(Marker(
                        marker_type=MarkerType.THRESHOLD,
                        label=f"Average: {_format_number(insight.comparison_value)}",
                        value=insight.comparison_value,
                        emphasis=EmphasisLevel.SUBTLE,
                    ))
        
        elif insight.insight_type == InsightType.TREND:
            markers.append(Marker(
                marker_type=MarkerType.TREND_LINE,
                label=insight.headline,
                emphasis=EmphasisLevel.SUBTLE,
            ))
        
        elif insight.insight_type == InsightType.CONCENTRATION and insight.label == "top_contributor":
            markers.append(Marker(
                marker_type=MarkerType.ANNOTATION,
                label=insight.headline,
                position=insight.dimension_value,
                value=insight.metric_value,
                emphasis=EmphasisLevel.STRONG,
            ))
    
    return markers


# =============================================================================
# HELPERS
# =============================================================================

def _make_title(query: Optional[str], insights: InsightResult) -> str:
    """Generate a title for the visual."""
    if query:
        return query[:MAX_TITLE_LENGTH] if len(query) <= MAX_TITLE_LENGTH else query[:MAX_TITLE_LENGTH - 3] + "..."
    
    metric_label = _clean_label(insights.metric) if insights.metric else "Data"
    if insights.dimensions and len(insights.dimensions) > 0:
        dim_label = _clean_label(insights.dimensions[0])
        return f"{metric_label} by {dim_label}"
    return metric_label


def _make_subtitle(insights: InsightResult) -> Optional[str]:
    """Generate a subtitle from the primary insight."""
    if insights.primary_insight and insights.primary_insight.insight_type != InsightType.HEADLINE:
        return insights.primary_insight.headline
    return None


def _build_emphasis_map(insights: InsightResult, x_values: list) -> dict[str, EmphasisLevel]:
    """Map dimension values to emphasis levels based on insights."""
    emphasis = {}
    
    for insight in insights.insights:
        if insight.dimension_value and insight.dimension_value in x_values:
            if insight.severity in (Severity.HIGH, Severity.CRITICAL):
                emphasis[insight.dimension_value] = EmphasisLevel.STRONG
            elif insight.severity == Severity.MEDIUM:
                emphasis[insight.dimension_value] = EmphasisLevel.SUBTLE
    
    return emphasis


def _compute_axis_range(values: list[float], target_ticks: int = AXIS_TICK_COUNT) -> list[float]:
    """
    Compute nice axis tick positions for numeric data.
    
    Args:
        values: The data values to compute range for
        target_ticks: Target number of ticks (actual may vary)
        
    Returns:
        List of tick positions, e.g., [0, 500, 1000, 1500, 2000, 2500, 3000]
        
    Examples:
        [2100, 2500, 2800] -> [0, 500, 1000, 1500, 2000, 2500, 3000]
        [10, 20, 30] -> [0, 10, 20, 30, 40]
        [95, 98, 102] -> [90, 95, 100, 105, 110]
    """
    if not values or all(v == 0 for v in values):
        return [0, 1, 2, 3, 4, 5]
    
    min_val = min(values)
    max_val = max(values)
    
    # If all values are the same, create a range around that value
    if min_val == max_val:
        if min_val == 0:
            return [0, 1, 2, 3, 4, 5]
        center = min_val
        step = max(1, abs(center) * 0.1)
        return [center - step * 2, center - step, center, center + step, center + step * 2]
    
    # Calculate range
    data_range = max_val - min_val
    
    # For positive data, prefer starting from 0 to give full context
    # This helps users understand the actual magnitude of values
    if min_val >= 0:
        min_val = 0
    
    # Add padding to max (about 10-20% headroom)
    max_val = max_val * 1.1
    
    # Calculate nice step size
    raw_step = (max_val - min_val) / target_ticks
    
    # Round step to a "nice" number (1, 2, 5, 10, 20, 50, 100, etc.)
    magnitude = 10 ** (len(str(int(raw_step))) - 1)
    nice_step = magnitude
    
    if raw_step <= magnitude * 1:
        nice_step = magnitude * 1
    elif raw_step <= magnitude * 2:
        nice_step = magnitude * 2
    elif raw_step <= magnitude * 5:
        nice_step = magnitude * 5
    else:
        nice_step = magnitude * 10
    
    # Generate ticks
    ticks = []
    current = (min_val // nice_step) * nice_step  # Floor to step
    max_tick = ((max_val // nice_step) + 1) * nice_step  # Ceil to step
    
    while current <= max_tick:
        ticks.append(float(current))
        current += nice_step
    
    return ticks


def _get_dim_value(row: dict, dim_key: Optional[str]) -> str:
    """Extract dimension value from a row."""
    if not dim_key:
        return "N/A"
    if dim_key in row:
        return str(row[dim_key])
    for key in row:
        if key.endswith(f".{dim_key}") or dim_key.endswith(f".{key}"):
            return str(row[key])
    return "N/A"


def _get_metric_value(row: dict, metric_key: str) -> float:
    """Extract metric value from a row, returning 0.0 for missing or invalid values."""
    if metric_key in row:
        try:
            val = row[metric_key]
            if val is None:
                return 0.0
            return float(val)
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to convert metric '{metric_key}' value '{row[metric_key]}' to float: {e}")
            return 0.0
            
    for key in row:
        if key.endswith(f".{metric_key}") or metric_key.endswith(f".{key}"):
            try:
                val = row[key]
                if val is None:
                    return 0.0
                return float(val)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to convert metric '{key}' value '{row[key]}' to float: {e}")
                return 0.0
    
    logger.debug(f"Metric key '{metric_key}' not found in row, returning 0.0")
    return 0.0




def _clean_label(key: Optional[str]) -> str:
    """
    Clean label by removing common prefixes and formatting.
    
    Examples:
        "fact_secondary_sales.total_sales" -> "Total Sales"
        "dim_product.product_name" -> "Product Name"
        "total_sales" -> "Total Sales"
    """
    if not key:
        return "Value"
    
    # Strip common table prefixes (check for exact prefix or after dot)
    prefixes_to_strip = [
        "fact_secondary_sales.",
        "dim_product.",
        "dim_region.",
        "fact_",
        "dim_",
    ]
    
    for prefix in prefixes_to_strip:
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    
    # Remove remaining dots by taking the last segment
    if "." in key:
        key = key.split(".")[-1]
    
    # Format: replace underscores with spaces and title case
    return key.replace("_", " ").title()


def _build_color_map(insights: InsightResult, x_values: list) -> dict[str, Optional[str]]:
    """
    Build a color map for data points based on insights.
    
    Returns a dict mapping dimension values to color codes.
    """
    color_map: dict[str, Optional[str]] = {x: None for x in x_values}
    
    for insight in insights.insights:
        if not insight.dimension_value or insight.dimension_value not in x_values:
            continue
        
        # Top contributor -> highlight color
        if insight.label == "top_contributor":
            color_map[insight.dimension_value] = ColorPalette.POSITIVE
        
        # Outlier -> warning/danger color based on severity
        elif insight.insight_type == InsightType.OUTLIER:
            if insight.severity in (Severity.HIGH, Severity.CRITICAL):
                color_map[insight.dimension_value] = ColorPalette.NEGATIVE
            else:
                color_map[insight.dimension_value] = ColorPalette.WARNING
        
        # Bottom performer -> muted color
        elif insight.label == "bottom_performer":
            color_map[insight.dimension_value] = ColorPalette.MUTED
    
    return color_map



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
