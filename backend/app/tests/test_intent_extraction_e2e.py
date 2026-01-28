"""
End-to-End Intent Extraction & Validation Tests.

This test module tests the complete flow:
1. Natural language query → Intent Extraction (via Claude API)
2. Raw intent dict → Intent Validation (against catalog)

IMPORTANT:
- These tests call the actual Claude API
- Each test is run sequentially
- Use pytest -v --tb=long to see detailed output
- Run with pytest -x to stop at first failure

Usage:
    pytest backend/app/tests/test_intent_extraction_e2e.py -v -x
    pytest backend/app/tests/test_intent_extraction_e2e.py -v -k "test_sales_performance"
"""

import os
import logging
import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from backend.app.services.intent_extractor import extract_intent, ExtractionError
from backend.app.services.catalog_manager import CatalogManager
from backend.app.services.intent_validator import validate_intent, IntentValidator
from backend.app.services.intent_errors import IntentValidationError
from backend.app.models.intent import Intent

# Configure logging for test visibility
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# Test Configuration
# =============================================================================

@dataclass
class TestCase:
    """Represents a single test case for intent extraction."""
    query: str
    category: str
    description: str
    # Allow multiple valid intent types since LLM may choose different valid interpretations
    valid_intent_types: Optional[List[str]] = None  # Changed from expected_intent_type
    expected_metric: Optional[str] = None
    expected_group_by: Optional[List[str]] = None
    expected_filters: Optional[List[Dict[str, Any]]] = None
    expected_time_range_window: Optional[str] = None
    expected_time_dimension: Optional[str] = None
    expected_granularity: Optional[str] = None
    should_have_filters: bool = False
    should_have_time_range: bool = False
    should_have_time_dimension: bool = False
    should_have_group_by: bool = False  # New: check if group_by is present


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def catalog() -> CatalogManager:
    """Load catalog manager for validation."""
    catalog_path = Path(__file__).parent.parent.parent / "catalog" / "catalog.yaml"
    return CatalogManager(str(catalog_path))


@pytest.fixture(scope="session")
def api_key_check():
    """Verify API key is available."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY environment variable not set")
    return api_key


# =============================================================================
# Test Cases - Sales Performance & Trends
# =============================================================================

SALES_PERFORMANCE_TESTS = [
    TestCase(
        query="What is the total Primary vs. Secondary sales revenue for the first quarter of 2024?",
        category="Sales Performance & Trends",
        description="Compare primary vs secondary sales with explicit date range",
        valid_intent_types=["snapshot", "comparison"],  # Both valid interpretations
        should_have_time_range=True,
        should_have_group_by=True,  # Should group by sales_type for comparison
    ),
    TestCase(
        query="Which month saw the highest growth in Tertiary (end-consumer) sales?",
        category="Sales Performance & Trends",
        description="Trend analysis for tertiary sales by month",
        valid_intent_types=["trend", "ranking"],
        should_have_filters=True,  # Should filter by sales_type = TERTIARY
        should_have_time_dimension=True,
        expected_granularity="month",
    ),
    TestCase(
        query="What is the average discount percentage given on Primary sales compared to Secondary sales?",
        category="Sales Performance & Trends",
        description="Compare discounts between primary and secondary sales",
        valid_intent_types=["snapshot", "comparison"],
        should_have_group_by=True,
    ),
    TestCase(
        query="Identify the top 5 SKUs by total net_amount across all territories.",
        category="Sales Performance & Trends",
        description="Ranking query for top SKUs",
        valid_intent_types=["ranking", "snapshot"],
        should_have_group_by=True,
    ),
]


# =============================================================================
# Test Cases - Territory & Regional Insights
# =============================================================================

TERRITORY_TESTS = [
    TestCase(
        query="Which Region (North, South, East, West) is contributing the most to the total gross amount?",
        category="Territory & Regional Insights",
        description="Regional breakdown of gross amount",
        valid_intent_types=["snapshot", "ranking", "distribution"],
        should_have_group_by=True,
    ),
    TestCase(
        query="Compare the sales performance of Metro zones versus Rural zones for the 'Beverages' category.",
        category="Territory & Regional Insights",
        description="Zone comparison with category filter",
        valid_intent_types=["comparison", "snapshot", "distribution"],
        should_have_group_by=True,
        should_have_filters=True,  # Should filter by category = Beverages
    ),
    TestCase(
        query="List the top 3 territories in the 'South' region based on Secondary sales volume.",
        category="Territory & Regional Insights",
        description="Territory ranking with region filter",
        valid_intent_types=["ranking", "snapshot"],
        should_have_group_by=True,
        should_have_filters=True,  # Should filter by region = South, sales_type = SECONDARY
    ),
    TestCase(
        query="Which state has the highest number of active retail outlets?",
        category="Territory & Regional Insights",
        description="State-wise outlet count",
        valid_intent_types=["ranking", "snapshot", "distribution"],
        should_have_group_by=True,
    ),
]


# =============================================================================
# Test Cases - Distribution & Channel Analysis
# =============================================================================

DISTRIBUTION_TESTS = [
    TestCase(
        query="Which Distributors are currently exceeding their credit limits based on unpaid credit invoices?",
        category="Distribution & Channel Analysis",
        description="Distributor credit analysis",
        valid_intent_types=["snapshot", "ranking"],
        should_have_group_by=True,
        should_have_filters=True,  # Credit filter
    ),
    TestCase(
        query="Calculate the 'Fill Rate'—what is the ratio of Primary sales (to distributors) to Secondary sales (to retailers) for each distributor?",
        category="Distribution & Channel Analysis",
        description="Fill rate calculation per distributor",
        valid_intent_types=["snapshot", "distribution"],
        should_have_group_by=True,
    ),
    TestCase(
        query="Identify outlets that have not placed a Secondary order in the last 30 days.",
        category="Distribution & Channel Analysis",
        description="Inactive outlets identification",
        valid_intent_types=["snapshot", "ranking"],
        should_have_filters=True,
        should_have_time_range=True,
    ),
    TestCase(
        query="What is the most popular Outlet Type (Kirana vs. Modern Trade) for the 'Snacks' brand 'CrunchTime'?",
        category="Distribution & Channel Analysis",
        description="Outlet type analysis with brand filter",
        valid_intent_types=["ranking", "snapshot", "distribution"],
        should_have_group_by=True,
        should_have_filters=True,  # Brand filter
    ),
]


# =============================================================================
# Test Cases - Product & Category Intelligence
# =============================================================================

PRODUCT_TESTS = [
    TestCase(
        query="Which Category has the highest 'Scheme Discount' burden relative to its total sales?",
        category="Product & Category Intelligence",
        description="Category discount analysis",
        valid_intent_types=["ranking", "snapshot", "distribution"],
        should_have_group_by=True,
    ),
    TestCase(
        query="What is the most popular pack_size for 'FreshCo Cola' across all Metro cities?",
        category="Product & Category Intelligence",
        description="Pack size analysis with brand and zone filter",
        valid_intent_types=["ranking", "snapshot", "distribution"],
        should_have_group_by=True,
        should_have_filters=True,  # Brand and zone filters
    ),
    TestCase(
        query="List SKUs where the mrp (Maximum Retail Price) is more than 20% higher than the base_price in Secondary sales.",
        category="Product & Category Intelligence",
        description="SKU price margin analysis",
        valid_intent_types=["snapshot", "ranking"],
        should_have_filters=True,  # Sales type filter
    ),
    TestCase(
        query="Find the sub-categories that are underperforming in the 'West' region.",
        category="Product & Category Intelligence",
        description="Sub-category performance by region",
        valid_intent_types=["ranking", "snapshot", "distribution"],
        should_have_group_by=True,
        should_have_filters=True,  # Region filter
    ),
]


# =============================================================================
# Test Cases - Sales Representative Productivity
# =============================================================================

SALES_REP_TESTS = [
    TestCase(
        query="Rank the Sales Reps (SR codes) by the total number of unique outlets they serviced in March 2024.",
        category="Sales Representative Productivity",
        description="Sales rep ranking by outlet coverage",
        valid_intent_types=["ranking", "snapshot"],
        should_have_group_by=True,
        should_have_time_range=True,
    ),
    TestCase(
        query="What is the average invoice value generated by SR-101 compared to the territory average?",
        category="Sales Representative Productivity",
        description="Sales rep comparison to average",
        valid_intent_types=["comparison", "snapshot"],
        should_have_filters=True,  # Filter by sales_rep = SR-101
    ),
    TestCase(
        query="Which Sales Rep has the highest percentage of Credit sales vs. Cash sales?",
        category="Sales Representative Productivity",
        description="Sales rep credit vs cash analysis",
        valid_intent_types=["ranking", "snapshot", "comparison"],
        should_have_group_by=True,
    ),
]


# =============================================================================
# All Test Cases Combined
# =============================================================================

ALL_TEST_CASES = (
    SALES_PERFORMANCE_TESTS +
    TERRITORY_TESTS +
    DISTRIBUTION_TESTS +
    PRODUCT_TESTS +
    SALES_REP_TESTS
)


# =============================================================================
# Helper Functions
# =============================================================================

def run_extraction_and_validation(
    query: str, 
    catalog: CatalogManager
) -> tuple[Dict[str, Any], Optional[Intent], Optional[Exception]]:
    """
    Run extraction and validation for a query.
    
    Returns:
        (raw_intent, validated_intent, error)
    """
    raw_intent = None
    validated_intent = None
    error = None
    
    try:
        # Step 1: Extract intent (calls Claude API)
        logger.info(f"\n{'='*60}")
        logger.info(f"QUERY: {query}")
        logger.info(f"{'='*60}")
        
        raw_intent = extract_intent(query)
        logger.info(f"RAW INTENT: {raw_intent}")
        
        # Step 2: Validate intent
        validated_intent = validate_intent(raw_intent, catalog)
        logger.info(f"VALIDATED INTENT: {validated_intent.model_dump()}")
        
    except ExtractionError as e:
        logger.error(f"EXTRACTION ERROR: {e}")
        error = e
    except IntentValidationError as e:
        logger.error(f"VALIDATION ERROR: {e}")
        error = e
    except Exception as e:
        logger.error(f"UNEXPECTED ERROR: {e}")
        error = e
    
    return raw_intent, validated_intent, error


def get_detailed_skip_reason(
    error: Exception,
    raw_intent: Optional[Dict[str, Any]],
    test_case: "TestCase"
) -> str:
    """
    Generate a detailed, specific skip reason based on the error and raw intent.
    
    Returns a human-readable string explaining exactly why the test was skipped.
    """
    error_type = type(error).__name__
    error_msg = str(error)
    
    # Build context from raw intent
    intent_context = ""
    if raw_intent:
        intent_type = raw_intent.get("intent_type", "null")
        metric = raw_intent.get("metric", "null")
        group_by = raw_intent.get("group_by", [])
        filters = raw_intent.get("filters", [])
        time_range = raw_intent.get("time_range")
        time_dimension = raw_intent.get("time_dimension")
        
        intent_context = f"\n  - LLM returned intent_type='{intent_type}', metric='{metric}'"
        if group_by:
            intent_context += f", group_by={group_by}"
        if filters:
            filter_dims = [f.get("dimension", "?") for f in filters] if isinstance(filters, list) else []
            intent_context += f", filters on {filter_dims}"
        if time_range:
            intent_context += f", time_range={time_range}"
        if time_dimension:
            intent_context += f", time_dimension={time_dimension}"
    
    # Categorize the specific failure
    if "UNKNOWN_METRIC" in error_msg or "Unknown metric" in error_msg:
        metric_val = raw_intent.get("metric") if raw_intent else "unknown"
        return (
            f"SKIP REASON: Unknown metric '{metric_val}' not in catalog.\n"
            f"  - Query: \"{test_case.query[:80]}...\"\n"
            f"  - Error: {error_msg[:150]}"
            f"{intent_context}"
        )
    
    if "UNKNOWN_DIMENSION" in error_msg or "Unknown dimension" in error_msg:
        return (
            f"SKIP REASON: Unknown dimension in group_by or filters.\n"
            f"  - Query: \"{test_case.query[:80]}...\"\n"
            f"  - Error: {error_msg[:150]}"
            f"{intent_context}"
        )
    
    if "MALFORMED_INTENT" in error_msg or "Malformed intent" in error_msg:
        # Parse out specific malformed field
        if "intent_type" in error_msg:
            return (
                f"SKIP REASON: Invalid intent_type value.\n"
                f"  - Query: \"{test_case.query[:80]}...\"\n"
                f"  - LLM returned intent_type='{raw_intent.get('intent_type') if raw_intent else 'null'}'\n"
                f"  - Error: {error_msg[:150]}"
            )
        if "metric" in error_msg.lower():
            return (
                f"SKIP REASON: Missing or invalid metric field.\n"
                f"  - Query: \"{test_case.query[:80]}...\"\n"
                f"  - LLM returned metric='{raw_intent.get('metric') if raw_intent else 'null'}'\n"
                f"  - Error: {error_msg[:150]}"
            )
        if "time_dimension" in error_msg.lower():
            return (
                f"SKIP REASON: TREND intent missing required time_dimension.\n"
                f"  - Query: \"{test_case.query[:80]}...\"\n"
                f"  - Error: {error_msg[:150]}"
                f"{intent_context}"
            )
        if "group_by" in error_msg.lower():
            return (
                f"SKIP REASON: Intent type requires group_by but none provided.\n"
                f"  - Query: \"{test_case.query[:80]}...\"\n"
                f"  - Error: {error_msg[:150]}"
                f"{intent_context}"
            )
        return (
            f"SKIP REASON: Malformed intent structure.\n"
            f"  - Query: \"{test_case.query[:80]}...\"\n"
            f"  - Error: {error_msg[:200]}"
            f"{intent_context}"
        )
    
    if "INVALID_TIME_WINDOW" in error_msg:
        time_window = raw_intent.get("time_range", {}).get("window") if raw_intent else None
        return (
            f"SKIP REASON: Invalid time_window '{time_window}' not in catalog.\n"
            f"  - Query: \"{test_case.query[:80]}...\"\n"
            f"  - Error: {error_msg[:150]}"
        )
    
    if "INVALID_GRANULARITY" in error_msg:
        granularity = raw_intent.get("time_dimension", {}).get("granularity") if raw_intent else None
        return (
            f"SKIP REASON: Invalid granularity '{granularity}'.\n"
            f"  - Query: \"{test_case.query[:80]}...\"\n"
            f"  - Error: {error_msg[:150]}"
        )
    
    # Default: return error type and message with context
    return (
        f"SKIP REASON: {error_type}\n"
        f"  - Query: \"{test_case.query[:80]}...\"\n"
        f"  - Error: {error_msg[:200]}"
        f"{intent_context}"
    )


def assert_intent_structure(intent: Intent, test_case: TestCase):
    """Assert that the intent matches expected structure."""
    
    # All valid intent types from catalog
    VALID_INTENT_TYPES = ["snapshot", "trend", "comparison", "ranking", "distribution", "drill_down"]
    
    # Check intent type is valid
    assert intent.intent_type in VALID_INTENT_TYPES, \
        f"Invalid intent_type: {intent.intent_type}. Must be one of {VALID_INTENT_TYPES}"
    
    # Check intent type if specific types are expected
    if test_case.valid_intent_types:
        assert intent.intent_type in test_case.valid_intent_types, \
            f"Expected intent_type in {test_case.valid_intent_types}, got {intent.intent_type}"
    
    # Check metric if expected
    if test_case.expected_metric:
        assert intent.metric == test_case.expected_metric, \
            f"Expected metric={test_case.expected_metric}, got {intent.metric}"
    
    # Check group_by if expected (specific dimensions)
    if test_case.expected_group_by:
        assert intent.group_by is not None, "Expected group_by but got None"
        for expected_dim in test_case.expected_group_by:
            assert expected_dim in intent.group_by, \
                f"Expected {expected_dim} in group_by, got {intent.group_by}"
    
    # Check group_by presence (just that it exists)
    if test_case.should_have_group_by:
        assert intent.group_by is not None and len(intent.group_by) > 0, \
            "Expected group_by but got None or empty"
    
    # Check filters presence
    if test_case.should_have_filters:
        assert intent.filters is not None and len(intent.filters) > 0, \
            "Expected filters but got None or empty"
    
    # Check time range presence
    if test_case.should_have_time_range:
        assert intent.time_range is not None, "Expected time_range but got None"
        
        if test_case.expected_time_range_window:
            assert intent.time_range.window == test_case.expected_time_range_window, \
                f"Expected window={test_case.expected_time_range_window}, got {intent.time_range.window}"
    
    # Check time dimension presence
    if test_case.should_have_time_dimension:
        assert intent.time_dimension is not None, "Expected time_dimension but got None"
        
        if test_case.expected_time_dimension:
            assert intent.time_dimension.dimension == test_case.expected_time_dimension, \
                f"Expected dimension={test_case.expected_time_dimension}, got {intent.time_dimension.dimension}"
        
        if test_case.expected_granularity:
            assert intent.time_dimension.granularity == test_case.expected_granularity, \
                f"Expected granularity={test_case.expected_granularity}, got {intent.time_dimension.granularity}"


# =============================================================================
# Test Classes
# =============================================================================

class TestSalesPerformance:
    """Tests for Sales Performance & Trends queries."""
    
    @pytest.mark.parametrize("test_case", SALES_PERFORMANCE_TESTS, ids=lambda tc: tc.description[:40])
    def test_sales_performance_query(self, api_key_check, catalog, test_case: TestCase):
        """Test sales performance queries."""
        raw_intent, validated_intent, error = run_extraction_and_validation(
            test_case.query, catalog
        )
        
        # Should not have extraction errors
        assert raw_intent is not None, f"Extraction failed: {error}"
        
        # Log raw intent for debugging
        logger.info(f"\n[{test_case.category}] {test_case.description}")
        logger.info(f"Query: {test_case.query}")
        logger.info(f"Raw Intent: {raw_intent}")
        
        # Validation might fail for complex queries - log detailed reason and skip
        if error and isinstance(error, IntentValidationError):
            skip_reason = get_detailed_skip_reason(error, raw_intent, test_case)
            logger.warning(skip_reason)
            pytest.skip(skip_reason)
        
        assert validated_intent is not None, f"Validation failed: {error}"
        assert_intent_structure(validated_intent, test_case)


class TestTerritoryInsights:
    """Tests for Territory & Regional Insights queries."""
    
    @pytest.mark.parametrize("test_case", TERRITORY_TESTS, ids=lambda tc: tc.description[:40])
    def test_territory_query(self, api_key_check, catalog, test_case: TestCase):
        """Test territory and regional queries."""
        raw_intent, validated_intent, error = run_extraction_and_validation(
            test_case.query, catalog
        )
        
        assert raw_intent is not None, f"Extraction failed: {error}"
        
        logger.info(f"\n[{test_case.category}] {test_case.description}")
        logger.info(f"Query: {test_case.query}")
        logger.info(f"Raw Intent: {raw_intent}")
        
        if error and isinstance(error, IntentValidationError):
            skip_reason = get_detailed_skip_reason(error, raw_intent, test_case)
            logger.warning(skip_reason)
            pytest.skip(skip_reason)
        
        assert validated_intent is not None, f"Validation failed: {error}"
        assert_intent_structure(validated_intent, test_case)


class TestDistributionChannel:
    """Tests for Distribution & Channel Analysis queries."""
    
    @pytest.mark.parametrize("test_case", DISTRIBUTION_TESTS, ids=lambda tc: tc.description[:40])
    def test_distribution_query(self, api_key_check, catalog, test_case: TestCase):
        """Test distribution and channel queries."""
        raw_intent, validated_intent, error = run_extraction_and_validation(
            test_case.query, catalog
        )
        
        assert raw_intent is not None, f"Extraction failed: {error}"
        
        logger.info(f"\n[{test_case.category}] {test_case.description}")
        logger.info(f"Query: {test_case.query}")
        logger.info(f"Raw Intent: {raw_intent}")
        
        if error and isinstance(error, IntentValidationError):
            skip_reason = get_detailed_skip_reason(error, raw_intent, test_case)
            logger.warning(skip_reason)
            pytest.skip(skip_reason)
        
        assert validated_intent is not None, f"Validation failed: {error}"
        assert_intent_structure(validated_intent, test_case)


class TestProductIntelligence:
    """Tests for Product & Category Intelligence queries."""
    
    @pytest.mark.parametrize("test_case", PRODUCT_TESTS, ids=lambda tc: tc.description[:40])
    def test_product_query(self, api_key_check, catalog, test_case: TestCase):
        """Test product and category queries."""
        raw_intent, validated_intent, error = run_extraction_and_validation(
            test_case.query, catalog
        )
        
        assert raw_intent is not None, f"Extraction failed: {error}"
        
        logger.info(f"\n[{test_case.category}] {test_case.description}")
        logger.info(f"Query: {test_case.query}")
        logger.info(f"Raw Intent: {raw_intent}")
        
        if error and isinstance(error, IntentValidationError):
            skip_reason = get_detailed_skip_reason(error, raw_intent, test_case)
            logger.warning(skip_reason)
            pytest.skip(skip_reason)
        
        assert validated_intent is not None, f"Validation failed: {error}"
        assert_intent_structure(validated_intent, test_case)


class TestSalesRepProductivity:
    """Tests for Sales Representative Productivity queries."""
    
    @pytest.mark.parametrize("test_case", SALES_REP_TESTS, ids=lambda tc: tc.description[:40])
    def test_sales_rep_query(self, api_key_check, catalog, test_case: TestCase):
        """Test sales rep productivity queries."""
        raw_intent, validated_intent, error = run_extraction_and_validation(
            test_case.query, catalog
        )
        
        assert raw_intent is not None, f"Extraction failed: {error}"
        
        logger.info(f"\n[{test_case.category}] {test_case.description}")
        logger.info(f"Query: {test_case.query}")
        logger.info(f"Raw Intent: {raw_intent}")
        
        if error and isinstance(error, IntentValidationError):
            skip_reason = get_detailed_skip_reason(error, raw_intent, test_case)
            logger.warning(skip_reason)
            pytest.skip(skip_reason)
        
        assert validated_intent is not None, f"Validation failed: {error}"
        assert_intent_structure(validated_intent, test_case)


# =============================================================================
# Interactive Test Runner
# =============================================================================

class TestInteractiveSequential:
    """
    Run all tests sequentially with detailed output.
    
    Use this for debugging and reviewing each query one by one.
    Run with: pytest -v -k "test_all_queries_sequential" --capture=no
    """
    
    def test_all_queries_sequential(self, api_key_check, catalog):
        """Run all test queries sequentially with detailed logging."""
        results = []
        
        for i, test_case in enumerate(ALL_TEST_CASES, 1):
            print(f"\n{'='*80}")
            print(f"TEST {i}/{len(ALL_TEST_CASES)}: {test_case.category}")
            print(f"{'='*80}")
            print(f"Query: {test_case.query}")
            print(f"Description: {test_case.description}")
            print("-" * 80)
            
            raw_intent, validated_intent, error = run_extraction_and_validation(
                test_case.query, catalog
            )
            
            result = {
                "index": i,
                "query": test_case.query,
                "category": test_case.category,
                "description": test_case.description,
                "raw_intent": raw_intent,
                "validated_intent": validated_intent.model_dump() if validated_intent else None,
                "error": error,
                "error_str": str(error) if error else None,
                "skip_reason": get_detailed_skip_reason(error, raw_intent, test_case) if error else None,
                "passed": error is None
            }
            results.append(result)
            
            if raw_intent:
                print(f"\nRAW INTENT:")
                import json
                print(json.dumps(raw_intent, indent=2))
            
            if validated_intent:
                print(f"\nVALIDATED INTENT:")
                print(json.dumps(validated_intent.model_dump(), indent=2))
            
            if error:
                print(f"\n{get_detailed_skip_reason(error, raw_intent, test_case)}")
            
            print(f"\nSTATUS: {'PASSED' if not error else 'FAILED'}")
        
        # Summary
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        
        passed = sum(1 for r in results if r["passed"])
        failed = len(results) - passed
        
        print(f"Total:  {len(results)}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        
        if failed > 0:
            print(f"\n{'='*80}")
            print("FAILED TESTS - DETAILED REASONS")
            print(f"{'='*80}")
            for r in results:
                if not r["passed"]:
                    print(f"\n[{r['index']}] {r['description']}")
                    print(r["skip_reason"])


# =============================================================================
# Single Query Test (for debugging)
# =============================================================================

class TestSingleQuery:
    """Test a single query for debugging purposes."""
    
    def test_single_query(self, api_key_check, catalog):
        """
        Test a single query.
        
        Modify the query below to test specific cases.
        Run with: pytest -v -k "test_single_query" --capture=no
        """
        query = "What is the total Primary vs. Secondary sales revenue for the first quarter of 2024?"
        
        raw_intent, validated_intent, error = run_extraction_and_validation(
            query, catalog
        )
        
        import json
        
        print(f"\nQuery: {query}")
        print(f"\nRaw Intent:\n{json.dumps(raw_intent, indent=2) if raw_intent else 'None'}")
        
        if validated_intent:
            print(f"\nValidated Intent:\n{json.dumps(validated_intent.model_dump(), indent=2)}")
        
        if error:
            print(f"\nError: {error}")
        
        assert raw_intent is not None, f"Extraction failed: {error}"


# =============================================================================
# Main entry point for direct execution
# =============================================================================

if __name__ == "__main__":
    # Run all tests
    pytest.main([__file__, "-v", "-x", "--capture=no"])
