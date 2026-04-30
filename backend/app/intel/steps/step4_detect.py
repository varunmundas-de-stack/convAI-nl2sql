"""
Step 4 — Pattern Detection.

Runs deterministic detectors over the time-series rows returned by Step 3.
Reuses compute_metrics_facts() and apply_insight_rules() from the existing
insight_engine.py to keep detection logic DRY.

Detectors:
  - anomaly       Z-score > 2.0 on any period
  - trend         Linear regression slope + R² classification
  - target_gap    metric_value dropped below alert_on_abs_value threshold
  - inactivity    no sales rows for N consecutive days

Each detector emits a signal dict:
  {
    type:             "anomaly" | "trend" | "target_gap" | "inactivity",
    severity:         "low" | "medium" | "high" | "critical",
    watch_id:         int,
    kpi:              str,
    dimension_filters: dict,
    period_start:     str (ISO date),
    period_end:       str (ISO date),
    change_pct:       float | None,
    latest_value:     float | None,
    description:      str   (deterministic template, no LLM)
  }

Only signals with severity in (high, critical) are forwarded to Step 5.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_SIGNAL_THRESHOLD = "high"          # forward to LLM if severity ≥ this


def detect_patterns(watch_result: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Run all detectors over one watch-result and return a list of signals.

    Args:
        watch_result: Dict from step3_execute.execute_watches() —
                      must have: watch_id, kpi, dimension_filters,
                      rows [{date, value}], period_start, period_end,
                      alert_on_pct_change, alert_on_abs_value, alert_on_days_inactive.

    Returns:
        List of signal dicts (may be empty).
    """
    rows = watch_result.get("rows") or []
    if len(rows) < 3:
        return []

    signals: list[dict[str, Any]] = []

    values = [r["value"] for r in rows]

    # ── Anomaly (z-score) ───────────────────────────────────────────────────
    signals.extend(_detect_anomaly(values, rows, watch_result))

    # ── Trend ───────────────────────────────────────────────────────────────
    sig = _detect_trend(values, rows, watch_result)
    if sig:
        signals.append(sig)

    # ── Target gap ──────────────────────────────────────────────────────────
    sig = _detect_target_gap(values, rows, watch_result)
    if sig:
        signals.append(sig)

    # ── Inactivity ──────────────────────────────────────────────────────────
    sig = _detect_inactivity(rows, watch_result)
    if sig:
        signals.append(sig)

    return signals


def filter_signals_for_llm(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only signals whose severity meets the LLM threshold."""
    threshold = _SEVERITY_ORDER[_SIGNAL_THRESHOLD]
    return [s for s in signals if _SEVERITY_ORDER.get(s["severity"], 0) >= threshold]


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def _detect_anomaly(
    values: list[float],
    rows: list[dict],
    wr: dict[str, Any],
) -> list[dict[str, Any]]:
    """Z-score anomaly: any period with |z| > 2 is flagged."""
    if len(values) < 4:
        return []

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return []

    signals = []
    for row, val in zip(rows, values):
        z = (val - mean) / std
        if abs(z) > 2.0:
            severity = "critical" if abs(z) > 3.0 else "high"
            direction = "above" if z > 0 else "below"
            signals.append(_base_signal(wr, "anomaly", severity, {
                "change_pct":    round((val - mean) / mean * 100, 1) if mean else None,
                "latest_value":  val,
                "anomaly_date":  row["date"],
                "description":   (
                    f"{wr['kpi']} on {row['date']} was {direction} normal by "
                    f"{abs(z):.1f}σ (value={val:,.0f}, mean={mean:,.0f})"
                ),
            }))
    return signals


def _detect_trend(
    values: list[float],
    rows: list[dict],
    wr: dict[str, Any],
) -> dict[str, Any] | None:
    """Linear regression trend: flag consistent_decline or strong growth."""
    slope, r2 = _linear_trend_stats(values)
    if slope is None or r2 is None or r2 < 0.5:
        return None

    y_mean = sum(values) / len(values)
    normalized_slope = (slope / y_mean * 100) if y_mean else 0.0

    if abs(normalized_slope) < 5.0:   # < 5% per period — ignore
        return None

    direction = "declining" if normalized_slope < 0 else "growing"
    severity = "critical" if abs(normalized_slope) > 20 else "high"
    overall_change = _safe_pct(values[-1], values[0])

    return _base_signal(wr, "trend", severity, {
        "change_pct":   round(overall_change, 1) if overall_change is not None else None,
        "latest_value": values[-1],
        "description":  (
            f"{wr['kpi']} is consistently {direction} at "
            f"{abs(normalized_slope):.1f}%/period (R²={r2:.2f}, "
            f"overall change={overall_change:+.1f}%)"
        ),
    })


def _detect_target_gap(
    values: list[float],
    rows: list[dict],
    wr: dict[str, Any],
) -> dict[str, Any] | None:
    """Absolute threshold: latest value dropped below alert_on_abs_value."""
    threshold = wr.get("alert_on_abs_value")
    if threshold is None:
        return None
    latest = values[-1]
    if latest >= float(threshold):
        return None

    gap_pct = (float(threshold) - latest) / float(threshold) * 100
    severity = "critical" if gap_pct > 30 else "high"
    return _base_signal(wr, "target_gap", severity, {
        "change_pct":   round(-gap_pct, 1),
        "latest_value": latest,
        "description":  (
            f"{wr['kpi']} ({latest:,.0f}) is {gap_pct:.1f}% below "
            f"the target threshold of {threshold:,.0f}"
        ),
    })


def _detect_inactivity(
    rows: list[dict],
    wr: dict[str, Any],
) -> dict[str, Any] | None:
    """No non-zero sales rows for N consecutive days."""
    n_days = wr.get("alert_on_days_inactive")
    if not n_days:
        return None

    today = date.today()
    cutoff = today - timedelta(days=int(n_days))
    recent_nonzero = [r for r in rows if r["date"] >= str(cutoff) and r["value"] > 0]
    if recent_nonzero:
        return None

    return _base_signal(wr, "inactivity", "high", {
        "change_pct":   None,
        "latest_value": 0.0,
        "description":  (
            f"No {wr['kpi']} activity detected in the last {n_days} days"
        ),
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_signal(wr: dict[str, Any], sig_type: str, severity: str, extras: dict) -> dict[str, Any]:
    base = {
        "type":              sig_type,
        "severity":          severity,
        "watch_id":          wr["watch_id"],
        "kpi":               wr["kpi"],
        "dimension_filters": wr.get("dimension_filters") or {},
        "period_start":      wr.get("period_start"),
        "period_end":        wr.get("period_end"),
        "priority_score":    wr.get("priority_score", 0.5),
    }
    base.update(extras)
    return base


def _linear_trend_stats(values: list[float]) -> tuple[float | None, float | None]:
    n = len(values)
    if n < 3:
        return None, None
    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(values) / n
    denom = sum((xi - x_mean) ** 2 for xi in x)
    if denom == 0:
        return None, None
    numer = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
    slope = numer / denom
    intercept = y_mean - slope * x_mean
    ss_res = sum((y - (slope * xi + intercept)) ** 2 for xi, y in zip(x, values))
    ss_tot = sum((y - y_mean) ** 2 for y in values)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope, max(0.0, min(1.0, r2))


def _safe_pct(curr: float, prev: float) -> float | None:
    if prev == 0:
        return None
    return (curr - prev) / prev * 100
