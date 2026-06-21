"""
Golden QA Regression Test Suite
================================
Tests the 5 most common sales queries against the live backend.
Run before every AWS deploy to catch regressions.

Usage (from project root):
    pytest backend/app/tests/test_golden_qa.py -v

Requirements:
    - All containers running (docker compose up -d)
    - nestle_admin credentials in .env or defaults below
    - Tests hit the real /query endpoint — not mocked

Pass criteria per query:
    - HTTP 200 or clarification (not 4xx/5xx errors)
    - If successful: response has data rows OR refined_insights
    - Response time < 120 seconds
"""

import os
import time
import pytest
import requests

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL   = os.getenv("TEST_API_BASE", "http://localhost:8000")
USERNAME   = os.getenv("TEST_USERNAME",  "nestle_admin")
PASSWORD   = os.getenv("TEST_PASSWORD",  "admin123")
TIMEOUT    = 120  # seconds — LLM pipeline can be slow

# ── Golden queries (sales-trend only — data exists in seed) ───────────────────

GOLDEN_QUERIES = [
    {
        "id":       "gqa-sales-trend-001",
        "question": "Show secondary net sales for last 30 days",
        "expect":   "data_or_clarification",
    },
    {
        "id":       "gqa-sales-trend-004",
        "question": "Show top 5 SKUs by net sales secondary",
        "expect":   "data_or_clarification",
    },
    {
        "id":       "gqa-sales-trend-005",
        "question": "Show secondary sales performance by zone",
        "expect":   "data_or_clarification",
    },
    {
        "id":       "gqa-zone-001",
        "question": "Secondary net sales by zone for last month",
        "expect":   "data_or_clarification",
    },
    {
        "id":       "gqa-brand-001",
        "question": "Show secondary net sales by brand for last 30 days",
        "expect":   "data_or_clarification",
    },
]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def auth_token():
    """Login once for the whole test session."""
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json().get("access_token")
    assert token, "No access_token in login response"
    return token


@pytest.fixture(scope="session")
def headers(auth_token):
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type":  "application/json",
    }


# ── Helper ────────────────────────────────────────────────────────────────────

def run_query(question: str, headers: dict) -> tuple[int, dict, float]:
    """POST /query, return (status_code, body, elapsed_seconds)."""
    start = time.monotonic()
    resp  = requests.post(
        f"{BASE_URL}/query",
        json={"query": question},
        headers=headers,
        timeout=TIMEOUT,
    )
    elapsed = time.monotonic() - start
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    return resp.status_code, body, elapsed


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("gqa", GOLDEN_QUERIES, ids=[q["id"] for q in GOLDEN_QUERIES])
def test_golden_query(gqa, headers):
    """
    Each golden query must:
    1. Return HTTP 200 (success or clarification)
    2. Not return a hard pipeline error (no error.error_type)
    3. Complete within TIMEOUT seconds
    4. Return data rows OR refined_insights OR clarification
    """
    status, body, elapsed = run_query(gqa["question"], headers)

    # ── 1. Must be HTTP 200 ──────────────────────────────────────────────────
    assert status == 200, (
        f"[{gqa['id']}] Expected 200, got {status}. "
        f"Body: {str(body)[:300]}"
    )

    # ── 2. No hard pipeline error ────────────────────────────────────────────
    error = body.get("error")
    assert not error, (
        f"[{gqa['id']}] Pipeline error: {error}"
    )

    # ── 3. Completed within timeout ──────────────────────────────────────────
    assert elapsed < TIMEOUT, (
        f"[{gqa['id']}] Took {elapsed:.1f}s — exceeded {TIMEOUT}s limit"
    )

    # ── 4. Has useful output ─────────────────────────────────────────────────
    is_clarification = body.get("clarification") is True
    has_data         = bool(body.get("data"))
    has_insights     = bool(body.get("refined_insights"))

    assert is_clarification or has_data or has_insights, (
        f"[{gqa['id']}] No data, no insights, and no clarification in response. "
        f"Stage: {body.get('stage')}. Body keys: {list(body.keys())}"
    )

    # ── Log result ───────────────────────────────────────────────────────────
    if is_clarification:
        result = f"CLARIFICATION: {body.get('clarification_message', '')[:80]}"
    elif has_data:
        result = f"DATA: {len(body['data'])} rows"
    else:
        headline = ""
        if isinstance(body.get("refined_insights"), dict):
            pi = body["refined_insights"].get("primary_insight", {})
            headline = pi.get("headline", "") if isinstance(pi, dict) else ""
        result = f"INSIGHTS: {headline[:80]}"

    print(f"\n[{gqa['id']}] {elapsed:.1f}s — {result}")


# ── Smoke test: health check ──────────────────────────────────────────────────

def test_backend_health():
    """Backend must be reachable before running golden QA."""
    resp = requests.get(f"{BASE_URL}/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json().get("status") == "healthy"
