# Repository Guidelines

## Project Structure & Module Organization

This repository contains an NL2SQL analytics app with a FastAPI backend, Next.js frontend, and Cube/PostgreSQL semantic layer.

- `backend/app/main.py` exposes the API entrypoint.
- `backend/app/services/`, `backend/app/pipeline/`, and `backend/app/dspy_pipeline/` hold orchestration, deterministic query logic, and LLM intent extraction.
- `backend/app/models/` and `backend/app/dspy_pipeline/schemas/` define shared data contracts.
- `backend/app/tests/` contains pytest coverage; snapshots live in `backend/app/tests/snapshots/`.
- `backend/catalog/catalog.yaml` is the semantic validation catalog.
- `frontend/src/` contains the Next.js app, components, services, state, types, and utilities.
- `cube/model/` and `cube/data/` define Cube models and seed SQL data.

## Build, Test, and Development Commands

- `.\start-dev.ps1` starts Docker services, populates PostgreSQL, and runs FastAPI.
- `docker compose up -d` starts PostgreSQL, Redis, and Cube.js without the backend process.
- `venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` runs the backend from `backend/`.
- `pytest` runs backend tests using `pytest.ini`.
- `cd frontend; npm run dev` starts the Next.js dev server.
- `cd frontend; npm run build` builds the production frontend.
- `cd frontend; npm run lint` runs ESLint.

## Coding Style & Naming Conventions

Use Python modules and functions in `snake_case`; use classes and Pydantic-style models in `PascalCase`. Keep backend changes aligned with the guardrails-first architecture: LLM code extracts structured intent, while validation and Cube query construction stay deterministic. For TypeScript/React, use component names in `PascalCase`, hooks/utilities in `camelCase`, and shared types under `frontend/src/types/`.

## Testing Guidelines

Backend tests use pytest and are discovered under `backend/app/tests` with `test_*.py` naming. Add focused tests for catalog validation, date/period logic, Cube query generation, RLHF flows, and visual specs. Run `pytest` before backend PRs. For frontend changes, run `npm run lint` and `npm run build`; add UI-level tests only when a test framework is introduced.

## Commit & Pull Request Guidelines

Recent commits use short, direct subjects such as `bug: insight engine` and `Resolve merge conflict in README.md`. Keep commits imperative and scoped; prefer prefixes like `bug:`, `feat:`, or `docs:` when useful. Pull requests should include a summary, test results, linked issue or context, and screenshots for visible frontend changes. Call out any `.env`, Docker, catalog, or data impact.

## Security & Configuration Tips

Do not commit real secrets. Keep local credentials in `.env` files and use the Docker defaults only for development. Preserve the safety boundary that prevents LLM-generated SQL; route all executable queries through validated Cube.js query objects.
