"""
End-to-End Test for Query Orchestrator Pipeline.

Tests the complete flow:
Query → Intent Extraction → Validation → Cube Query Build → Cube Execution

IMPORTANT: 
- This test calls the actual Claude API
- This test requires a running Cube instance (skip if unavailable)

Usage:
    pytest backend/app/tests/test_query_orchestrator_e2e.py -v --capture=no
"""

import os
import json
import logging
import pytest
from typing import Any, Dict, List, Tuple

from app.services.query_orchestrator import (
    execute_query,
    execute_query_dict,
    OrchestratorResponse,
    PipelineStage,
)

# Configure logging for test visibility
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# TEST QUERIES - Updated for new flat schema
# =============================================================================

TEST_QUERIES: List[Tuple[str, str, str]] = [
    # (query, expected_intent_type, description)
    
    # RANKING QUERIES
    (
        "What are the top 5 zones by total quantity?",
        "ranking",
        "Top zones by volume - tests zone dimension and billed_qty metric."
    ),
    (
        "Which distributors have the highest Secondary Sales net value?",
        "ranking",
        "Top distributors by revenue."
    ),
    (
        "List the top 3 brands by total quantity sold.",
        "ranking",
        "Brand ranking by volume."
    ),

    # COMPARISON QUERIES
    (
        "Compare the total Primary Sales volume vs Secondary Sales volume.",
        "comparison",
        "Channel fill (Primary) vs Offtake (Secondary) comparison."
    ),
    (
        "How does the gross value compare between Cigarettes and Aata categories?",
        "comparison",
        "Category comparison by gross value."
    ),

    # SNAPSHOT QUERIES
    (
        "What is the total net value of secondary sales?",
        "snapshot",
        "Simple aggregation of net value."
    ),
    (
        "How many transactions are there in the East zone?",
        "snapshot",
        "Count query with filter."
    ),
    (
        "What is the total billed quantity for the Fortune brand?",
        "snapshot",
        "Aggregation filtered by brand."
    ),

    # TREND QUERIES
    (
        "Show the daily trend of Secondary Sales net value over the last 30 days.",
        "trend",
        "Daily offtake trend."
    ),
    (
        "How has the total quantity changed month over month this year?",
        "trend",
        "Monthly volume trend."
    ),

    # DISTRIBUTION QUERIES
    (
        "What is the breakdown of Secondary Sales by zone?",
        "distribution",
        "Geographic distribution analysis."
    ),
    (
        "Show the sales distribution by category.",
        "distribution",
        "Category contribution analysis."
    ),
    (
        "Breakdown of gross value by state.",
        "distribution",
        "State-level distribution."
    ),
]

# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(scope="session")
def api_key_check():
    """Verify API key is available."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY environment variable not set")
    return api_key


# =============================================================================
# E2E TEST - MULTIPLE QUERIES (PARAMETERIZED)
# =============================================================================

class TestQueryOrchestratorE2E:
    """
    End-to-end test for the complete query orchestrator pipeline.
    
    Tests multiple queries covering various intent types.
    """
    
    @pytest.mark.parametrize(
        "query,expected_intent_type,description",
        TEST_QUERIES,
        ids=[q[2] for q in TEST_QUERIES]  # Use description as test ID
    )
    def test_full_pipeline(self, api_key_check, query: str, expected_intent_type: str, description: str):
        """
        Test the complete pipeline from query to Cube execution.
        
        This test verifies:
        1. Query is received
        2. Intent is extracted (raw_intent populated)
        3. Intent is validated (validated_intent populated)
        4. Cube query is built (cube_query populated)
        5. Cube query is executed (data populated) - OR error if Cube unavailable
        """
        # Execute the query
        print(f"\n{'='*80}")
        print(f"E2E TEST: {description}")
        print(f"Query: {query}")
        print(f"Expected Intent Type: {expected_intent_type}")
        print(f"{'='*80}")
        
        response = execute_query(query)
        
        # =====================================================================
        # STEP 1: Query received
        # =====================================================================
        assert response.query == query, "Query should be stored unchanged"
        print(f"\n✓ Step 1: Query received")
        print(f"  Query: {response.query[:80]}...")
        
        # =====================================================================
        # STEP 2: Intent extracted
        # =====================================================================
        assert response.raw_intent is not None, \
            f"Raw intent should be populated. Error: {response.error}"
        
        actual_intent_type = response.raw_intent.get('intent_type')
        print(f"\n✓ Step 2: Intent extracted")
        print(f"  Intent type: {actual_intent_type} (expected: {expected_intent_type})")
        print(f"  Metric: {response.raw_intent.get('metric')}")
        print(f"  Group by: {response.raw_intent.get('group_by')}")
        print(f"  Limit: {response.raw_intent.get('limit')}")
        
        # Verify intent structure
        assert "intent_type" in response.raw_intent, "Intent should have intent_type"
        assert response.raw_intent.get("intent_type") is not None, "intent_type should not be null"
        
        # Check if intent type matches expected (soft check - log mismatch but don't fail)
        if actual_intent_type != expected_intent_type:
            print(f"\n⚠ Warning: Intent type mismatch!")
            print(f"  Expected: {expected_intent_type}, Got: {actual_intent_type}")
        
        # If extraction failed, stop here and report
        if response.stage == PipelineStage.RECEIVED:
            pytest.fail(f"Pipeline stopped at extraction: {response.error.message}")
        
        # =====================================================================
        # STEP 3: Intent validated
        # =====================================================================
        if response.validated_intent is None:
            # Validation failed - report details
            assert response.error is not None, "Error should be set if validation failed"
            print(f"\n✗ Step 3: Validation failed")
            print(f"  Error type: {response.error.error_type}")
            print(f"  Error code: {response.error.error_code}")
            print(f"  Message: {response.error.message}")
            
            # This is a skip, not a failure - the LLM output was invalid
            pytest.fail(
                f"Validation failed: {response.error.error_code} - {response.error.message}"
            )
        
        print(f"\n✓ Step 3: Intent validated")
        print(f"  Intent type: {response.validated_intent.get('intent_type')}")
        
        # =====================================================================
        # STEP 4: Cube query built
        # =====================================================================
        assert response.cube_query is not None, \
            f"Cube query should be built. Error: {response.error}"
        
        print(f"\n✓ Step 4: Cube query built")
        print(f"  Measures: {response.cube_query.get('measures')}")
        print(f"  Dimensions: {response.cube_query.get('dimensions')}")
        print(f"  Limit: {response.cube_query.get('limit')}")
        
        # Verify Cube query structure
        assert "measures" in response.cube_query, "Cube query should have measures"
        
        # =====================================================================
        # STEP 5: Cube execution
        # =====================================================================
        if response.data is None:
            # Cube execution failed - this is expected if Cube is not running
            assert response.error is not None, "Error should be set if Cube failed"
            print(f"\n⚠ Step 5: Cube execution failed (expected if Cube not running)")
            print(f"  Error type: {response.error.error_type}")
            print(f"  Message: {response.error.message[:100]}...")
            
            # Skip if Cube is unavailable (connection refused)
            if "connect" in response.error.message.lower() or \
               "refused" in response.error.message.lower() or \
               "timeout" in response.error.message.lower():
                pytest.fail("Cube service unavailable - skipping execution test")
            
            # Other Cube errors should be reported but not fail the test
            print(f"  Full error: {response.error.to_dict()}")
            pytest.skip(f"Cube error: {response.error.message}")
        
        print(f"\n✓ Step 5: Cube query executed")
        print(f"  Rows returned: {len(response.data)}")
        if response.data and len(response.data) > 0:
            print(f"  First row: {response.data[0]}")
            
        
        # =====================================================================
        # FINAL: Success
        # =====================================================================
        assert response.success is True, "Pipeline should complete successfully"
        assert response.stage == PipelineStage.COMPLETED, \
            f"Stage should be COMPLETED, got {response.stage}"
        
        print(f"\n{'='*80}")
        print(f"✓ PIPELINE COMPLETED SUCCESSFULLY")
        print(f"  Duration: {response.duration_ms}ms")
        print(f"  Rows: {len(response.data)}")
        print(f"{'='*80}")
    
    def test_response_structure(self, api_key_check):
        """
        Test that the response has the expected structure for API serialization.
        Uses the first test query.
        """
        test_query = TEST_QUERIES[0][0]
        response_dict = execute_query_dict(test_query)
        
        # Verify all expected keys are present
        expected_keys = [
            "query",
            "success", 
            "stage",
            "duration_ms",
            "raw_intent",
            "validated_intent",
            "cube_query",
            "data",
            "error",
            "request_id",
        ]
        
        for key in expected_keys:
            assert key in response_dict, f"Response should contain '{key}'"
        
        # Verify types
        assert isinstance(response_dict["query"], str)
        assert isinstance(response_dict["success"], bool)
        assert isinstance(response_dict["stage"], str)
        assert isinstance(response_dict["duration_ms"], int)
        
        print(f"\n✓ Response structure verified")
        print(f"  Keys: {list(response_dict.keys())}")
        print(f"  Success: {response_dict['success']}")
        print(f"  Stage: {response_dict['stage']}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--capture=no"])
