"""
Cache Tool — Pipeline Stage 0 Injection

Adds three pre-pipeline stages that run before existing Stage 1 (Intent Extraction):

  Stage 0a: Tier-1 Golden Cache check  (cosine >= 0.95 → immediate return)
  Stage 0b: Tier-2 Redis Semantic Cache (cosine >= 0.92 → skip DSPy + Cube + Claude)
  Stage 0c: Load user memory context   → injected into Stage 1 DSPy prompt

Token-saving rationale:
  Each Tier-1 hit saves ~2000 tokens (intent extraction + narration).
  Each Tier-2 hit saves ~1500 tokens.
  Memory injection reduces DSPy clarification loops by providing query context.
"""

import logging
from typing import Any, Dict, Optional

from app.pipeline.context import PipelineContext, Stage
from app.pipeline.runner import pipeline_step, _span_set, _Halt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extra context field on PipelineContext injected by Stage 0c.
# We piggyback on resolved_clarifications to avoid modifying the dataclass.
# ---------------------------------------------------------------------------

_MEMORY_CONTEXT_KEY = "__user_memory_context__"


def _get_user_id(ctx: PipelineContext) -> Optional[str]:
    """Extract user_id from the security context (set per-request in main.py)."""
    try:
        from app.security.context import current_user
        user = current_user.get(None)
        if user is not None:
            return str(user.user_id)
    except Exception:
        pass
    return None


# ===========================================================================
# Stage 0a — Tier-1 Golden Q&A Cache
# ===========================================================================

@pipeline_step("cache.golden_lookup")
def step_golden_cache(ctx: PipelineContext, span) -> None:
    """
    Stage 0a: Check the FAISS golden cache (cosine >= 0.95).
    Hit → populate ctx with prebuilt answer and halt pipeline.
    Miss → continue to Stage 0b.
    """
    _span_set(span, input_query=ctx.query[:300])

    from app.services.cache_manager import golden_cache
    result = golden_cache.lookup(ctx.query)

    if result is None:
        _span_set(span, output_cache_tier_hit="miss")
        return  # proceed to Tier-2

    # Tier-1 hit — short-circuit the entire pipeline
    _span_set(span,
        output_cache_tier_hit="golden",
        output_similarity_score=str(result.get("similarity_score", "")),
        output_intent_tag=result.get("intent_tag", ""),
        output_tokens_saved=2000,
    )

    _populate_ctx_from_cache(ctx, result, tier="golden")
    raise _Halt  # stop pipeline here


# ===========================================================================
# Stage 0b — Tier-2 Redis Semantic Cache
# ===========================================================================

@pipeline_step("cache.semantic_lookup")
def step_semantic_cache(ctx: PipelineContext, span) -> None:
    """
    Stage 0b: Check the Redis semantic cache for this user (cosine >= 0.92).
    Hit → populate ctx with cached answer and halt pipeline.
    Miss → continue to Stage 0c (memory load).
    """
    _span_set(span, input_query=ctx.query[:300])

    user_id = _get_user_id(ctx)
    if not user_id:
        _span_set(span, output_cache_tier_hit="skip_no_user")
        return

    from app.services.cache_manager import semantic_cache
    result = semantic_cache.lookup(user_id, ctx.query)

    if result is None:
        _span_set(span, output_cache_tier_hit="miss")
        return  # proceed to live pipeline

    # Tier-2 hit — short-circuit pipeline
    _span_set(span,
        output_cache_tier_hit="semantic",
        output_similarity_score=str(result.get("similarity_score", "")),
        output_intent_tag=result.get("intent_tag", ""),
        output_tokens_saved=1500,
    )

    _populate_ctx_from_cache(ctx, result, tier="semantic")
    raise _Halt


# ===========================================================================
# Stage 0c — Load User Memory Context
# ===========================================================================

@pipeline_step("cache.memory_context")
def step_load_memory_context(ctx: PipelineContext, span) -> None:
    """
    Stage 0c: Build a context string from this user's conversation history
    and store it so Step 1 (intent extraction) can inject it into the DSPy prompt.

    Does NOT halt the pipeline — always continues to Stage 1.
    Token saving: by injecting prior context, the LLM needs fewer tokens to
    disambiguate follow-up questions, reducing clarification round-trips.
    """
    user_id = _get_user_id(ctx)
    if not user_id:
        _span_set(span, output_memory_context_injected=False, output_reason="no_user_id")
        return

    from app.services.memory_manager import build_context_for_question
    memory_context = build_context_for_question(user_id, ctx.query)

    if memory_context:
        # Attach to resolved_clarifications dict so intent_tool can read it
        rc = dict(ctx.resolved_clarifications or {})
        rc[_MEMORY_CONTEXT_KEY] = memory_context
        ctx.resolved_clarifications = rc
        _span_set(span,
            output_memory_context_injected=True,
            output_memory_context_length=len(memory_context),
        )
        logger.debug(f"[Stage-0c] Injected memory context ({len(memory_context)} chars) for user={user_id}")
    else:
        _span_set(span, output_memory_context_injected=False, output_reason="no_similar_turns")


# ===========================================================================
# Stage 9b — Store Result in Tier-2 Cache + User Memory (post-pipeline)
# ===========================================================================

@pipeline_step("cache.store_result")
def step_store_cache_and_memory(ctx: PipelineContext, span) -> None:
    """
    Stage 9b: After a successful live-pipeline run, persist the result to:
      1. Redis Tier-2 semantic cache (for future similar questions)
      2. User memory SQLite (for future context injection)

    This step runs after step_complete (Stage 8) and only acts on success.
    """
    if not ctx.success:
        _span_set(span, output_stored=False, output_reason="pipeline_failed")
        return

    user_id = _get_user_id(ctx)
    answer_text = _extract_answer_text(ctx)
    intent_tag = _extract_intent_tag(ctx)

    # --- Tier-2 Redis store ---
    if user_id:
        try:
            from app.services.cache_manager import semantic_cache
            semantic_cache.store(
                user_id=user_id,
                question=ctx.query,
                sql_generated=None,
                cube_query=ctx.cube_query,
                result_json=ctx.data,
                answer_text=answer_text,
                intent_tag=intent_tag,
            )
            _span_set(span, output_semantic_stored=True)
        except Exception as e:
            logger.warning(f"[Stage-9b] Semantic cache store failed (non-fatal): {e}")
            _span_set(span, output_semantic_stored=False)

    # --- User memory SQLite store ---
    if user_id and answer_text:
        try:
            from app.services.memory_manager import save_turn
            save_turn(
                user_id=user_id,
                question=ctx.query,
                answer=answer_text,
                session_id=ctx.session_id,
                turn_id=ctx.request_id,
                intent_tag=intent_tag,
            )
            _span_set(span, output_memory_stored=True)
        except Exception as e:
            logger.warning(f"[Stage-9b] Memory store failed (non-fatal): {e}")
            _span_set(span, output_memory_stored=False)


# ===========================================================================
# Shared helpers
# ===========================================================================

def _populate_ctx_from_cache(ctx: PipelineContext, result: Dict[str, Any], tier: str) -> None:
    """Fill PipelineContext fields from a cache hit payload."""
    answer = result.get("answer_text", "")
    # Store answer in refined_insights (the field the frontend reads)
    ctx.refined_insights = answer
    ctx.cube_query = result.get("cube_query") or ctx.cube_query
    ctx.success = True
    ctx.stage = Stage.COMPLETED
    ctx.duration_ms = ctx.elapsed_ms()
    # Attach cache tier so to_dict() can surface it for audit logging and OTel
    rc = dict(ctx.resolved_clarifications or {})
    rc["__cache_tier__"] = tier
    rc["__cache_hit__"] = True
    ctx.resolved_clarifications = rc


def _extract_answer_text(ctx: PipelineContext) -> str:
    """Best-effort extraction of the human-readable answer from a completed ctx."""
    if isinstance(ctx.refined_insights, str):
        return ctx.refined_insights
    if hasattr(ctx.refined_insights, "primary_insight"):
        return getattr(ctx.refined_insights.primary_insight, "label", "")
    if isinstance(ctx.insights, dict) and ctx.insights.get("refined_insights"):
        ri = ctx.insights["refined_insights"]
        return ri if isinstance(ri, str) else str(ri)
    return ""


def _extract_intent_tag(ctx: PipelineContext) -> Optional[str]:
    """Extract a CPG intent tag from validated_intent if available."""
    try:
        vi = ctx.validated_intent
        if vi is None:
            return None
        intent_type = getattr(vi, "intent_type", None)
        if intent_type:
            return str(intent_type)
    except Exception:
        pass
    return None
