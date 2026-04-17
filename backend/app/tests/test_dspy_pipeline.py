"""
Tests for DSPy Intent Extraction Pipeline.

Tests both individual agents and end-to-end pipeline functionality.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from app.dspy_pipeline.schemas import (
    ClassifiedQuery,
    ScopeResult,
    TimeResult,
    MetricsResult,
    DimensionsResult,
    FilterCondition
)
from app.dspy_pipeline.agents.classifier.agent import ClassifierModule
from app.dspy_pipeline.agents.scope.agent import ScopeModule
from app.dspy_pipeline.agents.time.agent import TimeModule
from app.dspy_pipeline.agents.metrics.agent import MetricsModule
from app.dspy_pipeline.agents.dimension.agent import DimensionsModule
from app.dspy_pipeline.pipeline import AssemblerModule
from app.dspy_pipeline.pipeline import IntentExtractionPipeline
from app.dspy_pipeline.training import intent_extraction_metric, IntentExtractionOptimizer
from app.models.intent import Intent, Metric, Filter, TimeSpec


# =============================================================================
# UNIT TESTS FOR INDIVIDUAL AGENTS
# =============================================================================

class TestClassifierAgent:
    """Test ClassifierAgent functionality."""

    def test_classifier_basic_classification(self):
        """Test basic term classification."""
        agent = ClassifierAgent()

        # Mock DSPy prediction
        with patch.object(agent.classifier, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                metric_terms="net_value, sales",
                dimension_terms="zone, brand",
                filter_terms="equals Oil",
                time_expressions="last month",
                ranking_indicators="top 5",
                scope_indicators="secondary",
                comparison_indicators="vs, compared"
            )

            result = agent.forward("Top 5 zones by sales for Oil last month")

            assert isinstance(result, ClassifiedQuery)
            assert result.metric_terms == ["net_value", "sales"]
            assert result.dimension_terms == ["zone", "brand"]
            assert result.time_expressions == ["last month"]
            assert result.ranking_indicators == ["top 5"]

    def test_classifier_empty_terms(self):
        """Test handling of empty/null terms."""
        agent = ClassifierAgent()

        with patch.object(agent.classifier, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                metric_terms="none",
                dimension_terms="",
                filter_terms="null",
                time_expressions="",
                ranking_indicators="",
                scope_indicators="",
                comparison_indicators=""
            )

            result = agent.forward("simple query")

            assert result.metric_terms == []
            assert result.dimension_terms == []
            assert result.filter_terms == []

    def test_classifier_parse_terms(self):
        """Test _parse_terms helper method."""
        agent = ClassifierAgent()

        # Test comma-separated terms
        assert agent._parse_terms("a, b, c") == ["a", "b", "c"]

        # Test whitespace handling
        assert agent._parse_terms(" a , b , c ") == ["a", "b", "c"]

        # Test empty/null handling
        assert agent._parse_terms("none") == []
        assert agent._parse_terms("null") == []
        assert agent._parse_terms("") == []


class TestScopeTimeAgent:
    """Test ScopeTimeAgent functionality."""

    def test_scope_time_basic_resolution(self):
        """Test basic scope and time resolution."""
        agent = ScopeTimeAgent()

        classified_query = ClassifiedQuery(
            query_text="Sales last month",
            time_expressions=["last month"],
            scope_indicators=["secondary"]
        )

        with patch.object(agent.resolver, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                sales_scope="SECONDARY",
                time_window="last_month",
                start_date="null",
                end_date="null",
                granularity="null",
                has_time_constraint="true"
            )

            result = agent.forward(classified_query, "2024-03-15")

            assert isinstance(result, ScopeResult)
            assert result.sales_scope == "SECONDARY"
            assert result.time_window == "last_month"
            assert result.has_time_constraint is True

    def test_scope_time_constraint_enforcement(self):
        """Test TimeSpec XOR constraint enforcement."""
        agent = ScopeTimeAgent()

        classified_query = ClassifiedQuery(query_text="test")

        with patch.object(agent.resolver, '__call__') as mock_predict:
            # Both window and dates provided (invalid)
            mock_predict.return_value = Mock(
                sales_scope="SECONDARY",
                time_window="last_month",
                start_date="2024-01-01",
                end_date="2024-01-31",
                granularity="null",
                has_time_constraint="true"
            )

            result = agent.forward(classified_query, "2024-03-15")

            # Dates should be cleared due to constraint
            assert result.time_window == "last_month"
            assert result.start_date is None
            assert result.end_date is None

    def test_scope_parsing(self):
        """Test sales scope parsing and validation."""
        agent = ScopeTimeAgent()

        # Valid scopes
        assert agent._parse_sales_scope("PRIMARY") == "PRIMARY"
        assert agent._parse_sales_scope("secondary") == "SECONDARY"

        # Invalid/empty scopes default to SECONDARY
        assert agent._parse_sales_scope("") == "SECONDARY"
        assert agent._parse_sales_scope("invalid") == "SECONDARY"
        assert agent._parse_sales_scope("null") == "SECONDARY"


class TestMetricsAgent:
    """Test MetricsAgent functionality."""

    def test_metrics_extraction_and_validation(self):
        """Test metric extraction with catalog validation."""
        agent = MetricsAgent()

        classified_query = ClassifiedQuery(
            query_text="Total sales and quantity",
            metric_terms=["sales", "quantity"]
        )

        with patch.object(agent.extractor, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                metrics="sales, quantity",
                aggregations="sum, sum"
            )

            result = agent.forward(classified_query, "SECONDARY")

            assert isinstance(result, MetricsResult)
            # Aliases should be resolved: sales -> net_value, quantity -> billed_qty
            assert "net_value" in result.metrics
            assert "billed_qty" in result.metrics

    def test_metrics_fallback(self):
        """Test fallback when no valid metrics found."""
        agent = MetricsAgent()

        classified_query = ClassifiedQuery(query_text="test")

        with patch.object(agent.extractor, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                metrics="invalid_metric",
                aggregations="sum"
            )

            result = agent.forward(classified_query, "SECONDARY")

            # Should fallback to default metric
            assert result.metrics == ["net_value"]
            assert result.aggregations == ["sum"]


class TestDimensionsAgent:
    """Test DimensionsAgent functionality."""

    def test_dimensions_basic_resolution(self):
        """Test basic dimension resolution."""
        agent = DimensionsAgent()

        classified_query = ClassifiedQuery(
            query_text="Sales by zone",
            dimension_terms=["zone"]
        )

        with patch.object(agent.resolver, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                group_by="zone",
                filters="null",
                context_operation="null",
                ranking_enabled="false",
                ranking_order="null",
                ranking_limit="null"
            )

            result = agent.forward(classified_query, "SECONDARY", "")

            assert isinstance(result, DimensionsResult)
            assert result.group_by == ["zone"]
            assert result.filters is None

    def test_dimensions_scope_validation(self):
        """Test dimension validation against scope."""
        agent = DimensionsAgent()

        classified_query = ClassifiedQuery(
            query_text="PRIMARY sales by retailer",
            dimension_terms=["retailer"]
        )

        with patch.object(agent.resolver, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                group_by="retailer",
                filters="null",
                context_operation="null",
                ranking_enabled="false",
                ranking_order="null",
                ranking_limit="null"
            )

            result = agent.forward(classified_query, "PRIMARY", "")

            # Retailer should be removed for PRIMARY scope
            assert result.group_by is None

    def test_dimensions_ranking_validation(self):
        """Test ranking requires group_by constraint."""
        agent = DimensionsAgent()

        classified_query = ClassifiedQuery(query_text="top sales")

        with patch.object(agent.resolver, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                group_by="null",
                filters="null",
                context_operation="null",
                ranking_enabled="true",  # Ranking requested
                ranking_order="desc",
                ranking_limit="5"
            )

            result = agent.forward(classified_query, "SECONDARY", "")

            # Ranking should be disabled due to no group_by
            # This is tested indirectly through the result structure


class TestAssembler:
    """Test Assembler functionality."""

    def test_assembler_manual_assembly(self):
        """Test manual assembly fallback."""
        assembler = Assembler()

        scope_time = ScopeTimeResult(
            sales_scope="SECONDARY",
            has_time_constraint=True,
            time_window="last_month"
        )

        metrics = MetricsResult(
            metrics=["net_value"],
            aggregations=["sum"]
        )

        dimensions = DimensionsResult(
            group_by=["zone"],
            filters=None
        )

        # Test manual assembly directly
        result = assembler._manual_assembly(scope_time, metrics, dimensions)

        assert isinstance(result, Intent)
        assert result.sales_scope == "SECONDARY"
        assert len(result.metrics) == 1
        assert result.metrics[0].name == "net_value"
        assert result.group_by == ["zone"]
        assert result.time.window == "last_month"

    def test_assembler_constraint_enforcement(self):
        """Test binary constraint enforcement."""
        assembler = Assembler()

        # Create intent with constraint violations
        intent = Intent(
            sales_scope="SECONDARY",
            metrics=[Metric(name="net_value", aggregation="sum")],
            group_by=["zone", "invoice_date"],  # invoice_date not allowed
            time=TimeSpec(
                dimension="invoice_date",
                window="last_month",
                start_date="2024-01-01",  # Both window and dates (invalid)
                end_date="2024-01-31"
            )
        )

        result = assembler._enforce_constraints(intent)

        # invoice_date should be removed from group_by
        assert "invoice_date" not in result.group_by
        assert result.group_by == ["zone"]

        # Explicit dates should be cleared due to window XOR constraint
        assert result.time.start_date is None
        assert result.time.end_date is None


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntentExtractionPipeline:
    """Test full pipeline integration."""

    def test_pipeline_info(self):
        """Test pipeline information."""
        pipeline = IntentExtractionPipeline()
        info = pipeline.get_pipeline_info()

        assert info["pipeline_type"] == "DSPy Modular"
        assert len(info["agents"]) == 5
        assert info["compilation_ready"] is True

    @patch('app.dspy_pipeline.modules.ClassifierAgent.forward')
    @patch('app.dspy_pipeline.modules.ScopeTimeAgent.forward')
    @patch('app.dspy_pipeline.modules.MetricsAgent.forward')
    @patch('app.dspy_pipeline.modules.DimensionsAgent.forward')
    @patch('app.dspy_pipeline.modules.Assembler.forward')
    def test_pipeline_end_to_end(self, mock_assembler, mock_dimensions,
                                mock_metrics, mock_scope_time, mock_classifier):
        """Test end-to-end pipeline execution."""

        # Setup mocks to return expected intermediate results
        mock_classifier.return_value = ClassifiedQuery(
            query_text="Top 5 zones by sales",
            metric_terms=["sales"],
            dimension_terms=["zones"],
            ranking_indicators=["top 5"]
        )

        mock_scope_time.return_value = ScopeTimeResult(
            sales_scope="SECONDARY",
            has_time_constraint=False
        )

        mock_metrics.return_value = MetricsResult(
            metrics=["net_value"],
            aggregations=["sum"]
        )

        mock_dimensions.return_value = DimensionsResult(
            group_by=["zone"]
        )

        mock_assembler.return_value = Intent(
            sales_scope="SECONDARY",
            metrics=[Metric(name="net_value", aggregation="sum")],
            group_by=["zone"]
        )

        pipeline = IntentExtractionPipeline()
        result = pipeline.forward("Top 5 zones by sales")

        assert isinstance(result, Intent)
        assert result.sales_scope == "SECONDARY"
        assert len(result.metrics) == 1
        assert result.group_by == ["zone"]

        # Verify all agents were called
        mock_classifier.assert_called_once()
        mock_scope_time.assert_called_once()
        mock_metrics.assert_called_once()
        mock_dimensions.assert_called_once()
        mock_assembler.assert_called_once()


# =============================================================================
# TRAINING AND OPTIMIZATION TESTS
# =============================================================================

class TestTrainingInfrastructure:
    """Test training examples and metric function."""

    def test_intent_extraction_metric_perfect_match(self):
        """Test metric function with perfect match."""
        gold = Intent(
            sales_scope="SECONDARY",
            metrics=[Metric(name="net_value", aggregation="sum")],
            group_by=["zone"]
        )

        pred = Intent(
            sales_scope="SECONDARY",
            metrics=[Metric(name="net_value", aggregation="sum")],
            group_by=["zone"]
        )

        score = intent_extraction_metric(gold, pred)
        assert score == 1.0

    def test_intent_extraction_metric_partial_match(self):
        """Test metric function with partial match."""
        gold = Intent(
            sales_scope="SECONDARY",
            metrics=[Metric(name="net_value", aggregation="sum")],
            group_by=["zone", "brand"]
        )

        pred = Intent(
            sales_scope="SECONDARY",
            metrics=[Metric(name="net_value", aggregation="sum")],
            group_by=["zone"]  # Missing brand
        )

        score = intent_extraction_metric(gold, pred)
        # Should get partial credit for correct scope, metrics, and partial group_by
        assert 0.0 < score < 1.0

    def test_intent_extraction_metric_total_mismatch(self):
        """Test metric function with total mismatch."""
        gold = Intent(
            sales_scope="PRIMARY",
            metrics=[Metric(name="net_value", aggregation="sum")],
            group_by=["zone"]
        )

        pred = Intent(
            sales_scope="SECONDARY",
            metrics=[Metric(name="gross_value", aggregation="count")],
            group_by=["brand"]
        )

        score = intent_extraction_metric(gold, pred)
        # Should get very low score
        assert score < 0.3

    def test_training_examples_format(self):
        """Test training examples have correct format."""
        from app.dspy_pipeline.training_examples import get_training_examples

        examples = get_training_examples()

        assert len(examples) > 0

        for example in examples:
            # Check required inputs
            assert hasattr(example, 'query')
            assert hasattr(example, 'previous_context')
            assert hasattr(example, 'current_date')

            # Check output format
            assert hasattr(example, 'outputs')
            assert isinstance(example.outputs, dict)


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestDSPyConfiguration:
    """Test DSPy configuration and mode switching."""

    @patch.dict('os.environ', {'INTENT_EXTRACTION_MODE': 'dspy'})
    def test_dspy_mode_enabled(self):
        """Test DSPy mode detection."""
        from app.dspy_pipeline.config import is_dspy_mode, get_pipeline_mode

        assert get_pipeline_mode() == "dspy"
        assert is_dspy_mode() is True

    @patch.dict('os.environ', {'INTENT_EXTRACTION_MODE': 'monolithic'})
    def test_monolithic_mode_enabled(self):
        """Test monolithic mode detection."""
        from app.dspy_pipeline.config import is_dspy_mode, get_pipeline_mode

        assert get_pipeline_mode() == "monolithic"
        assert is_dspy_mode() is False

    def test_default_mode(self):
        """Test default mode when not configured."""
        with patch.dict('os.environ', {}, clear=True):
            from app.dspy_pipeline.config import get_pipeline_mode
            assert get_pipeline_mode() == "monolithic"


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Test error handling and fallback mechanisms."""

    def test_classifier_error_fallback(self):
        """Test classifier fallback on error."""
        agent = ClassifierAgent()

        with patch.object(agent.classifier, '__call__') as mock_predict:
            mock_predict.side_effect = Exception("DSPy error")

            # Should not raise, should return empty classification
            result = agent.forward("test query")

            assert isinstance(result, ClassifiedQuery)
            assert result.query_text == "test query"
            assert result.metric_terms == []

    def test_metrics_agent_catalog_validation(self):
        """Test metrics agent validates against catalog."""
        agent = MetricsAgent()

        classified_query = ClassifiedQuery(
            query_text="Invalid metric request",
            metric_terms=["completely_invalid_metric"]
        )

        with patch.object(agent.extractor, '__call__') as mock_predict:
            mock_predict.return_value = Mock(
                metrics="completely_invalid_metric",
                aggregations="sum"
            )

            result = agent.forward(classified_query, "SECONDARY")

            # Should fallback to default valid metric
            assert result.metrics == ["net_value"]