# NL2SQL: Natural Language Analytics Interface

## 1. Project Overview

**NL2SQL** is an analytics interface that enables business users to query FMCG (Fast-Moving Consumer Goods) sales data using plain English questions instead of SQL. The system combines rule-based validation with LLM reasoning to generate accurate, safe queries without ever allowing the AI to write SQL directly.

**What the system does:**
- Accepts natural language questions from users (e.g., "What were our sales in the North region last month?")
- Understands user intent and maps it to business metrics and dimensions
- Validates the request against a business catalog to ensure accuracy
- Delegates all SQL generation and execution to Cube.js, a semantic data layer
- Returns structured data and visualization specifications for frontend display

**The problem it solves:**
- Democratizes data access for non-technical business users
- Eliminates manual SQL query writing by analysts
- Reduces errors by enforcing structured validation over generative freedom

**The overall approach:**
A "guardrails-first" architecture that prioritizes safety and accuracy over AI flexibility. The LLM handles only intent extraction; deterministic rule-based systems handle all structural transformations and validation.

---

## 2. Problem Statement

**Business context:**
- Data analysts spend significant time writing SQL queries for business stakeholders
- Business teams cannot directly query databases, creating a bottleneck
- Manual analytics requests introduce delays and errors
- SQL expertise is a scarce resource

**Technical challenge:**
- Naive generative AI systems (LLMs that write SQL) are unreliable—they hallucinate table names, generate incorrect syntax, and produce unsafe queries
- Pure rule-based systems lack the flexibility to understand natural language variation

**Solution goal:**
Enable users to retrieve insights using natural language queries while maintaining safety, accuracy, and performance. The system must never allow the LLM to write SQL; instead, use the LLM only for understanding intent, then translate to validated, deterministic queries.

---

## 3. System Overview

The system is composed of distinct layers, each with a specific responsibility:

**User Interface (Next.js)**
- Web-based conversational interface
- Displays query results and visualizations
- Maintains session context across multiple queries

**Query Orchestrator (FastAPI Backend)**
- Accepts natural language questions
- Manages the entire query processing pipeline
- Coordinates interactions between the LLM, validation layer, and data layer
- Returns structured responses

**Modular Service Tools**
- **CatalogTool:** Semantic catalog management and metric/dimension validation
- **CubeClientTool:** HTTP transport to Cube.js API with retry logic
- **VisualSpecTool:** Chart specification generation and compound visualization support
- **PivotUtilsTool:** Data transformation, pivoting, and field normalization
- **NormalizerTool:** Intent normalization, trend patching, and field mapping
- Managed via an **Integration Layer** for seamless composability and testing

**Intent Extractor (LLM - Anthropic Claude)**
- Processes natural language questions
- Extracts structured intent: metrics, filters, dimensions, time ranges
- Leverages session history for follow-up question resolution
- Never generates SQL

**Semantic Validation Layer**
- Validates extracted intent against the business catalog
- Checks metric existence, dimension compatibility, filter validity
- Triggers clarification requests when queries are ambiguous
- Maps semantic names to physical database identifiers

**Query Compiler**
- Deterministically converts validated intent to Cube.js query format
- No AI involved—pure mechanical translation

**Data Layer (Cube.js + PostgreSQL)**
- Cube.js acts as the semantic layer, generating SQL from validated queries
- PostgreSQL stores the raw FMCG sales data
- Cube.js handles caching, optimization, and SQL dialect specifics

**Conversational Context (Redis)**
- Stores session state (previous queries, resolved metrics)
- Enables follow-up questions like "how about in a different region?"

---

## 4. System Workflow

A complete query follows this workflow:

1. **User submits a question** via the frontend (e.g., "Sales by region for Q1?")

2. **Backend loads conversation context** from Redis using the session ID to support follow-up questions

3. **LLM extracts intent** from the natural language question plus prior context, returning structured JSON with:
   - Metrics (what to measure: sales, volume, margin)
   - Filters (conditions: region=North, product=Soap)
   - Group-by dimensions (how to slice: by region, by time period)
   - Time range (last 30 days, specific dates, etc.)

4. **Intent is merged with session history** to handle follow-ups (e.g., previous query context informs "the region" reference)

5. **Semantic validation occurs** against `catalog.yaml`:
   - Does the metric exist in the business data model?
   - Is the dimension valid for analysis?
   - Are filters applicable?
   - If anything is ambiguous or missing, the pipeline stops and returns a clarification request to the user

6. **Validated intent is compiled** into Cube.js JSON query format (deterministic, no AI)

7. **Cube.js executes the query**:
   - Generates dialect-specific SQL
   - Executes against PostgreSQL
   - Returns raw result set

8. **Insights are generated** from results (trend detection, outliers, statistical summary)

9. **Visualization specification is created** (e.g., bar chart config, table schema)

10. **Session state is saved** to Redis for future follow-up queries

11. **Response is returned** with data, visualization spec, natural language summary, and metadata

---

## 5. Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Browser / Frontend                  │
│              (Next.js React Interface)               │
└────────────────────┬────────────────────────────────┘
                     │
              POST /query endpoint
                     │
┌────────────────────▼────────────────────────────────┐
│            FastAPI Backend (Python)                  │
│         - Query Orchestrator (main flow)             │
│         - Integration Layer & Modular Tools          │
│           (Catalog, CubeClient, VisualSpec, etc.)    │
└────┬──────────────────────┬────────────────────┬────┘
     │                      │                    │
     │ (1) Load context     │ (2) Extract intent │ (3) Store state
     │                      │                    │
┌────▼──────────┐  ┌────────▼──────────┐  ┌────▼─────────────┐
│    Redis      │  │  Anthropic API    │  │  PostgreSQL      │
│  (Sessions)   │  │   (Claude LLM)    │  │   (Raw Data)     │
└───────────────┘  └────────┬──────────┘  └──────────────────┘
                            │
                     (4) Semantic Layer
                            │
                   ┌────────▼──────────┐
                   │   Cube.js API     │
                   │  - SQL Generator  │
                   │  - Query Executor │
                   │  - Caching        │
                   └────────┬──────────┘
                            │
                   ┌────────▼──────────┐
                   │   PostgreSQL      │
                   │  (FMCG Data)      │
                   └───────────────────┘
```

**Data flow:**
- Request flows left-to-right through the pipeline
- Each stage validates and enriches the query
- Modular tools (CatalogTool, CubeClientTool, etc.) provide specific processing logic via an Integration Layer
- Redis stores conversational context across requests
- Cube.js generates and executes SQL

---

## 6. Key Design Decisions

**Why the LLM only extracts intent, not SQL:**
- Pure generative SQL is unpredictable (hallucinations, incorrect syntax, unsafe queries)
- Deterministic compilation from validated intent ensures correctness
- Reduces latency and API costs by minimizing LLM invocations

**Why use Cube.js as the semantic layer:**
- Cube.js handles all SQL generation deterministically
- Decouples the backend from database dialect details
- Provides caching and optimization out-of-the-box
- Acts as a guardrail against raw SQL injection

**Why validate against a catalog:**
- `catalog.yaml` is the single source of truth for valid metrics and dimensions
- Validation catches errors early (before query execution)
- Enables ambiguity detection and clarification flows
- Makes the system maintainable—change the catalog, not the code

**Why store session context in Redis:**
- Enables follow-up queries without re-specifying all filters
- Example: "Sales last month?" → "What about this month?" (reuses region filter from prior query)
- Redis key-value design is simple and fast

**Why use structured Intent model (Pydantic):**
- Single contract between all pipeline stages
- Type safety prevents bugs in data transformation
- Validation rules are centralized and testable

**Why use a Modular Service Architecture:**
- Decouples pipeline stages into independently testable and composable tools (CatalogTool, CubeClientTool, etc.)
- Provides consistent error handling, structured logging, and performance metrics across the system
- Legacy compatibility is maintained through an integration layer, ensuring seamless migration

---

## 7. Performance Considerations

**Latency optimization:**
- **Session reuse:** Redis caching means follow-up queries skip LLM calls if intent is clear from context
- **Deterministic compilation:** Rule-based intent-to-query translation is instant (no AI wait)
- **Cube.js caching:** Frequently accessed metrics are cached at the semantic layer

**Reducing LLM dependency:**
- LLM is invoked only for intent extraction (the highest-value use of generative reasoning)
- Schema normalization (semantic-to-physical name mapping) is rule-based
- Validation is deterministic

**Query optimization:**
- Cube.js optimizes generated SQL before execution
- Pre-aggregated facts reduce data warehouse scan size
- Time-range filters minimize result sets

---

## 8. Limitations

- **Complex nested queries** (e.g., multi-level aggregations, advanced statistical functions) may require manual review or escalation
- **Schema changes** require updating `catalog.yaml`; the system cannot auto-discover new metrics or dimensions
- **Ambiguous questions** may produce multiple valid interpretations, triggering clarification requests
- **LLM latency** affects initial query response time (typically 1-3 seconds)
- **Session context** only persists for the duration of a session; long-term learning across sessions is not implemented
- **Cube.js dependency:** The system cannot function without a running Cube.js service

---

## 9. Future Improvements

- **Semantic query understanding:** Improve LLM prompting to handle more complex multi-part questions
- **Feedback-driven improvements:** Collect user feedback on clarification requests to refine intent extraction
- **Query result caching:** Cache popular queries to reduce latency on repeated questions
- **Multi-language support:** Extend LLM prompting to support queries in languages beyond English
- **Adaptive clarification:** Machine learning on clarification patterns to predict which questions need disambiguation
- **Advanced analytics:** Integrate statistical models for forecasting, anomaly detection, or causal analysis
- **Row-level security:** Extend validation layer to enforce data governance policies
- **Query audit trail:** Persistent logging of all executed queries for compliance and analysis

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Anthropic API key

### Setup

```bash
# Configure environment
cp .env.example .env
# Edit .env with ANTHROPIC_API_KEY, CUBE_API_URL, REDIS_URL
```

### Full Local Development (Windows)

```bash
# Start all services (Docker + FastAPI with hot-reload)
.\start-dev.ps1

# Stop all services and cleanup
# Ctrl+C will trigger automatic cleanup
```

### Manual Development Setup

If you prefer to start services manually:

```bash
# Start backing services (PostgreSQL, Redis, Cube.js)
docker compose up -d

# Backend (with hot-reload)
cd backend
# Using activated venv: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm run dev
```

### Testing & Tools Demonstration

```bash
cd backend

# Run all tests
pytest

# Run comprehensive Phase 1 tool tests
pytest app/tests/test_phase1_tools.py

# Run Phase 1 tool demonstration script
python demo_phase1_tools.py
```

Visit `http://localhost:3000` to access the interface.

---

## Documentation

- **Architecture Deep Dive:** See `docs/architecture.md`
- **API Reference:** See `docs/api.md`
- **Catalog Schema:** See `backend/catalog/catalog.yaml`
- **Development Guide:** See `docs/development.md`
