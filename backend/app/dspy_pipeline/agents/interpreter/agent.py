import dspy
from .signature import InterpretQuery

class QueryInterpreterModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.ChainOfThought(InterpretQuery)

    def forward(self, current_input: str, conversation: str, session_context: str) -> str:
        result = self.predict(
            current_input=current_input,
            conversation=conversation,
            session_context=session_context,
        )
        return result.resolved_query