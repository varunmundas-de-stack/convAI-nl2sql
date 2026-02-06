import pytest
from unittest.mock import MagicMock
from app.services.intent_extractor import extract_intent, JSONParseError, ExtractionError

# Mock response structure for anthropic
class MockContent:
    def __init__(self, text):
        self.text = text

class MockResponse:
    def __init__(self, text):
        self.content = [MockContent(text)]

def test_extract_valid_intent(mocker):
    mock_response = MockResponse('{"intent_type": "snapshot", "metric": "fact_primary_sales.count"}')
    mocker.patch("app.services.intent_extractor.call_claude", return_value=mock_response)
    # also mock count_tokens to avoid network call
    mocker.patch("app.services.intent_extractor.count_tokens", return_value=MagicMock(input_tokens=10))

    intent = extract_intent("Show me total sales")
    assert intent["intent_type"] == "snapshot"
    assert intent["metric"] == "fact_primary_sales.count"

def test_extract_intent_with_markdown_blocks(mocker):
    # LLM often returns markdown code blocks
    json_text = '```json\n{"intent_type": "trend", "metric": "fact_primary_sales.count"}\n```'
    mock_response = MockResponse(json_text)
    mocker.patch("app.services.intent_extractor.call_claude", return_value=mock_response)
    mocker.patch("app.services.intent_extractor.count_tokens", return_value=MagicMock(input_tokens=10))

    intent = extract_intent("Trend of sales")
    assert intent["intent_type"] == "trend"

def test_extract_intent_extra_fields(mocker):
    # LLM returns extra fields - extract_intent is just a parser, so it should return them.
    # Validation happens downstream.
    json_text = '{"intent_type": "snapshot", "extra_field": "ignore_me"}'
    mock_response = MockResponse(json_text)
    mocker.patch("app.services.intent_extractor.call_claude", return_value=mock_response)
    mocker.patch("app.services.intent_extractor.count_tokens", return_value=MagicMock(input_tokens=10))

    intent = extract_intent("query")
    assert intent["extra_field"] == "ignore_me"

def test_extract_intent_malformed_json(mocker):
    json_text = '{"intent_type": "snapshot", "metric": ... invalid json'
    mock_response = MockResponse(json_text)
    mocker.patch("app.services.intent_extractor.call_claude", return_value=mock_response)
    mocker.patch("app.services.intent_extractor.count_tokens", return_value=MagicMock(input_tokens=10))

    with pytest.raises(JSONParseError):
        extract_intent("query")

def test_extract_intent_reordered_fields(mocker):
    json_text = '{"metric": "fact_primary_sales.count", "intent_type": "snapshot"}'
    mock_response = MockResponse(json_text)
    mocker.patch("app.services.intent_extractor.call_claude", return_value=mock_response)
    mocker.patch("app.services.intent_extractor.count_tokens", return_value=MagicMock(input_tokens=10))

    intent = extract_intent("query")
    assert intent["intent_type"] == "snapshot"
    assert intent["metric"] == "fact_primary_sales.count"
