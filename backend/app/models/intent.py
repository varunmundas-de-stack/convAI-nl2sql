"""
Intent Model - Canonical intent contract for the NL2SQL system.

This module defines the structured representation of a user's query intent
after it has been parsed from natural language. It serves as the contract
between the intent extraction layer and the query generation layer.

Responsibilities:
- Define allowed intent types (enum)
- Define intent fields with types
- Enforce structural constraints via validation
- NO business logic
- NO catalog access
- NO LLM logic
"""

from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator, ConfigDict


class IntentType(str, Enum):
    """
    Defines the type of analytical query the user wants to perform.
    
    Each intent type has different requirements for which fields are needed.
    """
    SNAPSHOT = "snapshot"   # Point-in-time metric value (e.g., "total sales this month")
    TREND = "trend"         # Metric over time (e.g., "daily sales last 30 days")


class TimeRange(BaseModel):
    """
    Represents a time range for filtering or trending.
    
    Can be specified as:
    - A named window (e.g., "last_7_days", "MTD")
    - Explicit start/end dates
    """
    window: Optional[str] = Field(
        default=None,
        description="Named time window (e.g., 'last_7_days', 'month_to_date', 'YTD')"
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Explicit start date in ISO format (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        default=None,
        description="Explicit end date in ISO format (YYYY-MM-DD)"
    )

    @model_validator(mode='after')
    def validate_time_range(self) -> 'TimeRange':
        """Ensure either window OR start/end dates are provided, not both."""
        has_window = self.window is not None
        has_dates = self.start_date is not None or self.end_date is not None
        
        if has_window and has_dates:
            raise ValueError(
                "Cannot specify both 'window' and explicit dates. "
                "Use either a named window OR start_date/end_date."
            )
        
        # If explicit dates, both must be provided
        if has_dates:
            if self.start_date is None or self.end_date is None:
                raise ValueError(
                    "If using explicit dates, both 'start_date' and 'end_date' must be provided."
                )
        
        return self

    model_config = ConfigDict(extra="forbid")


class Filter(BaseModel):
    """
    Represents a filter condition on a dimension.
    
    Example: {"dimension": "region", "operator": "equals", "value": "North"}
    """
    dimension: str = Field(
        ...,
        description="The dimension to filter on (e.g., 'region', 'brand', 'outlet_type')"
    )
    operator: Literal["equals", "not_equals", "in", "not_in", "contains"] = Field(
        default="equals",
        description="Comparison operator"
    )
    value: str | List[str] = Field(
        ...,
        description="Value(s) to filter by. Use list for 'in'/'not_in' operators."
    )

    @model_validator(mode='after')
    def validate_operator_value_match(self) -> 'Filter':
        """Ensure operator and value type are compatible."""
        if self.operator in ("in", "not_in"):
            if not isinstance(self.value, list):
                raise ValueError(
                    f"Operator '{self.operator}' requires a list of values, "
                    f"got {type(self.value).__name__}"
                )
        elif self.operator in ("equals", "not_equals", "contains"):
            if isinstance(self.value, list):
                raise ValueError(
                    f"Operator '{self.operator}' requires a single value, "
                    f"got list"
                )
        return self

    model_config = ConfigDict(extra="forbid")


class TimeDimension(BaseModel):
    """
    Represents a time dimension configuration for trend analysis.
    
    Specifies which time field to use and at what granularity.
    """
    dimension: str = Field(
        ...,
        description="The time dimension field (e.g., 'invoice_date')"
    )
    granularity: Literal["day", "week", "month", "quarter", "year"] = Field(
        ...,
        description="Time granularity for grouping"
    )

    model_config = ConfigDict(extra="forbid")


class Intent(BaseModel):
    """
    The canonical intent representation for an analytical query.
    
    This is the contract between intent extraction and query generation.
    All fields are validated to ensure structural correctness.
    
    Constraints:
    - Exactly one metric is required
    - TREND intent requires time_dimension and time_range
    - No extra fields allowed
    
    Examples:
        # Snapshot: "Total sales this month"
        Intent(
            intent_type=IntentType.SNAPSHOT,
            metric="total_quantity",
            time_range=TimeRange(window="month_to_date")
        )
        
        # Trend: "Daily sales by region last 30 days"
        Intent(
            intent_type=IntentType.TREND,
            metric="total_quantity",
            group_by=["region"],
            time_dimension=TimeDimension(dimension="invoice_date", granularity="day"),
            time_range=TimeRange(window="last_30_days")
        )
    """
    intent_type: IntentType = Field(
        ...,
        description="The type of analytical query (SNAPSHOT or TREND)"
    )
    
    metric: str = Field(
        ...,
        description="The single metric to compute (e.g., 'total_quantity', 'transaction_count')"
    )
    
    group_by: Optional[List[str]] = Field(
        default=None,
        description="Dimensions to group by (e.g., ['region', 'brand'])"
    )
    
    time_dimension: Optional[TimeDimension] = Field(
        default=None,
        description="Time dimension configuration for trend analysis"
    )
    
    time_range: Optional[TimeRange] = Field(
        default=None,
        description="Time range to filter the data"
    )
    
    filters: Optional[List[Filter]] = Field(
        default=None,
        description="Filter conditions to apply"
    )

    @model_validator(mode='after')
    def validate_intent_constraints(self) -> 'Intent':
        """
        Enforce intent-type-specific constraints.
        
        - TREND intent MUST have time_dimension and time_range
        - Metric must be a non-empty string
        """
        # Validate metric is non-empty
        if not self.metric or not self.metric.strip():
            raise ValueError("Metric must be a non-empty string")
        
        # TREND-specific validation
        if self.intent_type == IntentType.TREND:
            if self.time_dimension is None:
                raise ValueError(
                    "TREND intent requires 'time_dimension' to specify "
                    "which time field and granularity to use"
                )
            if self.time_range is None:
                raise ValueError(
                    "TREND intent requires 'time_range' to specify "
                    "the date range for the trend"
                )
        
        return self

    model_config = ConfigDict(extra="forbid", use_enum_values=True)
    


# Type alias for clarity
IntentDict = dict  # When serialized via .model_dump()
