# import anthropic
# from dotenv import load_dotenv
# import os
# import logging
# import time
# import random
# from arize.otel import register
# from openinference.instrumentation.anthropic import AnthropicInstrumentor

# # Load environment variables from .env file
# load_dotenv()

# # =============================================================================
# # CONFIGURATION (Explicit, loaded from environment)
# # =============================================================================
# logger = logging.getLogger(__name__)

# try:
#     MODEL_ID = os.getenv("ANTHROPIC_MODEL_ID")
#     TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", 0.0)) # Deterministic: extraction is parsing, not generation
#     MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", 4096)) # Sufficient for intent JSON output
#     TIMEOUT_SECONDS = float(os.getenv("MODEL_TIMEOUT_SECONDS", 120.0)) # Give Claude enough time for long generations
#     FALLBACK_MODEL_ID = os.getenv("FALLBACK_MODEL_ID", "claude-sonnet-4-5")
# except Exception as e:
#     logger.error(f"Error loading configuration: {e}")


# client = anthropic.Anthropic(
#         api_key=os.getenv("ANTHROPIC_API_KEY"),
#         timeout=TIMEOUT_SECONDS)


# MAX_RETRIES = 5
# MAX_BACKOFF = 20

# tracer_provider = register(
#     space_id = "U3BhY2U6Mzg1MDE6dVlmZg==",
#     api_key = os.getenv("ARIZE_API_KEY"),
#     project_name = "nl2sql",
# )

# AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)


# def _call_model(model_id: str, prompt: str, max_tokens: int = None):
#     return client.messages.create(
#         model=model_id,
#         max_tokens=max_tokens or MAX_TOKENS,
#         temperature=TEMPERATURE,
#         messages=[{"role": "user", "content": prompt}]
#     )

# def call_claude(prompt: str, max_tokens: int = None):
#     last_exception = None

#     for attempt in range(MAX_RETRIES):
#         try:
#             logger.info(f"Calling LLM (attempt {attempt+1}) with model: {MODEL_ID}")
#             return _call_model(MODEL_ID, prompt, max_tokens)

#         except APIError as e:
#             last_exception = e

#             status_code = getattr(e, "status_code", None)

#             # Retry only for retryable errors
#             if status_code in (429, 500, 502, 503, 504, 529):
#                 backoff = min((2 ** attempt) + random.uniform(0, 0.5), MAX_BACKOFF)
#                 logger.warning(
#                     f"Retryable LLM error ({status_code}). "
#                     f"Sleeping {backoff:.2f}s"
#                 )
#                 time.sleep(backoff)
#                 continue
#             else:
#                 logger.error(f"Non-retryable LLM error: {e}")
#                 raise

#         except Exception as e:
#             last_exception = e
#             logger.error(f"Unexpected LLM error: {e}")
#             raise

#     # Fallback model
#     if FALLBACK_MODEL_ID:
#         logger.warning("Primary model failed. Trying fallback model.")
#         try:
#             return _call_model(FALLBACK_MODEL_ID, prompt, max_tokens)
#         except Exception as e:
#             logger.error(f"Fallback model failed: {e}")
#             raise

#     raise last_exception


# def count_tokens(prompt: str) -> int:
#     """
#     Count tokens in prompt.
#     """
#     return client.messages.count_tokens(
#         model=MODEL_ID,
#         messages=[
#             {"role": "user", "content": prompt}
#         ]
#     )