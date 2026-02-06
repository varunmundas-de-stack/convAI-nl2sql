# Technical Documentation: NL2SQL Analytics System

## 1. Executive Summary

This document details the architecture, design, and implementation of the Natural Language to SQL (NL2SQL) Analytics System. The system empowers business users to query FMCG sales and invoice data using natural language, providing validated, explainable insights without requiring knowledge of SQL or the underlying database schema.

The system is built on a "Guardrails First" philosophy, prioritizing accuracy and safety over unrestricted flexibility. It leverages a semantic layer (Cube) for query execution and a Large Language Model (LLM) for intent extraction, with a rigorous validation layer in between to ensure deterministic and correct behavior.

## 2. Problem Statement and Goals

### Problem
Business users need access to historical sales data (Primary and Secondary) across complex hierarchies (Zones, States, Distributors, Retailers). Traditional BI tools require technical skills, and direct SQL access is unsafe and complex. Users need a conversational interface that understands business terminology (e.g., "Secondary Sales", "Offtake") and maps it correctly to the data.

### Goals
*   **Accuracy**: Ensure queries map correctly to business metrics.
*   **Safety**: Prevent invalid or malicious queries from reaching the database.
*   **Explainability**: Provide clear feedback on how a query was interpreted.
*   **Performance**: Leverage pre-aggregations and caching via Cube.

### Non-Goals
*   **Real-time Streaming**: The system focuses on historical decision support, not sub-second real-time monitoring.
*   **Data Entry/Write Access**: The system is read-only.
*   **Arbitrary SQL Generation**: The LLM does not generate SQL directly; it generates *Intent*, which is mechanically translated to a Cube query.

## 3. High-Level Architecture

The system follows a pipeline architecture where data flows through distinct stages of processing, validation, and execution.

### 3.1 Data Flow Pipeline

1.  **Natural Language Query**: User submits a query (e.g., "Show me top 5 distributors by sales").
2.  **Intent Extraction (LLM)**: The query is sent to the LLM with a prompt containing the business catalog. The LLM returns a structured JSON "Intent".
3.  **Normalization & Validation**:
    *   *Normalization*: Semantic terms are mapped to physical Cube IDs (e.g., "sales" -> `fact_secondary_sales.net_value`).
    *   *Validation*: The Intent is checked against the Catalog (valid metrics, dimensions, time windows) and structural rules.
4.  **Query Generation**: The validated Intent is deterministically translated into a Cube Query format.
5.  **Query Execution (Cube)**: The Cube Query is sent to the Cube API. Cube handles SQL generation, execution against PostgreSQL, and caching.
6.  **Response Generation**: Data is formatted for visualization or textual summary.

### 3.2 Component Architecture & Folder Structure

The codebase is organized to enforce separation of concerns:

```
backend/
├── app/
│   ├── main.py                 # Entry point (FastAPI). Thin HTTP layer.
│   ├── pipeline/               # Pipeline state management.
│   ├── services/
│   │   ├── query_orchestrator.py # Core logic. Coordinates the pipeline steps.
│   │   ├── intent_extractor.py   # Interface to LLM (Claude). Returns raw JSON.
│   │   ├── intent_normalizer.py  # Maps semantic terms to specific Cube fields.
│   │   ├── intent_validator.py   # Enforces catalog rules and structural validity.
│   │   ├── cube_query_builder.py # Translates Intent -> Cube Query JSON.
│   │   ├── cube_client.py        # HTTP client for Cube API.
│   │   ├── catalog_manager.py    # Loads and serves the business catalog (YAML).
│   │   └── llm_service.py        # Wrapper for Anthropic API.
│   ├── models/                 # Pydantic models for Intent and API schemas.
│   ├── prompts/                # Text prompts for the LLM.
│   └── utils/
│       └── generate_catalog.py # Script to sync Catalog with Cube schema.
├── catalog/                    # Business Catalog definition (metrics, dimensions).
└── tests/                      # Unit and E2E tests.
```

### 3.3 Component Functions

*   **Query Orchestrator**: The central "brain". It calls each service in sequence and handles error propagation. It does not contain business logic itself.
*   **Intent Extractor**: Purely responsible for interacting with the LLM. It manages the prompt and parses the text response into JSON. It handles LLM-specific errors (timeouts, malformed JSON).
*   **Catalog Manager**: Single source of truth for "what exists". Loads `catalog.yaml` and provides lookup methods for valid metrics and dimensions.
*   **Intent Normalizer**: The translation layer. It contains the mapping logic (e.g., resolving ambiguity between Primary and Secondary sales metrics based on context).
*   **Cube Query Builder**: A deterministic compiler that turns the internal `Intent` object into a query payload that Cube understands.

## 4. Core Design Decisions and Tradeoffs

### 4.1 Decoupled Catalog vs. Raw Schema
*   **Decision**: The LLM does *not* see the raw database schema or the Cube schema directly. It sees a simplified "Business Catalog".
*   **Tradeoff**: Requires manual maintenance of the mapping layer (`intent_normalizer.py`), but significantly reduces hallucinations and allows the backend schema to change without breaking the NL interface.

### 4.2 Cube as the Semantic Layer
*   **Decision**: Use Cube instead of generating raw SQL.
*   **Reasoning**: Cube handles complex joins, fan-out issues, time-zone calculations, and caching. The LLM only needs to identify *intent* (Metrics + Dimensions), not SQL syntax.

### 4.3 Deterministic Query Generation
*   **Decision**: The "Builder" step is strict code, not AI.
*   **Reasoning**: Once intent is validated, query generation should never fail or hallucinate. We treat the LLM as a parser, not a coder.

### 4.4 Intent Validation Guardrails
*   **Decision**: All intents must pass strict Pydantic validation against the loaded Catalog.
*   **Reasoning**: Prevents "garbage in, garbage out". If the user asks for a non-existent metric, we fail fast with a clear error rather than guessing.

## 5. Data Model and Source Assumptions

### 5.1 Data Characteristics
*   **Source**: Historical invoice data (~20 months).
*   **Scale**: ~6 Zones, 12 States, ~300 Distributors, ~30k Retailers.
*   **Volume**: ~4 Primary invoices/month, ~200+ Secondary invoices/month.

### 5.2 Modeling Patterns
*   **Fact Tables**: Separated into `fact_primary_sales` (Distributor purchases) and `fact_secondary_sales` (Retailer purchases).
*   **Dimensions**: Shared dimensions (Time, Geography) and specific dimensions (Retailer, Route).
*   **Time Granularity**: Data is daily (invoice date). Supported grains: Day, Week, Month, Quarter, Year.

### 5.3 Schema Management Workflow
When the underlying database schema changes, the following workflow **must** be executed to keep the system in sync:

1.  **Regenerate Cube Schema**: New `cubes/*.yml` files must be generated (typically via Cube's introspection at port 4000).
2.  **Regenerate Catalog**: Run `python -m app.utils.generate_catalog`. This parses the Cube YAMLs and updates `catalog/catalog.yaml`.
3.  **Update Prompt**: Update `backend/app/prompts/intent_extraction.txt` with any new metrics/dimensions or relevant examples.
4.  **Update Normalizer**: Update mappings in `backend/app/services/intent_normalizer.py` to link new semantic terms to Cube IDs.

## 6. Catalog vs Schema Strategy

The system explicitly decouples the **Business Catalog** (User-facing) from the **Cube Schema** (System-facing).

*   **Cube Schema (`cube/model/cubes/*.yml`)**: Defines the physical data model, joins, SQL snippets, and pre-aggregations. Auto-generated from DB but manually refined.
*   **Business Catalog (`catalog/catalog.yaml`)**: Defines the *allowlist* of metrics and dimensions exposed to the LLM.
*   **Governance**: This separation allows us to hide technical fields (IDs, audit columns) from the LLM, reducing context window usage and confusion.

## 7. Intent Extraction and Validation Logic

### 7.1 Extraction
*   **Prompt Engineering**: Uses a few-shot prompt with a strict JSON schema.
*   **Context**: The prompt receives a simplified list of available metrics and dimensions.
*   **Model**: Anthropic Claude (via `llm_service`).

### 7.2 Validation
The `IntentValidator` enforces:
1.  **Existence**: Metric/Dimension must exist in `catalog.yaml`.
2.  **Ambiguity**: If a term is ambiguous (e.g., "Sales" could be Volume or Value), it halts or uses default logic defined in the Normalizer.
3.  **Time Logic**: Checks validity of Time Windows (e.g., "last_30_days") and Granularity.
    *   *Note*: The logic enforces a `time_dimension` even for SNAPSHOT intents to ensuring correct filtering, differing slightly from the optional Pydantic field.

## 8. Query Generation and Execution via Cube

1.  **Input**: A normalized, validated `Intent` object.
2.  **Builder**: `CubeQueryBuilder` maps the Intent to a Cube JSON query.
    *   *Measures*: Mapped from `intent.metric`.
    *   *Dimensions*: Mapped from `intent.group_by`.
    *   *TimeDimensions*: Constructed from `intent.time_range` and `intent.time_dimension`.
    *   *Filters*: Converted to Cube member/operator/values.
3.  **Execution**: `CubeClient` sends the JSON to the Cube REST API.
4.  **Output**: Raw result set from Cube.

## 9. Insight and Response Generation

Currently, the system returns structured data suitable for frontend rendering (Charts/Tables).
*   **Visualization Logic**: Heuristics determine the best chart type (e.g., Time Series -> Line Chart, Categorical -> Bar Chart).
*   **Explainability**: The response includes the "Understood Intent" so the user can verify the system interpreted their question correctly.

## 10. Testing Strategy

### 10.1 Deterministic Tests
*   **Unit Tests**: Validate `IntentValidator` and `CubeQueryBuilder` logic. Ensure that specific inputs always produce specific outputs.
*   **Data Validation**: Tests to ensure `generate_catalog` correctly parses Cube YAMLs.

### 10.2 Non-Deterministic (AI) Testing
*   **E2E Tests**: Run a suite of "Golden Queries" against the LLM and verify the extracted intent matches expected structure.
*   **Metric**: Success rate of Intent Extraction (correct type, correct metric identified).

### 10.3 Manual/Integration
*   **Cube Integration**: Verify that generated Cube queries actually execute against the running Cube instance without error.

## 11. CI/CD Integration Strategy (Proposed)

This section outlines a recommended strategy for continuous integration and deployment.

### 11.1 Proposed Pipeline
1.  **Build Stage**:
    *   Trigger on commit/PR.
    *   Build Docker image for the backend service.
    *   Run static analysis (linting, type checking).
2.  **Test Stage**:
    *   Run unit tests via `pytest`.
    *   Run integration tests (mocked external dependencies).
3.  **Staging Deployment**:
    *   Deploy built container to Staging environment.
    *   Run E2E smoke tests (verifying Cube connectivity and sample queries).
4.  **Production Promotion**:
    *   Manual approval gate.
    *   Deploy to Production environment.

## 12. Observability, Logging, and Monitoring

### 12.1 Logging Strategy
*   **Application Logs**: Structured logs (JSON format recommended) tracking the pipeline execution flow.
*   **Extraction Logs**: Capture input query, prompt hash, and raw LLM response to audit extraction quality.

### 12.2 Monitoring Concepts
*   **Latency**: track the duration of each pipeline stage (LLM extraction time vs. Cube execution time).
*   **Error Rates**: Distinguish between user errors (validation failures) and system errors (timeouts, connectivity).
*   **Quality**: Periodic review of extraction logs to identify queries where the LLM failed or was ambiguous.

## 13. Known Limitations and Risks

### 13.1 Cube Schema Generation Issues
*   **Issue**: Cube.js auto-generation often misclassifies data types during introspection.
    *   **Integer Confusion**: `INT` columns (e.g., `invoice_id`) are frequently classified as **Measures** (aggregatable) when they should be Dimensions.
    *   **Decimal Confusion**: `DECIMAL` columns (e.g., `billed_volume`) are frequently classified as **Dimensions** (groupable) when they should be Measures.
*   **Impact**: These mismatches prevent correct aggregation and require manual intervention.
*   **Mitigation**: Post-generation review of `cubes/*.yml` files is mandatory to correct `measure` vs `dimension` types before regenerating the catalog.

### 13.2 Schema Sync Friction
*   **Risk**: If `catalog.yaml` is not updated after a Cube schema change, the LLM will hallucinate invalid metrics.
*   **Mitigation**: Strict adherence to the update workflow defined in Section 5.3.

## 14. Future Improvements and Roadmap

*   **Automated Catalog Sync**: Build a watcher to automatically trigger catalog generation when Cube files change.
*   **Advanced Ambiguity Handling**: Interactive "Clarification" mode where the system asks the user to resolve ambiguity (e.g., "Did you mean Primary or Secondary sales?").
*   **Natural Language Answers**: Add a final LLM step to summarize the Cube data into a text paragraph.
*   **Multi-Tenant Support**: Enable context-aware catalog filtering based on the logged-in user's role/tenant.

## 15. Appendix

### Glossary
*   **Intent**: A structured representation of what the user wants (Metric + Dimensions + Filters).
*   **Measure**: A numerical value to be aggregated (e.g., Sales Amount).
*   **Dimension**: A categorical value to group by (e.g., Region, Product).
*   **Cube**: The semantic layer platform used for query orchestration.
