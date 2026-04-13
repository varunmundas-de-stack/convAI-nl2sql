import dspy

class InterpretQuery(dspy.Signature):
    """
    Resolve the current user input into a complete, standalone query
    using conversation history and structured session context.
    Expand pronouns, resolve references, and fill in any implied context
    so the output can be understood with zero prior context.
    """
    current_input: str = dspy.InputField(
        desc="Latest user message"
    )
    conversation: str = dspy.InputField(
        desc="Recent conversation turns formatted as alternating User/System messages. "
             "Includes clarification exchanges and system responses.",
        default=""
    )
    session_context: str = dspy.InputField(
        desc="Structured context: resolved metrics, dimensions, filters, scope, and time range from prior intent.",
        default=""
    )
    resolved_query: str = dspy.OutputField(
    desc=(
        "A fully specified, unambiguous, standalone natural language query in plain conversational English. "
        "Resolve vague or ambiguous terms to their exact catalog equivalents using session context. "
        "Only use words that appear in the catalog or were explicitly stated by the user. "
        "Never ask questions, never express uncertainty, never request clarification. "
        "Never introduce aggregation words, structural phrases, or paraphrasing that wasn't in the original input. "
        "Preserve the user's original terms where they are already unambiguous."
    )
)
