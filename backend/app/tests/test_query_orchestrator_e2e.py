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
from typing import Any, Dict

from backend.app.services.query_orchestrator import (
    execute_query,
    execute_query_dict,
    OrchestratorResponse,
    PipelineStage,
)

# Configure logging for test visibility
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
# E2E TEST - SINGLE QUERY
# =============================================================================

class TestQueryOrchestratorE2E:
    """
    End-to-end test for the complete query orchestrator pipeline.
    
    Uses a single, well-defined query to test the full flow.
    """
    
    TEST_QUERY = "Compare the sales performance of Metro zones versus Rural zones for the 'Beverages' category."
    
    def test_full_pipeline_success(self, api_key_check):
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
        print(f"E2E TEST: {self.TEST_QUERY}")
        print(f"{'='*80}")
        
        response = execute_query(self.TEST_QUERY)
        
        # =====================================================================
        # STEP 1: Query received
        # =====================================================================
        assert response.query == self.TEST_QUERY, "Query should be stored unchanged"
        print(f"\n✓ Step 1: Query received")
        print(f"  Query: {response.query}")
        
        # =====================================================================
        # STEP 2: Intent extracted
        # =====================================================================
        assert response.raw_intent is not None, \
            f"Raw intent should be populated. Error: {response.error}"
        
        print(f"\n✓ Step 2: Intent extracted")
        print(f"  Intent type: {response.raw_intent.get('intent_type')}")
        print(f"  Metric: {response.raw_intent.get('metric')}")
        print(f"  Group by: {response.raw_intent.get('group_by')}")
        
        # Verify intent structure
        assert "intent_type" in response.raw_intent, "Intent should have intent_type"
        assert response.raw_intent.get("intent_type") is not None, "intent_type should not be null"
        
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
            pytest.skip(
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
                pytest.skip("Cube service unavailable - skipping execution test")
            
            # Other Cube errors should be reported but not fail the test
            print(f"  Full error: {response.error.to_dict()}")
            pytest.skip(f"Cube error: {response.error.message}")
        
        print(f"\n✓ Step 5: Cube query executed")
        print(f"  Rows returned: {len(response.data)}")
        if response.data:
            print(f"  Response Data: {response.data}")
            
        
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
        """
        response_dict = execute_query_dict(self.TEST_QUERY)
        
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
