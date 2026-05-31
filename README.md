# CPG Analytics — NL2SQL

A production-grade natural language to SQL analytics platform for FMCG / CPG sales intelligence. Users type plain-English questions; the system translates them into structured Cube.js queries, executes them against a PostgreSQL data warehouse, and returns data with AI-generated narrative insights and chart recommendations — all without writing a single line of SQL.

---

## Tech Stack

### Frontend
| Layer | Technology |
|---|---|
| Framework | Next.js 14 (App Router, React Server / Client Components) |
| Language | TypeScript |
| Styling | Tailwind CSS (custom design tokens in `globals.css`) |
| Icons | Lucide React |
| State | React `useState` / custom `useConversation` hook |
| API calls | Custom `services/api.ts` (fetch wrapper) |

### Backend
| Layer | Technology |
|---|---|
| Framework | FastAPI 0.129 + Uvicorn |
| Language | Python 3.12 |
| LLM | Anthropic Claude (configurable model via `ANTHROPIC_MODEL_ID`) |
| Prompt engineering | DSPy 2.5 — typed signatures and compiled optimizers |
| Auth | JWT (PyJWT + bcrypt), Cube.js token minting |
| Database ORM | SQLAlchemy 2 + Alembic migrations |
| Caching / sessions | Redis 7 |
| Observability | OpenTelemetry + Arize Phoenix tracing |
| RLHF | SQLite sidecar DB (`rlhf.db`), APScheduler, A/B prompt router |
| Background jobs | APScheduler (intel insight generation) |
| Data science | pandas, numpy, scikit-learn (via optuna/datasets) |

### Data Layer
| Component | Technology |
|---|---|
| Warehouse | PostgreSQL 15 — `sales_analytics` database |
| Semantic layer | Cube.js (latest) — schema models in `cube/model/` |
| Data seed | SQL init scripts in `cube/data/` |
| ETL pipeline | Python watch-mode CSV ingestion (`backend/etl/`) |

### Infrastructure
| Component | Technology |
|---|---|
| Containerisation | Docker + Docker Compose (6 services) |
| Message broker | Redis (session store + pub/sub) |
| Port mapping | Frontend :3000 · Backend :8000 · Cube.js :4000 · Postgres :5432 |
| ETL watcher | Dedicated `nl2sql-etl-watcher` container (watch-mode CSV ingestion) |
| Cloud | AWS EC2 t3.medium (us-east-1b) — `cpg-sales-demo` instance |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser (Next.js)                           │
│                                                                     │
│   /           Chat window — conversational NL query interface       │
│   /dashboard  KPI cards, zone performance, quick-action launcher    │
│   /insights   Intel insights — AI-generated anomaly/trend alerts    │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP / REST  (NEXT_PUBLIC_API_BASE)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend  :8000                           │
│                                                                     │
│  POST /query        — main NL→SQL pipeline                         │
│  POST /clarify      — resume a paused pipeline                     │
│  POST /retry        — refine a previous result                     │
│  GET  /catalog/*    — metrics / dimensions / time-windows          │
│  GET  /insights     — role-aware proactive intel alerts             │
│  GET  /dashboard/kpis — optimised KPI endpoint (<2s response)      │
│  /auth/*            — login, token refresh, user info              │
│  /rlhf/*            — feedback, prompt A/B, RLHF scheduler         │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Query Orchestrator (pipeline engine)           │   │
│  │                                                             │   │
│  │  1. Intent Extraction   (Claude + DSPy signature)           │   │
│  │  2. Intent Merge        (fold into session QCO)             │   │
│  │  3. Clarification Gate  (ask user if fields are missing)    │   │
│  │  4. Intent Validation   (RBAC + catalog cross-check)        │   │
│  │  5. Cube Query Builder  (JSON query for Cube.js REST API)   │   │
│  │  6. Cube Execution      (HTTP call → Cube.js :4000)         │   │
│  │  7. Insight Generation  (Claude narrates the result set)    │   │
│  │  8. Insight Refinement  (RLHF-tuned prompt variant)         │   │
│  │  9. Visual Spec         (chart type + axis recommendation)  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Security: JWT auth middleware · Cube token minting per user       │
│  Storage:  PostgreSQL (audit log, chat history) · Redis (sessions) │
│  RLHF:     SQLite sidecar · APScheduler · A/B prompt router        │
└───────────┬──────────────────────────────┬──────────────────────────┘
            │ Cube.js REST API             │ optimised data layer
            ▼                              ▼
┌───────────────────────┐      ┌───────────────────────────────────┐
│   Cube.js  :4000      │      │   PostgreSQL :5432                │
│                       │      │   sales_analytics DB              │
│  Semantic schema:     │      │                                   │
│  - fact_secondary_    │      │  Schemas:                         │
│    sales              │◄────►│  - client_nestle (fact tables)    │
│  - fact_primary_sales │      │  - client_itc (fact tables)       │
│  - dim_* (shared)     │      │  - client_unilever (fact tables)  │
│                       │      │  - public (shared dimensions)     │
│  Multi-tenant RBAC:   │      │  - app_meta (users, insights)     │
│  queryRewrite injects │      │                                   │
│  row-level filters    │      │  ~1M rows fact_secondary_sales    │
│  (SO/ASM/ZSM role)    │      │  ~34K rows fact_primary_sales     │
└───────────────────────┘      └───────────────┬───────────────────┘
            ▲                                  ▲
            │ JWT-signed token                 │
            └─ cube/cube.js checkAuth          │
                                   ┌───────────┴───────────────────┐
                                   │   ETL Watcher Container        │
                                   │   nl2sql-etl-watcher           │
                                   │                               │
                                   │  Watches: /app/etl/data/      │
                                   │           drop_zone/          │
                                   │  Poll: every 30 seconds       │
                                   │  Auto-detects: primary vs     │
                                   │  secondary from filename      │
                                   │  Upserts: all dim tables +    │
                                   │  fact tables with ON CONFLICT │
                                   │  Moves: processed files to    │
                                   │  processed/ with timestamp    │
                                   └───────────────────────────────┘
```

---

## How It Works — End to End

### 1. Authentication
The user logs in via the frontend (`POST /auth/login`). The backend validates credentials from PostgreSQL, returns a JWT. A Cube.js-specific JWT (signed with `CUBEJS_API_SECRET`, carrying the user's role and hierarchy codes) is minted server-side for each request — the browser never holds a Cube token.

### 2. Natural Language Query
The user types a question such as:
> "Show me top 10 SKUs by net sales in North Zone for last 30 days"

The frontend calls `POST /query` with the text and an optional `session_id`.

### 3. Intent Extraction (Claude + DSPy)
The backend runs the **Query Orchestrator** — a linear pipeline of named stages. The first step calls Claude via a DSPy-compiled signature to extract a structured **Query Context Object (QCO)**:
- metrics (e.g. `net_value`)
- dimensions / group-by (e.g. `brand`, `zone`)
- filters (e.g. `zone = North Zone`)
- time window (e.g. `last_30_days`)
- sales scope (PRIMARY or SECONDARY)

### 4. Session Merge
If a `session_id` is supplied, the new QCO is merged with the previous QCO stored in Redis, enabling natural follow-up queries ("break that down by region" resolves against the previous context).

### 5. Clarification Gate
If required fields are missing or ambiguous, the pipeline halts at `CLARIFICATION_REQUESTED` and returns a structured clarification prompt to the frontend. The user answers; `POST /clarify` resumes the pipeline from the saved state. Clarification chips are now scope-aware — secondary-only dimensions (retailer, route, salesrep) are hidden when sales scope is PRIMARY.

### 6. Validation + RBAC
The validated QCO is checked against the metric/dimension catalog (`catalog/catalog.yaml`). Role-based access control is enforced: an SO-level user can only see their own territory data. Row-level security is implemented via Cube.js `queryRewrite`.

### 7. Cube Query Construction
A Cube.js JSON query object is assembled from the validated QCO (measures, dimensions, timeDimensions, filters, limit).

### 8. Cube Execution
The backend calls `http://cube:4000/cubejs-api/v1/load` with the JSON query and the per-user JWT. Cube.js translates the semantic query into optimised SQL, runs it against PostgreSQL, and returns a result set.

### 9. Insight Generation + Visual Spec
Claude narrates the result set into a human-readable insight paragraph. A separate Claude call produces a **visual spec** (chart type, x-axis, y-axis, colour encoding) that the frontend uses to render the correct chart.

### 10. Response
The full response — data rows, narrative insight, visual spec, and request metadata — is returned to the frontend as JSON and rendered in the `MessageBubble` component.

---

## Key Features

- **3-Tier Intelligent Query Cache** — repeated or semantically similar questions are served from cache without invoking the full pipeline:
  - *Tier 1 — Golden Q&A (in-memory FAISS):* A curated set of high-frequency questions is pre-embedded at startup. Cosine similarity ≥ 0.95 returns an instant pre-computed answer — zero LLM calls, zero latency.
  - *Tier 2 — Semantic Redis Cache (per user):* Every live pipeline response is embedded and stored in Redis keyed by user. Subsequent questions with cosine similarity ≥ 0.92 are served from cache, skipping DSPy intent extraction, Cube query building, and Claude narration entirely.
  - *Tier 3 — Live Pipeline:* Full NL→SQL pipeline runs only on genuine cache misses.
- **Persistent User Memory** — the last 20 conversation turns per user are stored in a SQLite sidecar (`memory.db`). When a new question arrives, the system retrieves prior intent patterns for that user and injects them as context, enabling the pipeline to resolve ambiguous follow-up queries more accurately over time.
- **Conversational context** — follow-up questions resolve against prior query context stored in Redis per session.
- **Clarification loop** — the pipeline pauses and asks the user when intent is ambiguous; conversation is resumed seamlessly.
- **Scope-aware dimension chips** — clarification options are filtered by PRIMARY/SECONDARY sales scope; secondary-only dimensions (retailer, route, salesrep) are hidden for primary queries.
- **Retry flow** — users can edit a failed or unsatisfactory query inline.
- **Multi-tenant RBAC** — JWT-based row-level security enforced at the Cube.js semantic layer.
- **Role-aware Intel Insights** — 8 non-obvious statistical detectors tuned to the latest data: SKU concentration risk, zone velocity divergence, dormant high-value brand, weekday/weekend sales pattern, emerging SKU momentum, end-of-month channel stuffing, distributor dependency, and pack size mix shift.
- **Fast Dashboard KPIs** — `/dashboard/kpis` returns pre-computed KPIs in under 2 seconds, fine-tuned to the latest available data window.
- **CSV ETL Pipeline** — watch-mode ingestion service (`etl-watcher`) automatically detects and loads CSV files dropped into a designated folder, upserts all dimension tables and fact tables, and archives processed files.
- **RLHF feedback loop** — user thumbs-up/down on responses feeds a SQLite-backed RLHF system.
- **OpenTelemetry tracing** — every pipeline stage emits spans for observability via Arize Phoenix.

---

## ETL Pipeline

A dedicated `etl-watcher` Docker service continuously monitors a drop-zone folder for CSV files and ingests them automatically.

### Folder Structure
```
backend/etl/
├── cpg_etl.py              # ETL pipeline script
├── __init__.py
└── data/
    ├── drop_zone/          # Drop CSV files here for auto-ingestion
    └── processed/          # Processed files archived here with timestamp
```

### File Naming Convention
| Filename pattern | Target | Tenant |
|---|---|---|
| `*secondary*` or `*sec_*` | `fact_secondary_sales` | from `--tenant` arg |
| `*primary*` or `*pri_*` | `fact_primary_sales` | from `--tenant` arg |

### What the ETL does per file
1. Upserts `dim_product` (by `sku_code`)
2. Upserts `dim_geography` (by `zone, state, city`)
3. Upserts `dim_period` (by `date`)
4. Upserts `dim_salesorg` (by `so_code`)
5. Upserts `dim_distributor` (by `distributor_code`)
6. Loads fact table rows (`ON CONFLICT DO UPDATE`)
7. Moves file to `processed/` with `YYYYMMDD_HHMMSS_` prefix

### CSV Column Reference
See `backend/etl/data/sample_secondary_sales.csv` and `sample_primary_sales.csv` for the expected column layout.

---

## Running the App

### Prerequisites
- Docker and Docker Compose installed
- An Anthropic API key

### Setup

```bash
git clone https://github.com/varunmundas-de-stack/convAI-nl2sql
cd nl2sql
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY, CUBEJS_API_SECRET, APP_JWT_SECRET
```

### Start

```bash
docker compose up --build
```

Six services start in dependency order:
1. PostgreSQL — initialises and seeds `sales_analytics` schema
2. Redis
3. Cube.js — connects to Postgres, loads semantic model
4. FastAPI backend — health-checked on `:8000/health`
5. Next.js frontend — serves on `:3000`
6. ETL watcher — begins watching `backend/etl/data/drop_zone/`

Open `http://localhost:3000`.

### Stop

```bash
docker compose down
# To also delete database volumes:
docker compose down -v
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for Claude |
| `ANTHROPIC_MODEL_ID` | No | `claude-haiku-4-5-20251001` | Claude model to use |
| `CUBEJS_API_SECRET` | Yes | — | Shared secret for Cube.js JWT signing |
| `APP_JWT_SECRET` | Yes | — | Secret for user-facing JWT auth |
| `LOG_LEVEL` | No | `INFO` | Python log level |

---

## Project Structure

```
nl2sql/
├── docker-compose.yml              # Orchestrates all six services
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx            # Root — renders ChatWindow
│       │   ├── dashboard/          # KPI dashboard (direct Postgres)
│       │   ├── insights/           # Role-aware intel insights page
│       │   └── globals.css
│       ├── components/
│       │   ├── ChatWindow.tsx      # Chat UI + scope-aware dimension chips
│       │   └── MessageBubble.tsx
│       ├── services/api.ts         # Backend API client + getDashboardKpis
│       └── state/conversation.ts
├── backend/
│   ├── Dockerfile                  # Includes etl/ folder
│   ├── requirements.txt            # Includes tenacity
│   └── app/
│       ├── main.py                 # FastAPI app, routes, middleware
│       ├── insight_generator.py    # 8 role-aware Postgres insight probes
│       ├── insights_router.py      # Insights REST router
│       ├── pipeline/               # Stage engine
│       ├── services/
│       │   ├── cube/
│       │   │   └── cube_query_builder.py  # Fixed _build_valid_dimensions()
│       │   └── intent/
│       │       ├── intent_normalizer.py   # DIMENSION_MAP with scope routing
│       │       └── intent_validator.py
│       ├── dspy_pipeline/
│       │   └── schemas/
│       │       └── catalog.py      # Cleaned COMMON_DIMENSIONS (no dim_* leaks)
│       ├── security/
│       │   └── metadata_store.py   # list_insights() uses insight_generator
│       └── catalog/catalog.yaml
│   └── etl/
│       ├── cpg_etl.py              # Watch-mode CSV ingestion pipeline
│       ├── __init__.py
│       └── data/
│           ├── drop_zone/          # Drop CSV files here
│           └── processed/          # Auto-archived after ingestion
└── cube/
    ├── cube.js
    ├── model/                      # Cube.js schema
    └── data/                       # PostgreSQL seed SQL scripts
```

---

## Cloud Deployment (AWS EC2)

The application is deployed on an EC2 t3.medium instance (`cpg-sales-demo`, us-east-1b).

```bash
# SSH
ssh -i cpg-sales-key.pem ubuntu@<EC2_PUBLIC_IP>

# Deploy latest
cd ~/nl2sql
git pull
docker compose -f docker-compose.yml build --build-arg NEXT_PUBLIC_API_BASE=http://<EC2_PUBLIC_IP>:8000 frontend
docker compose -f docker-compose.yml up -d --build
```

Security group must allow inbound TCP on ports 3000 and 8000.
