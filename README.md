# NL2SQL - Natural Language to SQL Analytics

> **Transform natural language questions into real-time analytics queries**

NL2SQL is an intelligent query interface that converts natural language questions into Cube.js queries for FMCG sales analytics. Ask questions like *"Show me total sales by region for last 30 days"* and get instant insights.

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![Cube.js](https://img.shields.io/badge/Cube.js-Latest-purple.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## 🎯 Features

- **Natural Language Understanding** - Ask questions in plain English
- **Intent Extraction** - LLM-powered query parsing with Claude
- **Semantic Validation** - Catalog-based validation ensures accuracy
- **Cube.js Integration** - Seamless connection to your data warehouse
- **Structured Error Handling** - Clear, actionable error messages
- **Full Transparency** - See every step of the pipeline (debugging-friendly)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           NL2SQL Pipeline                                │
│                                                                          │
│   "Show me sales by region"                                              │
│            │                                                             │
│            ▼                                                             │
│   ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐   │
│   │ Intent Extractor│ ──► │ Intent Validator│ ──► │Cube Query Builder│  │
│   │     (LLM)       │     │   (Catalog)     │     │   (Mapping)     │   │
│   └─────────────────┘     └─────────────────┘     └─────────────────┘   │
│                                                            │             │
│                                                            ▼             │
│                                                   ┌─────────────────┐   │
│                                                   │   Cube Client   │   │
│                                                   │    (HTTP)       │   │
│                                                   └─────────────────┘   │
│                                                            │             │
│                                                            ▼             │
│                                                   ┌─────────────────┐   │
│                                                   │   PostgreSQL    │   │
│                                                   │   (Data Store)  │   │
│                                                   └─────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- Anthropic API Key (Claude)

### 1. Clone & Setup

```bash
git clone https://github.com/yourusername/nl2sql.git
cd nl2sql

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
# Anthropic (LLM)
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_MODEL_ID=claude-sonnet-4-5

# Cube.js
CUBE_API_URL=http://localhost:4000/cubejs-api/v1
CUBE_API_SECRET=mysecretkey123

# API Settings
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
```

### 3. Start Infrastructure

```bash
# Start PostgreSQL and Cube.js
docker-compose up -d

# Wait for services to be ready (~30 seconds)
```

### 4. Run the API

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Test It!

```bash
# Health check
curl http://localhost:8000/health

# Query endpoint
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the top 5 territories by total quantity?"}'
```

Or open **http://localhost:8000/docs** for the interactive Swagger UI.

---

## 📖 API Reference

### POST /query

Execute a natural language analytics query.

**Request:**
```json
{
  "query": "Show me total sales by region for last 30 days"
}
```

**Success Response (200):**
```json
{
  "query": "Show me total sales by region for last 30 days",
  "success": true,
  "stage": "completed",
  "duration_ms": 1234,
  "raw_intent": {
    "intent_type": "distribution",
    "metric": "transaction_count",
    "group_by": ["region"],
    "time_range": {"window": "last_30_days"}
  },
  "validated_intent": {...},
  "cube_query": {
    "measures": ["sales_fact.count"],
    "dimensions": ["territories.region"],
    "timeDimensions": [{"dimension": "sales_fact.invoice_date", "dateRange": "last 30 days"}]
  },
  "data": [
    {"territories.region": "North", "sales_fact.count": 150},
    {"territories.region": "South", "sales_fact.count": 230}
  ],
  "request_id": "abc123"
}
```

**Error Response (400):**
```json
{
  "success": false,
  "stage": "intent_extracted",
  "error": {
    "stage": "intent_extracted",
    "error_type": "UnknownMetricError",
    "error_code": "UNKNOWN_METRIC",
    "message": "Unknown metric: 'revenue'. Did you mean: transaction_count, total_quantity?",
    "details": {...}
  }
}
```

### GET /catalog/metrics

List all available metrics.

### GET /catalog/dimensions

List all available dimensions for grouping.

### GET /catalog/time-windows

List all available time windows (last_7_days, last_30_days, etc.).

---

## 📁 Project Structure

```
nl2sql/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── models/
│   │   │   └── intent.py        # Pydantic intent models
│   │   ├── services/
│   │   │   ├── query_orchestrator.py  # Pipeline coordinator
│   │   │   ├── intent_extractor.py    # LLM-based extraction
│   │   │   ├── intent_validator.py    # Catalog validation
│   │   │   ├── cube_query_builder.py  # Intent → Cube query
│   │   │   ├── cube_client.py         # Cube HTTP client
│   │   │   ├── catalog_manager.py     # Catalog loader
│   │   │   └── intent_errors.py       # Error taxonomy
│   │   └── prompts/
│   │       └── intent_extraction.txt  # LLM prompt template
│   └── catalog/
│       └── catalog.yaml         # Semantic catalog
├── cube/
│   ├── model/
│   │   └── cubes/               # Cube.js schema files
│   └── data/
│       └── fmcg_sales.sql       # Sample data
├── docker-compose.yml           # Infrastructure setup
├── requirements.txt
└── README.md
```

---

## 🔧 Supported Queries

### Metrics
| Metric | Description | Example |
|--------|-------------|---------|
| `transaction_count` | Number of transactions | "How many transactions?" |
| `total_quantity` | Sum of quantities sold | "Total quantity sold" |
| `distributor_count` | Number of distributors | "How many distributors?" |
| `outlet_count` | Number of retail outlets | "Count of outlets" |

### Dimensions (Group By)
| Dimension | Description |
|-----------|-------------|
| `region` | Geographic region (North, South, East, West) |
| `state` | State name |
| `brand` | Product brand |
| `product_category` | Category (Beverages, Snacks, Dairy) |
| `outlet_type` | Outlet type (Kirana, Modern Trade) |
| `sales_type` | Sales channel (Primary, Secondary, Tertiary) |

### Time Windows
| Window | Description |
|--------|-------------|
| `today` | Current day |
| `last_7_days` | Past 7 days |
| `last_30_days` | Past 30 days |
| `month_to_date` | Current month so far |
| `year_to_date` | Current year so far |

---

## 🧪 Testing

```bash
cd backend
python -m pytest app/tests/ -v
```

---

## 🛠️ Development & Maintenance

### Generating the Catalog

If you modify the Cube.js schema files in `cube/model/cubes/`, you need to regenerate the `catalog.yaml` file so the NL2SQL validators are aware of the changes.

```bash
cd backend
python -m app.utils.generate_catalog
```

This script parses the Cube YAML files and updates `backend/catalog/catalog.yaml` with the latest metrics, dimensions, and time dimensions.

---

## 🔒 Design Principles

1. **Separation of Concerns** - Each module has a single responsibility
2. **Catalog as Source of Truth** - All valid terms defined in `catalog.yaml`
3. **No Hallucination** - LLM output is validated against catalog
4. **Fail Fast** - Pipeline stops immediately on any error
5. **Full Transparency** - Every step is visible in the response
6. **Deterministic** - Low temperature LLM calls for consistent parsing

---
