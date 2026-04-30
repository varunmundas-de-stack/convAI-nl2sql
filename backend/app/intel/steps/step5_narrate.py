"""
Step 5 — LLM Narrative Generation (claude-haiku-4-5).

For each signal that passed the severity threshold, calls Claude Haiku 4.5
via DSPy to produce a human-readable:
  - title          (≤ 80 chars)
  - description    (2–3 sentences)
  - suggested_action

Uses dspy.context() — NOT dspy.configure() — so it is safe to call from an
async background task without conflicting with the main DSPy pipeline.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import dspy
from pydantic import BaseModel
import datetime 

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DSPy Signature
# ---------------------------------------------------------------------------

class IntelNarrativeSignature(dspy.Signature):
    """
    Generate a concise, actionable sales insight narrative for a field sales
    manager or analyst based on a detected pattern signal.
    """
    role: str           = dspy.InputField(desc="User's role (e.g. ZSM, ASM, SO)")
    kpi: str            = dspy.InputField(desc="Metric name (e.g. net_value, billed_qty)")
    entity_context: str = dspy.InputField(desc="Entity/dimension being watched (e.g. zone=West, brand=KitKat)")
    signal_type: str    = dspy.InputField(desc="Detection type: anomaly | trend | target_gap | inactivity")
    severity: str       = dspy.InputField(desc="Signal severity: high | critical")
    description: str    = dspy.InputField(desc="Deterministic description of the pattern")
    change_pct: str     = dspy.InputField(desc="% change string (e.g. '-18.5%') or 'N/A'")
    period: str         = dspy.InputField(desc=f"Data window (e.g. '2024-03-01 to {datetime.date.today()}')")

    title: str          = dspy.OutputField(desc="One-line insight title, max 80 chars, no quotes")
    narrative: str      = dspy.OutputField(desc="2–3 sentences explaining the insight and its business impact")
    suggested_action: str = dspy.OutputField(desc="One specific, actionable next step for the user")


# ---------------------------------------------------------------------------
# DSPy Module
# ---------------------------------------------------------------------------

class IntelNarrativeModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(IntelNarrativeSignature)

    def forward(self, **kwargs) -> dspy.Prediction:
        return self.predict(**kwargs)


# ---------------------------------------------------------------------------
# Pydantic output model
# ---------------------------------------------------------------------------

class IntelNarrative(BaseModel):
    title: str
    description: str
    suggested_action: str
    priority: Literal["low", "medium", "high", "critical"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_narratives(
    signals: list[dict[str, Any]],
    user: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    For each signal, call the LLM and attach title/description/suggested_action.

    Args:
        signals: Filtered signal dicts from step4 (severity ≥ HIGH).
        user:    Row dict from app_meta.users (for role context).

    Returns:
        List of enriched signal dicts with narrative fields added in-place.
        Signals where LLM fails are skipped (non-fatal).
    """
    if not signals:
        return []

    lm = _get_lm()
    module = IntelNarrativeModule()
    enriched = []

    for signal in signals:
        try:
            narrative = _narrate_one(signal, user, module, lm)
            enriched.append({**signal, **narrative.model_dump()})
        except Exception as e:
            logger.warning(
                f"[step5] Narrative failed for watch_id={signal.get('watch_id')}: {e}"
            )

    logger.info(f"[step5] Generated {len(enriched)}/{len(signals)} narratives")
    return enriched


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_lm() -> dspy.LM:
    """Build a claude-haiku-4-5 LM instance for narrative generation."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for intel narrative generation")
    return dspy.LM(
        model="anthropic/claude-haiku-4-5",
        api_key=api_key,
        max_tokens=512,
        temperature=0.3,
    )


def _narrate_one(
    signal: dict[str, Any],
    user: dict[str, Any],
    module: IntelNarrativeModule,
    lm: dspy.LM,
) -> IntelNarrative:
    role = user.get("role") or "Analyst"
    kpi = signal.get("kpi") or "metric"
    dim_filters = signal.get("dimension_filters") or {}
    entity_context = (
        ", ".join(f"{k}={v}" for k, v in dim_filters.items()) if dim_filters else "all regions"
    )
    change_pct = signal.get("change_pct")
    change_str = f"{change_pct:+.1f}%" if change_pct is not None else "N/A"
    period = f"{signal.get('period_start', '')} to {signal.get('period_end', '')}"

    # Use dspy.context() so we don't mutate the global DSPy config
    with dspy.context(lm=lm):
        pred = module(
            role=role,
            kpi=kpi,
            entity_context=entity_context,
            signal_type=signal.get("type", ""),
            severity=signal.get("severity", "high"),
            description=signal.get("description", ""),
            change_pct=change_str,
            period=period,
        )

    return IntelNarrative(
        title=_truncate(pred.title, 80),
        description=pred.narrative,
        suggested_action=pred.suggested_action,
        priority=signal.get("severity", "high"),  # type: ignore[arg-type]
    )


def _truncate(text: str, max_len: int) -> str:
    text = text.strip().strip('"').strip("'")
    return text[:max_len] if len(text) > max_len else text
