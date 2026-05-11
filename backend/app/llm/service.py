import os
import anthropic
import logging

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = os.getenv("ANTHROPIC_MODEL_ID", "claude-haiku-4-5-20251001")

    async def generate_insights(self, prompt: str) -> str:
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return "[]"
