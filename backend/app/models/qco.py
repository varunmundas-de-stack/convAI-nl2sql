"""
Query Context Object (QCO) - Lightweight conversational context for NL2SQL.

The QCO captures the resolved analytical parameters from the last successful
query, enabling follow-up queries like "now show by brand" or "drill into Mumbai".

It carries NO query results — only the resolved intent parameters.
"""

from enum import Enum
from typing import List, Optional
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


class QueryContextObject(BaseModel):
    """
    Lightweight structured object capturing the resolved state of the last
    successful query.

    This is injected into the LLM prompt for follow-up queries and used
    by the intent merger to fill in missing fields.
    """
    # Schema version for migration support
    schema_version: int = Field(default=2, description="QCO schema version for backward compatibility")
    
    # The original natural language query
    original_query: str = Field(..., description="The original NL query that produced this context")

    # Core analytical parameters (all using semantic names, not Cube IDs)
    intent_type: str = Field(..., description="e.g. snapshot, trend, ranking, distribution")
    sales_scope: str = Field(..., description="PRIMARY or SECONDARY")
    metric: str = Field(..., description="Semantic metric name, e.g. 'net_value'")

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

    # Limit
    limit: Optional[int] = Field(default=None)

    def to_prompt_context(self) -> str:
        """
        Format QCO as a human-readable context block for LLM prompt injection.

        This is deliberately concise — the LLM should understand the previous
        query state without being overwhelmed.
        """
        lines = [
            f"Previous Query: \"{self.original_query}\"",
            f"Previous Intent: {self.intent_type}",
            f"Previous Scope: {self.sales_scope}",
            f"Previous Metric: {self.metric}",
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

        if self.limit:
            lines.append(f"Previous Limit: {self.limit}")

        return "\n".join(lines)
