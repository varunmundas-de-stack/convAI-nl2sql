"""
Intel Scheduler — Proactive Insight Generation System.

This package drives automated, scheduler-triggered insight generation:
  - Step 1: Mine chat_messages → refresh user_interest_profiles
  - Step 2: Diff profile → sync intel_watch_configs
  - Step 3: Execute watches against tenant fact tables (RBAC-safe)
  - Step 4: Pattern detection (anomaly, trend, rank_shift, inactivity)
  - Step 5: LLM narrative generation (claude-haiku-4-5)
  - Step 6: Hash-based deduplication → INSERT ON CONFLICT DO NOTHING

Entry point: app.intel.scheduler (hooked into main.py lifespan).
"""
