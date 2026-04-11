from typing import Optional, List, Dict, Any, Union
import dspy
import json
import logging
import time
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.utils.tracer import _span_set

logger = logging.getLogger(__name__)
from app.dspy_pipeline.schemas import PostProcessingResult
from .signature import ResolvePostProcessing
tracer = get_tracer(__name__)

from app.dspy_pipeline.schemas import PostProcessingResult
from .signature import ResolvePostProcessing

