"""
Test for Clarification Tool

Basic tests to ensure the clarification tool works correctly.
"""

import pytest
from app.dspy_pipeline.clarification_tool import (
    ClarificationTool,
    ClarificationOption,
    ClarificationType,
    ClarificationContext,
    ClarificationRequiredException,
)


def test_basic_clarification_flow():
    """Test basic clarification request and response flow."""
    tool = ClarificationTool()

    # Create options
    options = [
        ClarificationOption(
            id="net_sales",
            label="Net Sales",
            description="Sales after discounts",
            value="net_value"
        ),
        ClarificationOption(
            id="gross_sales",
            label="Gross Sales",
            description="Sales before discounts",
            value="gross_value"
        )
    ]

    # Request clarification
    request_id = tool.request_clarification(
        clarification_type=ClarificationType.METRIC,
        field_name="metrics",
        question="Which sales metric?",
        context="Ambiguous sales reference",
        options=options
    )

    assert isinstance(request_id, str)
    assert tool.has_pending_clarifications()

    # Provide response
    response = tool.provide_clarification(
        request_id=request_id,
        selected_option_ids=["net_sales"]
    )

    assert response.resolved_value == "net_value"
    assert response.confidence == 1.0
    assert not tool.has_pending_clarifications()


def test_multiple_selection():
    """Test multiple option selection."""
    tool = ClarificationTool()

    options = [
        ClarificationOption(id="opt1", label="Option 1", value="val1"),
        ClarificationOption(id="opt2", label="Option 2", value="val2"),
        ClarificationOption(id="opt3", label="Option 3", value="val3")
    ]

    request_id = tool.request_clarification(
        clarification_type=ClarificationType.DIMENSION,
        field_name="group_by",
        question="Which dimensions?",
        context="Multiple dimensions available",
        options=options,
        allow_multiple=True
    )

    response = tool.provide_clarification(
        request_id=request_id,
        selected_option_ids=["opt1", "opt3"]
    )

    assert response.resolved_value == ["val1", "val3"]


def test_custom_value():
    """Test custom value provision."""
    tool = ClarificationTool()

    options = [
        ClarificationOption(id="standard", label="Standard", value="std_value")
    ]

    request_id = tool.request_clarification(
        clarification_type=ClarificationType.GENERAL,
        field_name="custom_field",
        question="What value?",
        context="Custom input allowed",
        options=options,
        allow_custom=True
    )

    response = tool.provide_clarification(
        request_id=request_id,
        custom_value="my_custom_value"
    )

    assert response.resolved_value == "my_custom_value"
    assert response.confidence == 0.8


def test_dspy_metric_clarification():
    """Test DSPy metric clarification method."""
    tool = ClarificationTool()

    context = ClarificationContext(
        agent_name="TestAgent",
        step_name="extract_metrics",
        input_data="show me sales"
    )

    available_metrics = [
        {"name": "net_value", "label": "Net Sales", "description": "Net sales"},
        {"name": "gross_value", "label": "Gross Sales", "description": "Gross sales"}
    ]

    # This should raise ClarificationRequiredException
    with pytest.raises(ClarificationRequiredException) as exc_info:
        tool.request_metric_clarification(
            ambiguous_terms=["sales"],
            available_metrics=available_metrics,
            agent_context=context
        )

    exception = exc_info.value
    assert isinstance(exception.request_id, str)
    assert exception.clarification_request.clarification_type == ClarificationType.METRIC
    assert "sales" in exception.clarification_request.question


def test_error_handling():
    """Test error handling for invalid inputs."""
    tool = ClarificationTool()

    # Empty options should raise error
    with pytest.raises(ValueError, match="At least one clarification option"):
        tool.request_clarification(
            clarification_type=ClarificationType.METRIC,
            field_name="metrics",
            question="Which?",
            context="Test",
            options=[]
        )

    # Duplicate option IDs should raise error
    duplicate_options = [
        ClarificationOption(id="same", label="Option 1", value="val1"),
        ClarificationOption(id="same", label="Option 2", value="val2")
    ]

    with pytest.raises(ValueError, match="unique IDs"):
        tool.request_clarification(
            clarification_type=ClarificationType.METRIC,
            field_name="metrics",
            question="Which?",
            context="Test",
            options=duplicate_options
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])