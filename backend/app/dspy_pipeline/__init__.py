"""
DSPy Pipeline for Intent Extraction

This module implements a modular DSPy pipeline that replaces the monolithic
LLM prompt for intent extraction. The pipeline follows decomposition rules
to separate concerns into specialized agents.

Architecture:
1. ClassifierAgent - Term classification and semantic labeling with intent determination
2. ScopeAgent - Sales scope determination (PRIMARY/SECONDARY)
3. TimeAgent - Time constraint resolution with decision logic
4. MetricsAgent - Metric extraction and aggregation specification
5. DimensionsAgent - Dimensions and filters resolution
6. Assembler - Final assembly with post-processing and constraint enforcement

Key Benefits:
- Independent optimization per agent
- Better failure isolation
- Maintainable constraints in Python
- Higher accuracy through specialization
- Intent-centric design with structured JSON outputs
"""

from .pipeline import IntentExtractionPipeline
from .schemas import (
    ClassifiedQuery,
    ScopeResult,
    TimeResult,
    MetricsResult,
    DimensionsResult,
    Intent
)

__all__ = [
    "IntentExtractionPipeline",
    "ClassifiedQuery",
    "ScopeResult",
    "TimeResult",
    "MetricsResult",
    "DimensionsResult",
    "Intent"
]