# convAI-nl2sql — Language Rewrite Candidates
## Parked: June 2026 — Revisit when concurrent users > 20 or file uploads > 10MB

---

## 1. CSV ETL Pipeline → Go or Rust
**File:** `backend/etl/cpg_etl.py`
**Why:** Python GIL prevents parallel CPU-bound CSV parsing. At 50MB files Python takes 8-10s causing upload timeouts. Go/Rust would process in ~200ms.
**User impact:** Direct — file upload timeout is visible UX failure at scale.
**Trigger to act:** File uploads > 10MB or user complaints about CSV ingest timeouts.
**Effort:** 2 weeks. Go preferred (simpler concurrency model than Rust for this use case).
**Approach:** Rewrite `cpg_etl.py` as a standalone Go binary, call it from FastAPI via subprocess or expose as a microservice on port 8001.

---

## 2. cube_query_builder.py → Go microservice
**File:** `backend/app/services/cube/cube_query_builder.py` (372 lines)
**Why:** Pure CPU-bound dict/string manipulation. Python: ~30ms. Go: <1ms. Invisible to single user but at 50+ concurrent queries Python GIL queues requests causing latency spikes.
**User impact:** Invisible now. Visible at 50+ concurrent users as query latency degrades.
**Trigger to act:** Concurrent users consistently > 30 or p95 latency > 5s on /query.
**Effort:** 1 week. Expose as HTTP microservice, replace CubeQueryBuilder Python class with HTTP call.
**Note:** Keep Python wrapper for fallback. Gradual migration.

---

## 3. LLM Response Streaming — Correct Architecture (not a language change)
**Current state:** Parked — DSPy thread-local LM issue breaks clarification on worker threads.
**Correct fix (language-agnostic):**
- Add a Redis pub/sub channel per request_id
- Pipeline steps publish stage labels to the channel after each step
- New `/query/progress/{request_id}` SSE endpoint subscribes to the channel
- Frontend calls `/query` normally (unchanged) + opens SSE to `/query/progress/{request_id}` simultaneously
- No monkey-patching, no thread pools, no DSPy context issues
**Files to change:** `main.py` (new SSE endpoint), `runner.py` (publish to Redis after each step), `ChatWindow.tsx` (open SSE connection alongside regular fetch)
**Effort:** 3 days once Redis pub/sub approach is confirmed.
**Trigger to act:** When DSPy thread-local issue is resolved OR when Redis pub/sub approach is validated.

---

## 4. What NOT to Rewrite (confirmed)
- FastAPI backend → Python async is fast enough; bottleneck is LLM network latency
- Authentication layer → security rewrites introduce risk disproportionate to gain
- PostgreSQL queries → SQL is already the right language; add indexes instead
- LLM pipeline steps → waiting 3-5s on Claude API; language saves microseconds against seconds
- Frontend → already TypeScript/Next.js, correct language

---

## Decision Framework
Rewrite only when:
1. A specific bottleneck is **measured** (not assumed) via profiling
2. The rewrite affects something **user-visible** (not just architecturally elegant)
3. The effort is proportionate to the user count / revenue at that point

Current user count threshold for Go rewrites: **> 20 concurrent users sustained**
Current file size threshold for ETL rewrite: **> 10MB uploads**
