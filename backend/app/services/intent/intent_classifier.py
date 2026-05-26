"""
Intent Classifier — routes incoming queries to one of 4 handling paths.

Intents:
  DATA_QUERY      → existing CubeJS SQL pipeline (unchanged)
  RISK_ANALYSIS   → Claude narrative with conversation memory
  RECOMMENDATION  → Claude narrative with conversation memory
  TREND_EXPLAIN   → Claude narrative with last query result as context
"""

import logging
import os
from typing import Literal, Optional

import anthropic

logger = logging.getLogger(__name__)

IntentLabel = Literal["DATA_QUERY", "RISK_ANALYSIS", "RECOMMENDATION", "TREND_EXPLAIN"]

_SYSTEM = """You are an intent classifier for a sales analytics assistant.
Classify the user message into exactly one of these intents:

DATA_QUERY      – requests specific numbers, metrics, counts, or data retrieval
                  (e.g. "show me revenue for last month", "top 10 products by sales")
RISK_ANALYSIS   – asks about risks, threats, red flags, or what could go wrong
                  (e.g. "which accounts are at risk?", "what are the warning signs?")
RECOMMENDATION  – asks for suggestions, next steps, or what to do
                  (e.g. "what should I focus on?", "recommend actions for the team")
TREND_EXPLAIN   – asks to explain, interpret, or reason about an already-seen trend
                  (e.g. "why did sales drop?", "explain this pattern", "what does this mean?")

Reply with ONLY the intent label — no punctuation, no explanation."""

_EXAMPLES = [
    ("Show revenue by region for Q1", "DATA_QUERY"),
    ("Which reps are at risk of missing quota?", "RISK_ANALYSIS"),
    ("What actions should I take to improve retention?", "RECOMMENDATION"),
    ("Why did orders spike last week?", "TREND_EXPLAIN"),
    ("Give me top 5 customers by revenue", "DATA_QUERY"),
    ("What risks do I face in the southern region?", "RISK_ANALYSIS"),
    ("Recommend which products to push this quarter", "RECOMMENDATION"),
    ("Explain why churn increased last month", "TREND_EXPLAIN"),
]


def classify_intent(query: str) -> IntentLabel:
    """Single Claude call to classify query into one of 4 intents."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    model = os.getenv("ANTHROPIC_MODEL_ID", "claude-haiku-4-5-20251001")

    few_shot = "\n".join(f'User: "{q}"\nIntent: {i}' for q, i in _EXAMPLES)
    user_message = f"{few_shot}\n\nUser: \"{query}\"\nIntent:"

    try:
        response = client.messages.create(
            model=model,
            max_tokens=10,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip().upper()
        valid: set[IntentLabel] = {"DATA_QUERY", "RISK_ANALYSIS", "RECOMMENDATION", "TREND_EXPLAIN"}
        if raw in valid:
            return raw  # type: ignore[return-value]
        logger.warning(f"[IntentClassifier] Unexpected label '{raw}', defaulting to DATA_QUERY")
        return "DATA_QUERY"
    except Exception as e:
        logger.error(f"[IntentClassifier] Classification failed: {e}, defaulting to DATA_QUERY")
        return "DATA_QUERY"


def build_narrative_prompt(
    query: str,
    intent: IntentLabel,
    conversation_history: list[dict],
    last_query_result: Optional[list[dict]] = None,
) -> str:
    """Build the Claude prompt for non-DATA_QUERY intents."""
    last_turns = conversation_history[-6:]  # last 3 pairs (user + assistant)

    history_text = ""
    if last_turns:
        history_text = "Recent conversation:\n" + "\n".join(
            f"{m['role'].capitalize()}: {m['content']}" for m in last_turns
        ) + "\n\n"

    result_text = ""
    if last_query_result and intent == "TREND_EXPLAIN":
        import json
        preview = last_query_result[:20]
        result_text = f"Last query result (up to 20 rows):\n{json.dumps(preview, default=str)}\n\n"

    intent_instruction = {
        "RISK_ANALYSIS": "Provide a concise risk analysis based on the conversation context and data. Identify specific risks, quantify where possible, and prioritise by severity.",
        "RECOMMENDATION": "Provide actionable recommendations based on the conversation context. Be specific, prioritised, and practical.",
        "TREND_EXPLAIN": "Explain the trend or pattern in the data. Use the query result if available. Be analytical and clear.",
    }[intent]

    return (
        f"{history_text}"
        f"{result_text}"
        f"User question: {query}\n\n"
        f"Task: {intent_instruction}"
    )
