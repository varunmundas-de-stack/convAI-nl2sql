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

### Infrastructure
| Component | Technology |
|---|---|
| Containerisation | Docker + Docker Compose |
| Message broker | Redis (session store + pub/sub) |
| Port mapping | Frontend :3000 · Backend :8000 · Cube.js :4000 · Postgres :5432 |

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
│  GET  /insights/*   — proactive intel alerts                       │
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
            │ Cube.js REST API             │ SQLAlchemy / psycopg2
            ▼                              ▼
┌───────────────────────┐      ┌───────────────────────────────────┐
│   Cube.js  :4000      │      │   PostgreSQL :5432                │
│                       │      │   sales_analytics DB              │
│  Semantic schema:     │      │                                   │
│  - fact_secondary_    │      │  Tables seeded from               │
│    sales              │◄────►│  cube/data/ SQL scripts           │
│  - dimensions         │      │                                   │
│  - measures           │      │  Also stores:                     │
│  - time dimensions    │      │  - users / tenants (RBAC)         │
│                       │      │  - audit log                      │
│  Multi-tenant RBAC:   │      │  - chat sessions & messages       │
│  queryRewrite injects │      │  - intel insights                 │
│  row-level filters    │      └───────────────────────────────────┘
│  (SO/ASM/ZSM role)    │
└───────────────────────┘
            ▲
            │ JWT-signed token (minted by backend per request)
            └─ cube/cube.js checkAuth validates every Cube query
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
- metrics (e.g. `net_sales`)
- dimensions / group-by (e.g. `sku_name`, `zone`)
- filters (e.g. `zone = North Zone`)
- time window (e.g. `last_30_days`)

### 4. Session Merge
If a `session_id` is supplied, the new QCO is merged with the previous QCO stored in Redis, enabling natural follow-up queries ("break that down by region" resolves against the previous context).

### 5. Clarification Gate
If required fields are missing or ambiguous (e.g. an unrecognised metric name), the pipeline halts at `CLARIFICATION_REQUESTED` and returns a structured clarification prompt to the frontend. The user answers; `POST /clarify` resumes the pipeline from the saved state.

### 6. Validation + RBAC
The validated QCO is checked against the metric/dimension catalog (`catalog/catalog.yaml`). Role-based access control is enforced: an SO-level user can only see their own territory data. Row-level security is implemented via Cube.js `queryRewrite` — the backend mints a JWT carrying the user's `so_code` / `asm_code` / `zsm_code`, and Cube automatically appends `WHERE` filters to every query.

### 7. Cube Query Construction
A Cube.js JSON query object is assembled from the validated QCO (measures, dimensions, timeDimensions, filters, limit).

### 8. Cube Execution
The backend calls `http://cube:4000/cubejs-api/v1/load` with the JSON query and the per-user JWT. Cube.js translates the semantic query into optimised SQL, runs it against PostgreSQL, and returns a result set.

### 9. Insight Generation + Visual Spec
Claude narrates the result set into a human-readable insight paragraph. A separate Claude call produces a **visual spec** (chart type, x-axis, y-axis, colour encoding) that the frontend uses to render the correct chart (bar, line, scatter, table).

### 10. Response
The full response — data rows, narrative insight, visual spec, and request metadata — is returned to the frontend as JSON and rendered in the `MessageBubble` component.

---

## Key Features

- **Conversational context** — follow-up questions resolve against prior query context stored in Redis per session.
- **Clarification loop** — the pipeline pauses and asks the user when intent is ambiguous; conversation is resumed seamlessly.
- **Retry flow** — users can edit a failed or unsatisfactory query inline; the system re-runs the pipeline with the modified text and logs the delta for RLHF.
- **Multi-tenant RBAC** — JWT-based row-level security enforced at the Cube.js semantic layer; every role (SO, ASM, ZSM, Admin) sees only their authorised data slice.
- **Proactive Intel Insights** — a background scheduler (APScheduler) runs statistical detectors (anomaly z-score, trend regression, target-gap, inactivity) against the warehouse and surfaces prioritised alerts on the `/insights` page.
- **RLHF feedback loop** — user thumbs-up/down on responses feeds a SQLite-backed RLHF system with A/B prompt routing and an Optuna-driven optimizer.
- **OpenTelemetry tracing** — every pipeline stage emits spans with input/output values for observability via Arize Phoenix.
- **Dashboard** — a pre-built KPI dashboard (`/dashboard`) shows real-time cards, sparklines, zone performance bars, and quick-action buttons that inject pre-formed queries into the chat.

---

## Running the App

### Prerequisites
- Docker and Docker Compose installed
- An Anthropic API key

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd nl2sql

# Copy and populate environment variables
cp .env.example .env
# Edit .env — minimum required: ANTHROPIC_API_KEY
```

### Start

```bash
docker compose up --build
```

Services start in dependency order:
1. PostgreSQL initialises and seeds the `sales_analytics` schema
2. Redis starts
3. Cube.js connects to Postgres and loads the semantic model
4. FastAPI backend starts (health-checked on `:8000/health`)
5. Next.js frontend builds and serves on `:3000`

Open `http://localhost:3000` in your browser.

Default login credentials are seeded via the database init scripts. Check with your team for access.

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
| `LOG_LEVEL` | No | `INFO` | Python log level (DEBUG / INFO / WARNING) |

Database, Redis, and Cube connection strings are pre-configured in `docker-compose.yml` for the internal Docker network. Override as needed for production deployments.

---

## Project Structure

```
nl2sql/
├── docker-compose.yml          # Orchestrates all five services
├── frontend/                   # Next.js application
│   └── src/
│       ├── app/
│       │   ├── page.tsx        # Root — renders ChatWindow
│       │   ├── dashboard/      # KPI dashboard page
│       │   ├── insights/       # Intel insights page
│       │   └── globals.css     # Design tokens + Tailwind config
│       ├── components/
│       │   ├── ChatWindow.tsx  # Main chat UI + sidebar + auth
│       │   └── MessageBubble.tsx
│       ├── services/api.ts     # Backend API client
│       └── state/conversation.ts
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # FastAPI app, routes, middleware
│       ├── pipeline/           # Stage engine (context, runner, state)
│       ├── services/
│       │   ├── query_orchestrator.py   # Public pipeline API
│       │   ├── intent/         # Extraction, merge, validation
│       │   ├── cube/           # Cube.js query builder + executor
│       │   ├── insights/       # Intel insight detectors
│       │   └── tools/          # Compound/multi-query tools
│       ├── dspy_pipeline/      # DSPy signatures and clarification tool
│       ├── llm/                # Claude client wrapper
│       ├── security/           # JWT auth, RBAC, metadata store
│       ├── rlhf/               # Feedback DB, prompt A/B, scheduler
│       ├── intel/              # Proactive analytics scheduler
│       ├── models/             # Pydantic + SQLAlchemy models
│       └── catalog/            # catalog.yaml — metrics & dimensions
└── cube/
    ├── cube.js                 # Auth, queryRewrite, multi-tenant config
    ├── model/                  # Cube.js schema (cubes, measures, dims)
    └── data/                   # PostgreSQL seed SQL scripts
```
