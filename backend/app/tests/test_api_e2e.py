import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app.main import app
from app.services.intent_errors import IntentIncompleteError
from app.services.query_orchestrator import PipelineStage

client = TestClient(app)

# Mock data for Cube response
MOCK_CUBE_DATA = [{"count": 100, "fact_primary_sales.brand": "BrandA"}]
MOCK_CUBE_RESPONSE = MagicMock()
MOCK_CUBE_RESPONSE.data = MOCK_CUBE_DATA

@pytest.fixture
def mock_pipeline_components(mocker):
    # Mock extract_intent to return a valid snapshot intent
    mocker.patch("app.services.query_orchestrator.extract_intent", return_value={
        "intent_type": "snapshot",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY",
        "time_range": {"window": "last_30_days"},
        # Including time_dimension to pass validation as discovered earlier
        "time_dimension": {
            "dimension": "fact_primary_sales.invoice_date",
            "granularity": "month"
        }
    })

    # Mock CubeClient execution to avoid network calls
    # We patch `CubeClient` class to return a mock instance
    mock_client_cls = mocker.patch("app.services.query_orchestrator.CubeClient")
    mock_client_instance = mock_client_cls.return_value
    mock_client_instance.load.return_value = MOCK_CUBE_RESPONSE

    return mock_client_instance

def test_query_endpoint_success(mock_pipeline_components):
    response = client.post("/query", json={"query": "Total sales last 30 days"})

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["stage"] == PipelineStage.COMPLETED
    assert "request_id" in data
    assert "cube_query" in data
    assert data["data"] == MOCK_CUBE_DATA

def test_query_endpoint_clarification(mocker):
    # Mock extract_intent to return an incomplete intent (missing time_range)
    # But wait, extract_intent just returns dict.
    # validation raises IntentIncompleteError.

    mocker.patch("app.services.query_orchestrator.extract_intent", return_value={
        "intent_type": "snapshot",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY"
        # Missing time_range and time_dimension
    })

    # We don't need to mock CubeClient here because it stops at validation

    response = client.post("/query", json={"query": "Total sales"})

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is False
    assert data["stage"] == PipelineStage.CLARIFICATION_REQUESTED
    assert "missing_fields" in data
    assert "time_range" in data["missing_fields"]
    assert "request_id" in data

def test_clarify_flow(mocker):
    # First, trigger a clarification to get a request_id and save state
    # We need to ensure state saving works.
    # app.pipeline.state_store uses a simple dict or Redis?
    # I should check state_store.py

    # Mock extract_intent for the initial call
    mocker.patch("app.services.query_orchestrator.extract_intent", return_value={
        "intent_type": "snapshot",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY"
    })

    # Initial request
    resp1 = client.post("/query", json={"query": "Total sales"})
    req_id = resp1.json()["request_id"]

    # Now call /clarify
    # We need to mock CubeClient now as it will proceed to execution
    mock_client_cls = mocker.patch("app.services.query_orchestrator.CubeClient")
    mock_client_instance = mock_client_cls.return_value
    mock_client_instance.load.return_value = MOCK_CUBE_RESPONSE

    # Clarification request
    clarification_payload = {
        "request_id": req_id,
        "answers": {
            "time_range": {"window": "last_30_days"},
            "time_dimension": {
                "dimension": "fact_primary_sales.invoice_date",
                "granularity": "month"
            }
        }
    }

    resp2 = client.post("/clarify", json=clarification_payload)

    assert resp2.status_code == 200
    data = resp2.json()

    assert data["success"] is True
    assert data["stage"] == PipelineStage.COMPLETED
    assert data["data"] == MOCK_CUBE_DATA
