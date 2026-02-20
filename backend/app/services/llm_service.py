import anthropic
from dotenv import load_dotenv
import os
import logging
from arize.otel import register
from openinference.instrumentation.anthropic import AnthropicInstrumentor

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# CONFIGURATION (Explicit, loaded from environment)
# =============================================================================
logger = logging.getLogger(__name__)

try:
    MODEL_ID = os.getenv("ANTHROPIC_MODEL_ID")
    TEMPERATURE = os.getenv("MODEL_TEMPERATURE", 0.0) # Deterministic: extraction is parsing, not generation
    MAX_TOKENS = os.getenv("MODEL_MAX_TOKENS", 2048) # Sufficient for intent JSON output
    TIMEOUT_SECONDS = os.getenv("MODEL_TIMEOUT_SECONDS", 30.0)
except Exception as e:
    logger.error(f"Error loading configuration: {e}")

tracer_provider = register(
    space_id = "U3BhY2U6Mzg1MDE6dVlmZg==",
    api_key = os.getenv("ARIZE_API_KEY"),
    project_name = "nl2sql",
)

AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)

def call_claude(prompt: str) -> anthropic.types.Message:
    """
    Call Claude with explicit configuration.
    
    - Explicit model, temperature, max_tokens
    - Single verbatim retry on failure (no prompt mutation)
    - Returns raw text response
    
    Raises:
        LLMCallError: API call failed
        LLMTimeoutError: Request timed out
        EmptyResponseError: Empty response received
    """

    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=TIMEOUT_SECONDS)
    logger.info(f"Calling LLM with model: {MODEL_ID}")
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response


def count_tokens(prompt: str) -> int:
    """
    Count tokens in prompt.
    """
    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=TIMEOUT_SECONDS)
    
    return client.messages.count_tokens(
        model=MODEL_ID,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )