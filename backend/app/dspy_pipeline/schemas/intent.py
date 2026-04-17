from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from .primitives import MetricSpec, FilterCondition
from .agent_outputs import PostProcessingResult
 
class TimeSpec(BaseModel):
    """Time block in the final Intent. Always uses 'invoice_date'."""
 
    dimension: Literal["invoice_date"] = Field(default="invoice_date")
    window: Optional[str] = Field(alias="time_window")
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    granularity: Optional[Literal["day", "week", "month", "quarter", "year"]] = Field(default=None)
 
    model_config = ConfigDict(extra="forbid")

 
 
class Intent(BaseModel):
    """
    Final output of the pipeline. Schema matches the original monolithic
    prompt's output exactly — the internal agent structure is invisible
    to downstream consumers.
    """
 
    sales_scope: Literal["PRIMARY", "SECONDARY"]
    metrics: List[MetricSpec] = Field(min_length=1)
    group_by: Optional[List[str]] = Field(default=None)
    
    @field_validator("group_by", mode="before")
    @classmethod
    def ensure_group_by_is_list(cls, v):
        if isinstance(v, str):
            return [v]
        return v
        
    filters: Optional[List[FilterCondition]] = Field(default=None)
    time: Optional[TimeSpec] = Field(default=None)
    post_processing: Optional[PostProcessingResult] = Field(default=None)
 
    model_config = ConfigDict(extra="forbid")
 