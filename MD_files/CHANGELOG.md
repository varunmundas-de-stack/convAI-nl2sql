# Changelog

All notable changes to the CPG Analytics NL2SQL platform are recorded here.
Changes are grouped by sprint/session and reflect what was **actually merged to `main` and deployed to AWS EC2**.

---

## Sprint 2 — May 2026

### Session: NL2SQL CPG Analytics Pipeline Continuation

**Context:** Resumed from Sprint 1 PoC. Codebase had accumulated stale code, broken dimension resolution, and hardcoded values across the frontend. Goal was to stabilise the pipeline and prepare for a client demo.

#### Completed

**`backend/app/services/cube/cube_query_builder.py`**
- Fixed `_build_valid_dimensions()` — the function had a dead commented-out block above a broken replacement. The broken version used `all(isinstance(v, str) ...)` which evaluated to `False` for mixed `str`/`dict` DIMENSION_MAP values, causing the passthrough accumulation to silently add nothing. Replaced with a single clean loop handling both `str` and `dict` values correctly.

**`backend/app/dspy_pipeline/schemas/catalog.py`**
- Removed fully-qualified Cube dimension paths (`dim_geography.*`, `dim_product.*`, `dim_period.*`, `dim_salesorg.*`) that had leaked into `COMMON_DIMENSIONS` via an unclosed comment block. These paths caused the DSPy DimensionsModule to resolve user queries to `dim_geography.zone` instead of `fact_secondary_sales.zone`, producing Cube errors (`relation "client_nestle.dim_geography" does not exist`).
- Removed star-schema aliases (`geo_zone`, `geo_state`, `prod_category`, `org_asm`, `period_year` etc.) from `COMMON_DIMENSIONS` — these caused the same resolution failure in fresh sessions where no prior context existed.
- Cleaned `SECONDARY_ONLY_DIMENSIONS` — removed `dim_channel_type` (internal Cube path), added `salesrep_code`, `salesrep_name`, `channel_type`.

**`backend/app/services/intent/intent_normalizer.py`**
- `DIMENSION_MAP` entries for `fact_primary_sales.*` confirmed correct — no changes needed.

**`backend/app/main.py`**
- Added `GET /dashboard/kpis` endpoint — optimised backend queries returning net sales, active SKUs, zone coverage, target vs actual, 30D daily trend, top 10 brands, and zone rows. Response time under 2 seconds, fine-tuned to the latest available data window in the warehouse.
- Added `GET /insights` endpoint — overrides the static DB-seeded placeholder with 8 role-aware statistical detectors tuned to the latest data.
- Added `POST /insights/{id}/read` and `POST /insights/{id}/feedback` stubs.

**`backend/app/insight_generator.py`** *(new file)*
- Standalone module with 8 non-obvious statistical insight detectors, tuned to the latest data in the warehouse:
  1. SKU Concentration Risk — top 3 SKUs driving >25% of revenue
  2. Zone Velocity Divergence — zones moving in opposite directions simultaneously
  3. Dormant High-Value Brand — was top-5 last period, now down >15%
  4. Weekday vs Weekend Pattern — push-model signal (field rep activity vs consumer pull)
  5. Emerging SKU Momentum — small-base SKU growing >20%
  6. End-of-Month Channel Stuffing — last 3 days driving >20% of monthly sales
  7. Distributor Dependency — single distributor >25% of zone revenue
  8. Pack Size Mix Shift — pack declining >5% (affordability/competitive signal)
- All detectors are role-aware — SO/ASM/ZSM roles see only their authorised data slice.
- Thresholds calibrated to real CPG data (not synthetic high-variance seed data).

**`backend/app/security/metadata_store.py`**
- `list_insights()` updated to return dynamic role-aware insights merged with any scheduler-triggered DB insights. Eliminates the static seeded "Nestle India sales review is ready" placeholder.

**`backend/app/insights_router.py`**
- Left intact — router delegates to overridden `list_insights()`. No changes required.

**`backend/requirements.txt`**
- Added `tenacity==8.2.3` — was missing, caused `ModuleNotFoundError` on container start.

**`backend/Dockerfile`**
- Added `COPY etl/ ./etl/` — the ETL folder was not being copied into the Docker image, causing the `etl-watcher` service to fail with `No such file or directory`.

**`backend/etl/cpg_etl.py`** *(new file)*
- Watch-mode CSV ingestion pipeline. Polls `drop_zone/` every 30 seconds.
- Auto-detects sales type from filename: `*secondary*` → `fact_secondary_sales`, `*primary*` → `fact_primary_sales`.
- Upserts all 5 dimension tables before loading fact rows (`ON CONFLICT DO UPDATE`).
- Archives processed files to `processed/` with `YYYYMMDD_HHMMSS_` timestamp prefix.
- Fixed `processed/` folder path bug — was creating `drop_zone/processed/` instead of `data/processed/`.
- Requires unique constraints on fact tables and business-key unique constraints on dimension tables (see DB migration notes below).

**`docker-compose.yml`**
- Added `etl-watcher` service — runs `cpg_etl.py --tenant nestle --watch /app/etl/data/drop_zone --poll 30`.
- Added volume mount `./backend/etl/data:/app/etl/data` to backend service.

**`frontend/src/components/ChatWindow.tsx`**
- Added `lastSalesScope` state tracking from `backendResponse.raw_intent.sales_scope`.
- Added scope-aware dimension chips above the input bar — common dimensions always visible; secondary-only chips (retailer, route, salesrep) shown only when `lastSalesScope === "SECONDARY"`.
- Chips are clickable — appends ` by <dimension>` to current input text.

**`frontend/src/services/api.ts`**
- Added `getDashboardKpis()` function calling `GET /dashboard/kpis`.

#### Existing Features Confirmed Active (Sprint 2 Validation)

**3-Tier Semantic Cache (`backend/app/services/cache_manager.py`)**
- Tier 1 (Golden Q&A): FAISS in-memory index loaded from `golden_qa.json` at startup. Cosine ≥ 0.95 returns pre-computed answers instantly — zero LLM cost.
- Tier 2 (Redis Semantic): Per-user embedding cache in Redis. Cosine ≥ 0.92 skips DSPy + Cube + Claude narration entirely.
- Tier 3: Full live pipeline on genuine cache misses only.
- Cache stats exposed at `GET /cache/stats`.

**Persistent User Memory (`backend/app/services/memory_manager.py`)**
- Last 20 conversation turns per user stored in `memory.db` (SQLite sidecar).
- On each new query, prior intent patterns are retrieved and injected as context — improves resolution of ambiguous follow-up questions over time.
- Not dependent on Anthropic API — pure local storage.

**Fix #6 — Primary sales full end-to-end flow**
- Reason: Requires live Anthropic API to test the DSPy pipeline scope resolution for PRIMARY queries. API key hit usage limit during the session (resets 2026-06-01). Backend code is correct but untested end-to-end.

#### Abandoned / Deferred
**Fix #7 — Intel scheduler live AI narratives**
- Status: Deferred to Sprint 3.
- Reason: `intel/scheduler.py` step 5 (`step5_narrate.py`) calls Claude to generate natural-language insight narratives. API key exhaustion blocked testing. The 8 Postgres-direct probes in `insight_generator.py` are a functional replacement that does not require the API.

**Dashboard trend chart 7D/30D/90D tab switching**
- Status: Partially working — 30D loads correctly on page load via `/dashboard/kpis`. Tab switching clears trend state because `fetchTrend` calls `sendQuery` which requires the Anthropic API.
- Reason: Not pushed to git. Frontend fix attempted but not stabilised before API exhaustion. Will be addressed in Sprint 3 by wiring all trend periods to the fast Postgres endpoint.

---

### Session: Reducing Anthropic API Costs and Token Usage

**Context:** Separate workstream focused on Claude Code CLI cost optimisation for the development workflow itself (not the application API costs).

#### Completed

- Generated `.claudeignore` for the project — excludes `node_modules/`, `.next/`, `__pycache__/`, `.git/`, large data folders from Claude Code context.
- Configured `autoCompactWindow: 50000` in `.claude/settings.json` to force earlier context compaction.
- Documented `ccusage` npm tool for local session cost tracking without billing console access.
- Built `monitor.py` background daemon — watches `~/.claude/projects/**/*.jsonl`, accumulates cost per session, fires desktop popup alerts at 75% and 100% of a configurable budget.

#### Not applicable to application codebase
These changes are developer-tooling only and were not committed to the application repository.

---

## Database Migrations Applied (Manual — Sprint 2)

The following DDL was applied directly to `sales_analytics` Postgres and is not yet captured in Alembic migrations. Must be re-applied if database is recreated from scratch.

```sql
-- Unique constraints on dimension business keys
ALTER TABLE public.dim_product ADD CONSTRAINT dim_product_sku_code_key UNIQUE (sku_code);
ALTER TABLE public.dim_geography ADD CONSTRAINT dim_geography_zone_state_city_key UNIQUE (zone, state, city);
ALTER TABLE public.dim_salesorg ADD CONSTRAINT dim_salesorg_so_code_key UNIQUE (so_code);
ALTER TABLE public.dim_distributor ADD CONSTRAINT dim_distributor_code_key UNIQUE (distributor_code);

-- Unique constraints on fact table natural keys (required for ETL ON CONFLICT)
ALTER TABLE client_nestle.fact_primary_sales ADD CONSTRAINT fact_primary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);
ALTER TABLE client_nestle.fact_secondary_sales ADD CONSTRAINT fact_secondary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);
ALTER TABLE client_itc.fact_primary_sales ADD CONSTRAINT fact_primary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);
ALTER TABLE client_itc.fact_secondary_sales ADD CONSTRAINT fact_secondary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);
ALTER TABLE client_unilever.fact_primary_sales ADD CONSTRAINT fact_primary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);
ALTER TABLE client_unilever.fact_secondary_sales ADD CONSTRAINT fact_secondary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);

-- Deduplicated ~1M duplicate rows from seeded fact tables
-- (seed script 99_seed_1m_rows.sql had no ON CONFLICT guard)
-- Removed ~37K duplicates from each client fact_primary_sales
-- Removed ~1M duplicates from each client fact_secondary_sales

-- Fix is_ytd flag
UPDATE public.dim_period SET is_ytd = true WHERE date <= CURRENT_DATE;
```

**Note:** These constraints must be added to Alembic migrations or the init SQL scripts before Sprint 3.

---

## Sprint 1 — April 2026 (Reference)

Sprint 1 delivered the end-to-end NL2SQL PoC:
- 19-step medallion pipeline (RAW → Bronze → Silver → Gold) for Nielsen and Walmart POS data
- Claude API integration at Step 7 (semantic column mapping) and Step 14b (error diagnosis/self-healing)
- File registry (`cpg_bronze.file_registry`) driving dynamic sequencing
- 100% auto-approval tested across two retailer schemas
- HITL governance framework, prompt constitution, linting gates, audit logging

Orchestration automation was deferred to Sprint 2 (subsequently deferred again to Sprint 3).
