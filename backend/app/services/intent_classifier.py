"""
Intent Classifier — Keyword Rule-Map (Zero Token Cost)

Runs BEFORE the DSPy classifier to catch obvious CPG intents at zero LLM cost.
Only falls through to DSPy if the keyword map returns no match.

Token saving: for ~40% of predictable CPG questions, this avoids the DSPy
classifier call entirely, saving ~300 tokens per hit.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# CPG intent keyword map
# Each intent lists high-signal keywords/phrases (case-insensitive, word-boundary)
# Order matters: more-specific intents first to avoid shadowing
# ---------------------------------------------------------------------------

_INTENT_RULES: list[tuple[str, list[str]]] = [
    ("forecast",          ["forecast", "predict", "projection", "next month", "next quarter", "next year", "expected sales"]),
    ("promo_lift",        ["promo lift", "promotion lift", "campaign lift", "promo effect", "promotion impact", "promo uplift", "scheme impact"]),
    ("market_share",      ["market share", "share of market", "sos", "share of shelf", "sov", "share of voice", "competitive share"]),
    ("sales_trend",       ["trend", "growth", "decline", "yoy", "year on year", "mom", "month on month", "over time", "weekly sales", "monthly sales", "quarterly sales", "annual sales"]),
    ("inventory",         ["inventory", "stock", "out of stock", "oos", "coverage", "days of supply", "dos", "fill rate", "replenishment"]),
    ("distribution",      ["distribution", "reach", "numeric distribution", "weighted distribution", "sku coverage", "availability"]),
    ("pricing",           ["price", "pricing", "mrp", "realization", "net price", "discount", "trade margin", "margin"]),
    ("competitor",        ["competitor", "competition", "rival", "vs ", " versus ", "benchmark", "peer"]),
    ("product_mix",       ["product mix", "sku mix", "pack mix", "portfolio mix", "mix analysis", "assortment"]),
    ("customer_segment",  ["customer segment", "shopper segment", "buyer segment", "channel mix", "modern trade", "general trade", "ecommerce", "outlet type"]),
]

# Pre-compiled regex patterns for efficiency
_COMPILED: list[tuple[str, re.Pattern]] = [
    (intent, re.compile(r"(?i)(?:^|[\s,\.])(?:" + "|".join(re.escape(kw) for kw in keywords) + r")(?:[\s,\.\?]|$)"))
    for intent, keywords in _INTENT_RULES
]


def classify_intent_by_keywords(question: str) -> Optional[str]:
    """
    Return the first matching CPG intent tag or None if no keyword matches.
    None means fall through to DSPy classifier (full LLM call).
    """
    for intent, pattern in _COMPILED:
        if pattern.search(question):
            return intent
    return None
