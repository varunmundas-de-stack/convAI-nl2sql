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


class Axis(BaseModel):
    """Axis specification."""
    label: str
    values: Optional[list[Any]] = None
    format: Optional[str] = None  # "number", "currency", "percent", "date"


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


class VisualSpecError(Exception):
    """Raised when visual spec generation fails."""
    pass


# =============================================================================
# GENERATOR
# =============================================================================

def generate_visual_spec(
    data: list[dict[str, Any]],
    insights: Any,  # InsightResult or RefinedInsightResult (duck-typed)
    chart_type_hint: Optional[str] = None,
    query: Optional[str] = None,
) -> VisualSpec:
    """
    Generate a declarative visual specification.
    
    This is the ONLY public function.
    
    Args:
        data: Raw query result rows
        insights: InsightResult or RefinedInsightResult from insight engine/refiner
        chart_type_hint: Suggested chart type from intent (can be overridden)
        query: Original NL query for title generation
        
    Returns:
        VisualSpec — declarative spec for the frontend to render
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
    match chart_type:
        case ChartType.NUMBER_CARD:
            spec = _build_number_card_spec(data, insights)
        case ChartType.TABLE:
            spec = _build_table_spec(data, insights)
        case ChartType.BAR | ChartType.HORIZONTAL_BAR | ChartType.STACKED_BAR:
            spec = _build_bar_spec(data, insights, chart_type)
        case ChartType.LINE:
            spec = _build_line_spec(data, insights)
        case ChartType.PIE:
            spec = _build_pie_spec(data, insights)
        case _:
            spec = _build_table_spec(data, insights)
    
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
    
    if insights.intent_type == "trend":
        return ChartType.LINE
    
    if insights.intent_type == "distribution":
        return ChartType.PIE
    
    if insights.intent_type == "ranking":
        return ChartType.HORIZONTAL_BAR
    
    if len(data) > 20:
        return ChartType.TABLE
    
    return ChartType.BAR


# =============================================================================
# SPEC BUILDERS (type-specific)
# =============================================================================

def _build_number_card_spec(data: list[dict], insights: InsightResult) -> VisualSpec:
    """Build a number card spec."""
    spec = VisualSpec(chart_type=ChartType.NUMBER_CARD)
    
    spec.primary_value = insights.total_formatted or "N/A"
    spec.primary_label = _format_label(insights.metric) if insights.metric else "Value"
    
    # If there's a comparison insight, add secondary value
    for insight in insights.insights:
        if insight.insight_type == InsightType.COMPARISON:
            spec.secondary_value = f"{'+' if (insight.change_pct or 0) > 0 else ''}{insight.change_pct:.1f}%"
            spec.secondary_label = "vs previous period"
            spec.direction = insight.direction
            break
    
    return spec


def _build_table_spec(data: list[dict], insights: InsightResult) -> VisualSpec:
    """Build a table spec."""
    spec = VisualSpec(chart_type=ChartType.TABLE)
    
    if data:
        spec.columns = [_format_label(col) for col in data[0].keys()]
        spec.rows = data
    
    return spec


def _build_bar_spec(data: list[dict], insights: InsightResult, chart_type: ChartType) -> VisualSpec:
    """Build a bar chart spec."""
    spec = VisualSpec(chart_type=chart_type)
    
    metric_key = insights.metric or ""
    dim_key = insights.dimensions[0] if insights.dimensions else None
    
    # Extract x-axis (dimension values) and y-axis (metric values)
    x_values = []
    y_values = []
    
    for row in data:
        x_val = _get_dim_value(row, dim_key) if dim_key else str(len(x_values))
        y_val = _get_metric_value(row, metric_key)
        x_values.append(x_val)
        y_values.append(y_val)
    
    spec.x_axis = Axis(
        label=_format_label(dim_key) if dim_key else "Category",
        values=x_values,
    )
    spec.y_axis = Axis(
        label=_format_label(metric_key),
        format="number",
    )
    
    # Determine emphasis per bar based on insights
    emphasis_map = _build_emphasis_map(insights, x_values)
    
    series = DataSeries(
        label=_format_label(metric_key),
        values=y_values,
        emphasis=EmphasisLevel.NONE,
        color_hint="primary",
        point_emphasis=[emphasis_map.get(x, EmphasisLevel.NONE) for x in x_values],
    )
    spec.series = [series]
    
    return spec


def _build_line_spec(data: list[dict], insights: InsightResult) -> VisualSpec:
    """Build a line chart spec."""
    spec = VisualSpec(chart_type=ChartType.LINE)
    
    metric_key = insights.metric or ""
    dim_key = insights.dimensions[0] if insights.dimensions else None
    
    x_values = []
    y_values = []
    
    for row in data:
        x_val = _get_dim_value(row, dim_key) if dim_key else str(len(x_values))
        y_val = _get_metric_value(row, metric_key)
        x_values.append(x_val)
        y_values.append(y_val)
    
    spec.x_axis = Axis(
        label=_format_label(dim_key) if dim_key else "Time",
        values=x_values,
        format="date" if dim_key and "date" in dim_key.lower() else None,
    )
    spec.y_axis = Axis(
        label=_format_label(metric_key),
        format="number",
    )
    
    # Determine color hint from trend insight
    color_hint = "primary"
    for insight in insights.insights:
        if insight.insight_type == InsightType.TREND:
            if insight.direction == Direction.UP:
                color_hint = "positive"
            elif insight.direction == Direction.DOWN:
                color_hint = "negative"
    
    spec.series = [DataSeries(
        label=_format_label(metric_key),
        values=y_values,
        color_hint=color_hint,
    )]
    
    return spec


def _build_pie_spec(data: list[dict], insights: InsightResult) -> VisualSpec:
    """Build a pie chart spec."""
    spec = VisualSpec(chart_type=ChartType.PIE)
    
    metric_key = insights.metric or ""
    dim_key = insights.dimensions[0] if insights.dimensions else None
    
    labels = []
    values = []
    
    for row in data:
        label = _get_dim_value(row, dim_key) if dim_key else str(len(labels))
        val = _get_metric_value(row, metric_key)
        labels.append(label)
        values.append(val)
    
    spec.x_axis = Axis(label="Category", values=labels)
    spec.series = [DataSeries(
        label=_format_label(metric_key),
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
        return query[:80] if len(query) <= 80 else query[:77] + "..."
    
    metric_label = _format_label(insights.metric) if insights.metric else "Data"
    if insights.dimensions:
        dim_label = _format_label(insights.dimensions[0])
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
    """Extract metric value from a row."""
    if metric_key in row:
        try:
            return float(row[metric_key])
        except (ValueError, TypeError):
            pass
    for key in row:
        if key.endswith(f".{metric_key}") or metric_key.endswith(f".{key}"):
            try:
                return float(row[key])
            except (ValueError, TypeError):
                pass
    # Fallback: first numeric
    for val in row.values():
        try:
            return float(val)
        except (ValueError, TypeError):
            continue
    return 0.0


def _format_label(key: Optional[str]) -> str:
    """Format a column key into a human-readable label."""
    if not key:
        return "Value"
    if "." in key:
        key = key.split(".")[-1]
    return key.replace("_", " ").title()
