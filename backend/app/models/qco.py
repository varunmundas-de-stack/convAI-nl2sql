"""
Query Context Object (QCO) - Lightweight conversational context for NL2SQL.

The QCO captures the resolved analytical parameters from the last successful
query, enabling follow-up queries like "now show by brand" or "drill into Mumbai".

It carries NO query results — only the resolved intent parameters.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


class FilterOperator(str, Enum):
    """Valid filter operators for QCO filters."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN_OR_EQUAL = "lte"


class QCOTimeRange(BaseModel):
    """Concrete resolved time range (always start/end dates, never a window name)."""
    start_date: str = Field(..., description="Resolved start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="Resolved end date in YYYY-MM-DD format")


class QCOFilter(BaseModel):
    """A resolved filter from the previous query."""
    dimension: str
    operator: str  # Keep as str for backward compatibility, but validate in resolver
    value: str | List[str]


class QCOMetric(BaseModel):
    """A single metric captured in the QCO (semantic names, not Cube IDs)."""
    name: str = Field(..., description="Semantic metric name, e.g. 'net_value'")
    aggregation: str = Field(default="sum", description="Aggregation function, e.g. 'sum', 'count', 'avg'")


class SlotMeta(BaseModel):
    """Metadata for tracking slot provenance in conversational context."""
    source: Literal["override", "carry_forward", "tombstone"] = Field(
        ...,
        description="How this slot value was determined in the current turn"
    )
    turn: int = Field(
        ...,
        description="Conversation turn when this slot was last set"
    )
    timestamp: datetime = Field(
        ...,
        description="When this slot metadata was created"
    )


class QueryContextObject(BaseModel):
    """
    Lightweight structured object capturing the resolved state of the last
    successful query.

    This is injected into the LLM prompt for follow-up queries and used
    by the intent merger to fill in missing fields.
    """
    # Schema version for migration support
    schema_version: int = Field(default=3, description="QCO schema version for backward compatibility")

    # The original natural language query
    original_query: str = Field(..., description="The original NL query that produced this context")

    # Core analytical parameters (all using semantic names, not Cube IDs)
    intent_type: str = Field(..., description="e.g. snapshot, trend, ranking, distribution")
    sales_scope: str = Field(..., description="PRIMARY or SECONDARY")

    # Full metrics list — mirrors the Intent.metrics format (semantic names)
    metrics: List[QCOMetric] = Field(
        ...,
        description="One or more metrics from the previous query, e.g. [{'name': 'net_value', 'aggregation': 'sum'}]",
        min_length=1,
    )

    @property
    def metric(self) -> str:
        """
        Backward-compat shim: returns the primary (first) metric name as a string.

        Used by drill_detector and any code that only needs to know the primary
        metric without caring about aggregation or multi-metric queries.
        """
        return self.metrics[0].name if self.metrics else ""

    # Dimensions
    group_by: Optional[List[str]] = Field(default=None, description="Semantic dimension names")

    # Time
    time_dimension: Optional[str] = Field(default=None, description="Semantic time dimension name, e.g. 'invoice_date'")
    time_granularity: Optional[str] = Field(default=None, description="day, week, month, quarter, year")
    time_range: Optional[QCOTimeRange] = Field(default=None, description="Concrete resolved date range")

    # Filters
    filters: Optional[List[QCOFilter]] = Field(default=None, description="Resolved filters")

    # Visualization
    visualization_type: Optional[str] = Field(default=None, description="e.g. bar_chart, line_chart, table")
    x_axis_labels: Optional[List[str]] = Field(default=None, description="Extracted X-axis labels from the retrieved data to provide context on available entities")

    # Limit
    limit: Optional[int] = Field(default=None)

    # Hierarchy state
    active_hierarchies: Optional[Dict[str, str]] = Field(
        default=None,
        description='Axis → current active dimension, e.g. {"geography": "zone", "product": "brand"}'
    )

    # New fields for agent architecture
    slot_metadata: Dict[str, SlotMeta] = Field(
        default_factory=dict,
        description="Per-slot provenance tracking for merge behavior"
    )
    turn_index: int = Field(
        default=0,
        description="Current conversation turn, incremented on each successful query"
    )
    parent_request_id: Optional[str] = Field(
        default=None,
        description="Set when this QCO was produced by a sub-query in a decomposed compound query"
    )

    # Cached agent results for context injection
    cached_scope_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Cached result from ScopeModule for selective re-execution"
    )
    cached_time_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Cached result from TimeModule for selective re-execution"
    )
    cached_metrics_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Cached result from MetricsModule for selective re-execution"
    )
    cached_dimensions_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Cached result from DimensionsModule for selective re-execution"
    )

    def to_prompt_context(self) -> str:
        """
        Format QCO as a human-readable context block for LLM prompt injection.

        This is deliberately concise — the LLM should understand the previous
        query state without being overwhelmed.
        """
        # Render metrics as a comma-separated list of "name (aggregation)" entries
        metrics_str = ", ".join(
            f"{m.name} ({m.aggregation})" for m in self.metrics
        )

        lines = [
            f"Previous Query: \"{self.original_query}\"",
            f"Previous Intent: {self.intent_type}",
            f"Previous Scope: {self.sales_scope}",
            f"Previous Metrics: {metrics_str}",
        ]

        if self.group_by:
            lines.append(f"Previous Group By: {', '.join(self.group_by)}")

        if self.time_dimension:
            lines.append(f"Previous Time Dimension: {self.time_dimension}")
        
        if self.time_granularity:
            lines.append(f"Previous Granularity: {self.time_granularity}")

        if self.time_range:
            lines.append(f"Previous Time Range: {self.time_range.start_date} to {self.time_range.end_date}")

        if self.filters:
            filter_strs = []
            for f in self.filters:
                val = f.value if isinstance(f.value, str) else ", ".join(f.value)
                filter_strs.append(f"{f.dimension} {f.operator} {val}")
            lines.append(f"Previous Filters: {'; '.join(filter_strs)}")

        if self.visualization_type:
            lines.append(f"Previous Visualization: {self.visualization_type}")

        if self.x_axis_labels:
            lines.append(f"Previous X-Axis Labels: {', '.join(self.x_axis_labels)}")

        if self.limit:
            lines.append(f"Previous Limit: {self.limit}")

        if self.active_hierarchies:
            hier_strs = [f"{axis}={dim}" for axis, dim in self.active_hierarchies.items()]
            lines.append(f"Previous Hierarchies: {', '.join(hier_strs)}")

        return "\n".join(lines)

    def to_decomposer_context(self) -> str:
        """
        Minimal context for the decomposer agent — just enough to understand
        conversational references without overwhelming the decomposition decision.
        """
        return "\n".join([
            f"Previous Query: \"{self.original_query}\"",
            f"Previous Intent: {self.intent_type}",
            f"Previous Metrics: {', '.join(m.name for m in self.metrics)}",
        ])
