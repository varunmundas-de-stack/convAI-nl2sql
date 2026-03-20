"""
DSPy Pipeline for Intent Extraction

This module implements a modular DSPy pipeline that replaces the monolithic
LLM prompt for intent extraction. The pipeline follows decomposition rules
to separate concerns into specialized agents.

Architecture:
1. ClassifierAgent - Term classification and semantic labeling
2. ScopeTimeAgent - Sales scope and time resolution
3. MetricsAgent - Metric extraction and aggregation
4. DimensionsAgent - Dimensions, filters, and context handling
5. Assembler - Final assembly with binary constraint enforcement

Key Benefits:
- Independent optimization per agent
- Better failure isolation
- Maintainable constraints in Python
- Higher accuracy through specialization
"""

from .pipeline import IntentExtractionPipeline
from .schemas import (
    ClassifiedQuery,
    ScopeTimeResult,
    MetricsResult,
    DimensionsResult
)

__all__ = [
    "IntentExtractionPipeline",
    "ClassifiedQuery",
    "ScopeTimeResult",
    "MetricsResult",
    "DimensionsResult"
]