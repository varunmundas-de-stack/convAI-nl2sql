"""
backend/cost_tracker.py
Drop-in wrapper around anthropic.Anthropic() for the convAI-nl2sql project.
Logs every API call to cost_log.jsonl — picked up by monitor.py daemon.

Usage (in your DSPy pipeline / LLM tools):
    from backend.cost_tracker import tracked_client
    client = tracked_client()
    resp = client.messages.create(model=..., messages=..., max_tokens=...)
"""

import os, json, time, functools
from datetime import datetime
from pathlib import Path
import anthropic

# ── Config (reads from .env via os.environ) ────────────────────────────────
COST_LOG = Path(os.getenv("COST_LOG_PATH", "cost_log.jsonl"))
MODEL_ID  = os.getenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")
LIMIT_USD = float(os.getenv("COST_LIMIT_USD", "0.50"))

PRICES = {
    "claude-haiku-4-5":           {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":          {"input": 3.00,  "output": 15.00},
    "claude-opus-4-6":            {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514":   {"input": 3.00,  "output": 15.00},
    "claude-opus-4-20250514":     {"input": 15.00, "output": 75.00},
}

def _price(model: str) -> dict:
    for k, v in PRICES.items():
        if k in model:
            return v
    return PRICES["claude-sonnet-4-6"]   # safe default


def _log(event: dict):
    """Append one JSON line to cost_log.jsonl."""
    COST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(COST_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = _price(model)
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


# ── Tracked wrapper ────────────────────────────────────────────────────────
class TrackedMessages:
    """Wraps client.messages and logs token usage after every call."""

    def __init__(self, messages_api, session_id: str):
        self._api = messages_api
        self._session = session_id

    def create(self, **kwargs):
        t0 = time.time()
        resp = self._api.create(**kwargs)
        elapsed = round(time.time() - t0, 3)

        model = kwargs.get("model", MODEL_ID)
        inp   = getattr(resp.usage, "input_tokens", 0)
        out   = getattr(resp.usage, "output_tokens", 0)
        cost  = _compute_cost(model, inp, out)

        _log({
            "sessionId":      self._session,
            "timestamp":      datetime.utcnow().isoformat(),
            "model":          model,
            "caller":         kwargs.get("_caller", "unknown"),   # pass _caller="dspy_pipeline" etc.
            "elapsed_s":      elapsed,
            "usage": {
                "input_tokens":  inp,
                "output_tokens": out,
            },
            "cost_usd":       round(cost, 7),
        })

        return resp

    def __getattr__(self, name):
        return getattr(self._api, name)


def tracked_client(session_id: str = None) -> anthropic.Anthropic:
    """
    Returns an anthropic.Anthropic client whose .messages is cost-tracked.

    session_id: logical grouping (e.g. tenant_id, request_id).
                Defaults to today's date so daily cost rolls up naturally.
    """
    if session_id is None:
        session_id = f"nl2sql-{datetime.utcnow().strftime('%Y%m%d')}"

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    client.messages = TrackedMessages(client.messages, session_id)
    return client


# ── Quick cost check (call from anywhere) ─────────────────────────────────
def today_cost() -> float:
    """Read cost_log.jsonl and return today's total USD spend."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    total = 0.0
    if COST_LOG.exists():
        for line in COST_LOG.read_text().splitlines():
            try:
                ev = json.loads(line)
                if ev.get("timestamp", "").startswith(today):
                    total += ev.get("cost_usd", 0)
            except json.JSONDecodeError:
                pass
    return total


if __name__ == "__main__":
    print(f"Today's API spend: ${today_cost():.5f}")
    print(f"Budget remaining:  ${LIMIT_USD - today_cost():.5f}")
