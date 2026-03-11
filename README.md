# NL2SQL System Documentation

[Improvements Since Version 1.1](#improvements-since-version-11)

## 1. System Overview

The NL2SQL (Natural Language to SQL) system is a specialized analytics interface designed for the Fast-Moving Consumer Goods (FMCG) sector. It enables non-technical business users to query complex sales data using natural language, abstracting the underlying SQL complexity.

The system operates on a "Guardrails First" philosophy, prioritizing accuracy and safety over generative freedom. It utilizes a deterministic pipeline architecture that combines Large Language Models (LLMs) for intent extraction with a strict semantic layer (Cube.js) for data retrieval. This approach mitigates hallucination risks common in generative AI database interfaces by enforcing a validated business catalog.

## 2. Architecture Overview

The system employs a microservices-based architecture orchestrated via Docker.

### Core Components

*   **Orchestrator Service (Backend)**: A Python FastAPI application serving as the central nervous system. It manages the query lifecycle, state, and integration with external services.
*   **Semantic Layer (Cube.js)**: Acts as the interface between the application and the raw database. It manages data modeling, caching, access control, and SQL generation.
*   **Data Store (PostgreSQL)**: The relational database hosting the raw FMCG sales data (facts and dimensions).
*   **State Store (Redis)**: High-performance key-value store used for managing conversational context (sessions) and temporary pipeline state during clarification loops.
*   **Inference Engine (Anthropic Claude)**: External LLM service utilized strictly for natural language understanding and intent extraction, not for SQL generation.

### Architecture Diagram

```
[Client] <-> [FastAPI Backend] <-> [Redis]
                    |
                    v
             [Anthropic API]
                    |
                    v
               [Cube.js API]
                    |
                    v
               [PostgreSQL]
```

## 3. Pipeline Flow

The query processing pipeline is linear but interruptible, managed by the `QueryOrchestrator`. It proceeds through the following distinct stages:

1.  **Context Retrieval**: The system accepts a query and a session ID. It attempts to load the previous Query Context Object (QCO) from Redis to support follow-up questions (e.g., "how about in the South region?").
2.  **Intent Extraction**: The raw query and optional previous context are submitted to the LLM. The model returns a structured JSON representation of the user's intent, adhering to a defined schema.
3.  **Intent Merging**: If previous context exists, the new intent is merged with the old QCO. Specific override rules determine how new filters replace or augment existing ones.
4.  **Normalization**: Semantic terms (e.g., "sales", "last month") are mapped to physical identifiers defined in the Cube.js schema (e.g., `fact_secondary_sales.net_value`, `time_range: last_30_days`).
5.  **Validation**: The normalized intent is validated against the `catalog.yaml`. The system checks for:
    *   Metric existence and accessibility.
    *   Dimension compatibility (group-by validity).
    *   Filter validity.
    *   **Ambiguity Detection**: If the intent is incomplete or ambiguous, the pipeline suspends and returns a `ClarificationRequest` to the client.
6.  **Query Compilation**: A validated intent is deterministically compiled into a Cube.js JSON query object. This step involves no AI; it is a mechanical translation ensuring syntactical correctness.
7.  **Execution**: The compiled query is transmitted to the Cube.js API. Cube.js generates the dialect-specific SQL, executes it against PostgreSQL, and returns the result set.
8.  **Insight Generation**: The raw result set is analyzed to generate statistical insights (e.g., trend detection, outlier identification) and a declarative visualization specification (e.g., bar chart configuration).
9.  **Context Resolution**: A new QCO is derived from the successful query and saved to Redis, updating the session state for future interactions.
10. **Response Construction**: A comprehensive JSON response containing the data, visualization config, natural language summary, and debug metadata is returned to the client.

## 4. Module Responsibilities

The backend codebase (`backend/app/`) is organized by functional responsibility:

*   **`services/query_orchestrator.py`**: The primary controller. It executes the pipeline steps sequentially, handles state transitions, and manages error propagation.
*   **`services/intent_extractor.py`**: Manages interactions with the LLM provider. It constructs prompts, handles retries, and parses the LLM's string output into JSON.
*   **`services/intent_validator.py`**: Enforces business logic. It ensures that the requested metrics and dimensions exist in the catalog and are compatible. It is responsible for triggering clarification flows.
*   **`services/cube_query_builder.py`**: A translation engine that converts the internal `Intent` model into the external Cube.js query format.
*   **`services/catalog_manager.py`**: Loads and serves the `catalog.yaml` definition file, providing a singleton interface for looking up metrics and dimensions.
*   **`pipeline/state_store.py`**: Wraps Redis operations for saving and retrieving pipeline state, particularly for interrupted queries requiring user clarification.

## 5. API Interfaces

The system exposes a RESTful API via FastAPI.

### Primary Endpoints

#### `POST /query`
Executes a natural language query.
*   **Input**: `{"query": "string", "session_id": "string (optional)"}`
*   **Output**: JSON object containing execution results, visualization data, or an error payload.

#### `POST /clarify`
Resumes a suspended pipeline with user-provided disambiguation.
*   **Input**: `{"request_id": "string", "answers": { ... }}`
*   **Output**: Same structure as `/query`.

### Metadata Endpoints

*   **`GET /catalog/metrics`**: Lists available business metrics.
*   **`GET /catalog/dimensions`**: Lists available analysis dimensions.
*   **`GET /catalog/time-windows`**: Lists supported time ranges.

## 6. Error Handling Strategy

The system implements a centralized error handling strategy utilizing the `OrchestratorResponse` object. Exceptions are caught at the pipeline level and converted into structured error data rather than causing HTTP 500 crashes.

### Error Classification

*   **Client Errors (400)**:
    *   `IntentValidationError`: The query requested metrics not in the catalog.
    *   `IntentIncompleteError`: The query was too vague (triggers clarification).
*   **Upstream Errors (502/504)**:
    *   `CubeHTTPError`: Connection failure to the Cube.js service.
    *   `CubeQueryExecutionError`: SQL execution failure within the data warehouse.
*   **System Errors (500)**:
    *   `LLMCallError`: Failure to communicate with the inference provider.
    *   `PipelineCompletionError`: Internal logic failure.

Errors include a machine-readable `error_type` and a human-readable `message` to facilitate frontend error display.

## 7. Deployment Flow

Deployment is containerized using Docker Compose, ensuring environment consistency.

### Requirements
*   Docker Engine & Docker Compose
*   Python 3.12+ (for local development)
*   Anthropic API Credentials

### Configuration
Environment variables function as the primary configuration mechanism, defined in `.env`:
*   `ANTHROPIC_API_KEY`: Authentication for the LLM.
*   `CUBE_API_URL`: Endpoint for the Cube.js service.
*   `REDIS_URL`: Connection string for the state store.

### Infrastructure Setup
The `docker-compose.yml` defines the service mesh:
1.  **PostgreSQL**: Initializes with seed data from `cube/data/`.
2.  **Redis**: Starts with default persistence settings.
3.  **Cube.js**: Connects to PostgreSQL and exposes the semantic API (port 4000).
4.  **Backend**: Builds from `backend/Dockerfile` and exposes port 8000.

### Installation

```bash
# Clone the repository
git clone <repository_url>

# Configure environment
cp .env.example .env
# Edit .env with appropriate credentials

# Start services
docker-compose up -d

# Initialize Database (if not using automatic seeding)
cat cube/data/02_populate_data.sql | docker exec -i nl2sql-postgres psql -U postgres -d sales_analytics
```

## Improvements Since Version 1.1

### 1. Query Orchestration and Pipeline Refactoring
Significant improvements were made to the internal orchestration pipeline to improve stability and maintainability.

Key updates include:
* Refactoring of the Query Coordination Orchestrator (QCO) flow
* Improved intent modelling and intent validation layers
* Updated intent JSON format
* Improved query orchestration handling
* Added retry logic for LLM calls
* Updated Cube query builder
* Improved period strategy layer for time-based queries

These changes streamlined the pipeline and reduced errors in query interpretation and execution.

### 2. Insight Generation Enhancements
The insight generation module was expanded to produce more structured and user-friendly analytics insights.

Enhancements include:
* Implementation of three-layer insight generation
* Addition of risks, drivers, and recommendations insights
* Layman-friendly insight language formatting
* Support for lakhs and crores numeric formatting
* Latency reduction in insight generation pipeline

These improvements make insights more interpretable and relevant for business users.

### 3. Drill-Down and Analytical Capability Improvements
New analytical capabilities were introduced to support deeper data exploration.

Key additions:
* Hierarchy-based drill-down functionality
* Drill detector module for identifying drillable dimensions
* Pivot configuration support
* Pivot table constraints and value mapping

These updates allow users to perform deeper analytical exploration of datasets.

### 4. Visualization and UI Improvements
The frontend visualization layer received multiple improvements to enhance usability and presentation.

Enhancements include:
* Improved pivot table rendering
* Added stacked bar chart support
* Chart-table toggle functionality
* Chart window design improvements
* Improved search bar layout
* Better chart axis and label formatting
* UI layout refinements (bubble width, padding, column tables)

These changes improve the readability and usability of analytics results.

### 5. Logging and Observability Improvements
System observability was strengthened to improve debugging and monitoring.

Updates include:
* Component-level logging
* Cube client error logging
* Integration with LLM tracing tools
* Improved exception handling (token counting and execution errors)

This helps diagnose issues in the NL-to-SQL pipeline more effectively.

### 6. Data Handling and Test Data Quality
Multiple fixes and improvements were implemented for dataset consistency and test data generation.

Changes include:
* Fix for data insertion bugs
* Synthetic data variance generation
* Price reduction and formatting updates
* Improvements in test datasets used for validation

These updates help improve testing reliability and system evaluation.

### 7. Bug Fixes and Stability Improvements
Several bugs affecting query interpretation and visualization were fixed.

Notable fixes:
* Time dimension handling issues
* Chart selection bugs
* Intent upstream issues
* Clarification query handling issues
* Granularity and trend patching issues
* Various QCO pipeline bugs

These fixes improved overall system stability.

### 8. Performance Improvements
Performance optimizations were introduced across the pipeline.

Key improvements:
* Insight latency reduction
* CubeJS caching fixes
* Pipeline execution optimizations

These changes improved response times for analytical queries.
