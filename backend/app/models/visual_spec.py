"""
Visual Spec Models
"""

from typing import Any, Optional, Union
from pydantic import BaseModel, Field
from enum import Enum

from app.services.insights.insight_engine import Direction, Severity

class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    NUMBER_CARD = "number_card"
    TABLE = "table"
    STACKED_BAR = "stacked_bar"
    HORIZONTAL_BAR = "horizontal_bar"
    GROUPED_BAR = "grouped_bar"
    MULTI_LINE = "multi_line"
    COMPOUND_SECTIONS = "compound_sections"
    COMPOUND_SECTIONS_PARTIAL = "compound_sections_partial"


class EmphasisLevel(str, Enum):
    NONE = "none"
    SUBTLE = "subtle"
    STRONG = "strong"
    CRITICAL = "critical"


class MarkerType(str, Enum):
    OUTLIER = "outlier"
    TREND_LINE = "trend_line"
    THRESHOLD = "threshold"
    ANNOTATION = "annotation"
    PEAK = "peak"
    TROUGH = "trough"


class ColorPalette:
    PRIMARY = "#3b82f6"
    POSITIVE = "#10b981"
    NEGATIVE = "#ef4444"
    WARNING = "#f59e0b"
    MUTED = "#94a3b8"
    NEUTRAL = "#64748b"


class DataSeries(BaseModel):
    label: str
    values: list[Any]
    emphasis: EmphasisLevel = EmphasisLevel.NONE
    color_hint: Optional[str] = None
    point_emphasis: Optional[list[EmphasisLevel]] = None
    point_colors: Optional[list[Optional[str]]] = None


class SeriesConfig(BaseModel):
    key: str
    label: str


class PivotConfig(BaseModel):
    index_dimension: str
    stack_dimension: str
    stack_dimensions: Optional[list[str]] = None
    stack_keys: list[str]


class Axis(BaseModel):
    label: str
    values: Optional[list[Any]] = None
    format: Optional[str] = None
    axis_type: Optional[str] = None


class Marker(BaseModel):
    marker_type: MarkerType
    label: str
    position: Optional[Any] = None
    value: Optional[float] = None
    emphasis: EmphasisLevel = EmphasisLevel.SUBTLE


class InsightAnnotation(BaseModel):
    text: str
    severity: Severity
    direction: Optional[Direction] = None
    position: Optional[str] = None


class VisualSpec(BaseModel):
    chart_type: ChartType
    x_axis: Optional[Axis] = None
    y_axis: Optional[Axis] = None
    series: list[Any] = Field(default_factory=list)  # Accepts DataSeries or SeriesConfig
    pivot_config: Optional[PivotConfig] = None
    data: list[dict] = Field(default_factory=list)
    x_axis_key: Optional[str] = None
    
    primary_value: Optional[str] = None
    primary_label: Optional[str] = None
    secondary_value: Optional[str] = None
    secondary_label: Optional[str] = None
    direction: Optional[Direction] = None
    
    columns: Optional[list[str]] = None
    rows: Optional[list[dict[str, Any]]] = None
    
    title: str = ""
    subtitle: Optional[str] = None
    annotations: list[InsightAnnotation] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    
    total_rows: int = 0
    metric: Optional[str] = None
    empty: bool = False
    trend_slope: Optional[float] = None

    # Compound query specific fields
    sections: Optional[list[dict[str, Any]]] = None
    total_sections: Optional[int] = None
    completed_sections: Optional[int] = None
    pending_sections: Optional[int] = None
    is_partial: Optional[bool] = None
