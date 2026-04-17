import dspy
from .signature import InterpretQuery
import logging

logger = logging.getLogger(__name__)

class QueryInterpreterModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.ChainOfThought(InterpretQuery)

    def forward(self, current_input: str, conversation: str, session_context: str) -> str:
        logger.info("Session Context for Interpreter: %s", session_context)
        result = self.predict(
            current_input=current_input,
            conversation=conversation,
            session_context=session_context,
        )
        return result.resolved_query