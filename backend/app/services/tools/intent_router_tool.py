"""
Intent Router Tool — Step 0 of the pipeline.

Classifies the incoming query and short-circuits for non-DATA_QUERY intents:
  RISK_ANALYSIS / RECOMMENDATION  → Claude narrative with conversation memory
  TREND_EXPLAIN                   → Claude narrative + last query result as context
  DATA_QUERY                      → pass-through, pipeline continues unchanged
"""

import logging
import os

import anthropic

from app.pipeline.context import PipelineContext, Stage
from app.pipeline.runner import pipeline_step, _span_set, _Halt
from app.services.intent.intent_classifier import (
    IntentLabel,
    classify_intent,
    build_narrative_prompt,
)

logger = logging.getLogger(__name__)

_NARRATIVE_SYSTEM = (
    "You are a helpful sales analytics assistant. "
    "Provide clear, concise, and actionable responses. "
    "Use bullet points where appropriate. Be specific and data-driven."
)


def _fetch_conversation_history(session_id: str | None) -> list[dict]:
    if not session_id:
        return []
    try:
        from app.security.context import current_user
        user = current_user.get(None)
        if user is None:
            return []
        # Redis-first (fast), fall back to Postgres
        from app.services.redis_session import get_session_turns
        cached = get_session_turns(user.user_id, session_id)
        if cached:
            return cached
        from app.security.metadata_store import list_messages
        return list_messages(user, session_id)
    except Exception as e:
        logger.warning(f"[IntentRouter] Could not fetch conversation history: {e}")
        return []


def _call_claude_narrative(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    model = os.getenv("ANTHROPIC_MODEL_ID", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_NARRATIVE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


@pipeline_step("intent_router.classify")
def step_intent_router(ctx: PipelineContext, span) -> None:
    """Step 0 — classify intent and bypass SQL pipeline for non-data queries."""
    intent: IntentLabel = classify_intent(ctx.query)
    _span_set(span, input_query=ctx.query, output_intent=intent)
    logger.info(f"[IntentRouter] Query classified as: {intent}")

    # Store on ctx for downstream observability (DATA_QUERY path uses this too)
    if ctx.resolved_clarifications is None:
        ctx.resolved_clarifications = {}
    ctx.resolved_clarifications["__intent_label__"] = intent

    if intent == "DATA_QUERY":
        # Continue normal pipeline
        return

    # --- Non-SQL path ---
    history = _fetch_conversation_history(ctx.session_id)

    # For TREND_EXPLAIN, try to pull last query result from conversation history
    last_query_result = None
    if intent == "TREND_EXPLAIN":
        for msg in reversed(history):
            raw = msg.get("raw_data")
            if isinstance(raw, list) and raw:
                last_query_result = raw
                break

    try:
        prompt = build_narrative_prompt(
            query=ctx.query,
            intent=intent,
            conversation_history=history,
            last_query_result=last_query_result,
        )
        narrative = _call_claude_narrative(prompt)
    except Exception as e:
        logger.error(f"[IntentRouter] Narrative generation failed: {e}, falling back to DATA_QUERY path")
        return  # graceful fallback — let normal pipeline handle it

    # Populate ctx so to_dict() surfaces it correctly to the frontend
    ctx.refined_insights = narrative
    ctx.insights = {"narrative": narrative, "intent": intent}
    ctx.stage = Stage.COMPLETED
    ctx.success = True
    ctx.duration_ms = ctx.elapsed_ms()

    _span_set(span,
        output_intent=intent,
        output_narrative_length=len(narrative),
        output_history_turns=len(history),
    )
    logger.info(f"[IntentRouter] Narrative response generated ({len(narrative)} chars), bypassing SQL pipeline")
    raise _Halt
