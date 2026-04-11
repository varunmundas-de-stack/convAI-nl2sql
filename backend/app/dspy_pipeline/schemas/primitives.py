from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, Optional, Union, List
TermRole = Literal[
    "METRIC",           # net_value, billed_qty, count, gross_value, tax_value
    "DIMENSION",        # zone, brand, category, state, distributor_name...
    "TIME_RANGE",       # last month, last 30 days, Q1 2024, this quarter
    "TIME_GRANULARITY", # daily, weekly, monthly, quarterly, yearly
    "FILTER_VALUE",     # Gold Flake, North-1, Kirana, 5 kg, Oil
    "RANKING",          # top 5, bottom 3, highest, lowest, best, worst
    "SCOPE",            # Primary, Secondary
    "COMPARISON",       # vs, compared to, versus, growth, change
    "TREND",            # trend, trending, over time, trajectory
]
 
QueryIntent = Literal[
    "SNAPSHOT",        # single aggregated value, no dimension breakdown (was KPI)
    "DISTRIBUTION",    # breakdown by one or more dimensions
    "RANKING",         # top/bottom N with a grouping dimension
    "TREND",           # metric over time requiring granularity
    "COMPARISON",      # current period vs another period or dimension
    "DRILL_DOWN",      # navigating deeper into a hierarchy from previous context
    "MINIMAL_MESSAGE", # bare dimension or metric name only — context-dependent
    "STRUCTURAL",      # asking what entities exist, not how they performed
]
 

 
class ClassifiedTerm(BaseModel):
    
    term: str = Field(
        description="Exact word or phrase as it appears in the query."
    )
    role: TermRole = Field(
        description="Semantic role this term plays in the query."
    )
    catalog_match: Optional[str] = Field(
    default=None,
    description=(
        "The resolved canonical column name from the data catalog. "
        "Apply known aliases and synonyms to map user-facing terms to their "
        "standardized catalog equivalents. Null if the term has no direct "
        "catalog entry (e.g. analytical intents like ranking, trends, or comparisons)."
        )
    )
    scope: Optional[Literal["PRIMARY", "SECONDARY"]] = Field(
        default=None,
        description="The scope implied by this term (e.g., 'secondary sales' implies SECONDARY). Null if not applicable."
    )
 
    model_config = ConfigDict(extra="forbid")
 


class FilterHint(BaseModel):
    """
    A specific filter value paired with the dimension it qualifies.
    """
    dimension: str = Field(
        description=(
            "Catalog dimension this value qualifies. "
            "Examples: brand→'Gold Flake', zone→'North-1', "
            "category→'Oil', pack_size→'5 kg', retailer_type→'Kirana'."
        )
    )
    value: str = Field(
        description="Exact filter value as mentioned in the query."
    )
 
    model_config = ConfigDict(extra="forbid")
 

class FilterCondition(BaseModel):
    """
    A single filter condition on a dimension.
    """
 
    dimension: str = Field(
        description="Canonical catalog dimension name to filter on."
    )
    operator: Literal["equals", "not_equals", "in", "not_in", "contains"] = Field(
        description=(
            "Filter operator. Single value → 'equals'. "
            "Multiple values → 'in'. Exclusion → 'not_equals'/'not_in'."
        )
    )
    value: Union[str, List[str]] = Field(
        description="Filter value(s). Use List[str] only with 'in'/'not_in' operators."
    )
 
    model_config = ConfigDict(extra="forbid")


class MetricSpec(BaseModel):
    """A single metric with its aggregation in the final Intent."""
    name: str
    aggregation: Literal["sum", "count", "avg"]
 
    model_config = ConfigDict(extra="forbid")