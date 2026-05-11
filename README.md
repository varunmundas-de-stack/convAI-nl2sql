# convAI-nl2sql

Multi-tenant conversational AI for CPG sales analytics — ask questions in plain English, get data-driven insights.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (TypeScript) |
| Backend | FastAPI (Python) |
| Database | PostgreSQL |
| Cache / Sessions | Redis |
| Semantic Layer | CubeJS |
| AI / LLM | Claude AI (Anthropic) + DSPy pipeline |

## Features

- **Multi-tenant RBAC** — JWT-based auth with role-scoped data access per tenant
- **NL2SQL pipeline** — LLM extracts intent; CubeJS compiles deterministic SQL (no AI-generated SQL)
- **AI-powered insights** — DSPy pipeline generates summaries, trend detection, and anomaly flagging
- **Dashboard drill-down** — Interactive charts with slice-and-dice from summary to detail
- **RLHF feedback loop** — Users rate responses; feedback drives continuous prompt improvement

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY, CUBEJS_API_SECRET, APP_JWT_SECRET, POSTGRES_PASSWORD

# 2. Build and start all services
docker compose up --build -d

# 3. Open the app
open http://localhost:3000
```

## Auth

- JWT-based authentication
- Default admin credentials are set via environment variables at first run
- Roles: `admin`, `analyst`, `viewer` — each scoped to one or more tenants

## Project Structure

```
backend/      FastAPI app, DSPy pipeline, LLM tools
frontend/     Next.js 14 UI (chat, dashboard, insights, RLHF)
cube/         CubeJS semantic layer schema
aws-deploy/   AWS deployment manifests and scripts
```

## AWS Deployment

See `aws-deploy/` for ECS task definitions, RDS, ElastiCache, and ALB configuration.

## Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `ANTHROPIC_MODEL_ID` | Claude model ID (e.g. `claude-sonnet-4-6`) |
| `CUBEJS_API_SECRET` | Shared secret for CubeJS JWT signing (min 32 chars) |
| `APP_JWT_SECRET` | Secret for app-level JWT auth tokens |
| `POSTGRES_PASSWORD` | PostgreSQL password |
