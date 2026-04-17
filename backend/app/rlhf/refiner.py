"""
Claude-powered prompt refinement.

- build_meta_prompt: constructs a meta-prompt with chosen/rejected pairs
- run_refinement: calls Claude to suggest improvements
- apply_refinement: saves new versioned prompt file
- rollback_version: reverts to parent version
"""

import json
import logging
from pathlib import Path
from typing import Optional

from app.rlhf.db import get_session
from app.rlhf.models import PromptVersion
from app.rlhf.feedback_service import get_preference_pairs, get_top_responses
from app.rlhf.prompt_manager import get_active_prompt, inject_few_shots, PROMPTS_DIR

logger = logging.getLogger(__name__)


def build_meta_prompt(
    preference_pairs: list[dict],
    current_prompt: str,
) -> str:
    """
    Construct a meta-prompt asking Claude to improve the system prompt
    based on chosen/rejected preference pairs.
    """
    # Escape all braces in the prompt EXCEPT the live placeholders,
    # so Python's f-string doesn't try to evaluate {sales_scope} etc.
    known_placeholders = ["{current_date}", "{query}", "{previous_context}"]
    sentinels = {}
    escaped_prompt = current_prompt
    for i, ph in enumerate(known_placeholders):
        sentinel = f"__PH_{i}__"
        sentinels[sentinel] = ph
        escaped_prompt = escaped_prompt.replace(ph, sentinel)
    escaped_prompt = escaped_prompt.replace("{", "{{").replace("}", "}}")
    for sentinel, ph in sentinels.items():
        escaped_prompt = escaped_prompt.replace(sentinel, ph)

    pairs_text = ""
    for i, pair in enumerate(preference_pairs, 1):
        chosen = pair["chosen"]
        rejected = pair["rejected"]
        pairs_text += f"\n--- Pair {i} ---\n"
        pairs_text += f"User Query: {pair['query']}\n\n"
        pairs_text += f"CHOSEN (rating {chosen['rating']}):\n"
        pairs_text += f"  Summary: {chosen['response_summary']}\n"
        if chosen.get("full_response"):
            pairs_text += f"  Full Response: {chosen['full_response']}\n"
        if chosen.get("sql_query"):
            pairs_text += f"  SQL Query: {chosen['sql_query']}\n"
        if chosen.get("correction"):
            pairs_text += f"  Human Correction: {chosen['correction']}\n"
        pairs_text += f"\nREJECTED (rating {rejected['rating']}):\n"
        pairs_text += f"  Summary: {rejected['response_summary']}\n"
        if rejected.get("full_response"):
            pairs_text += f"  Full Response: {rejected['full_response']}\n"
        if rejected.get("sql_query"):
            pairs_text += f"  SQL Query: {rejected['sql_query']}\n"
        if rejected.get("correction"):
            pairs_text += f"  Human Correction: {rejected['correction']}\n"

    meta_prompt = f"""You are an expert prompt engineer. Your task is to improve a system prompt for an NL2SQL intent extraction chatbot.

## Current System Prompt
```
{escaped_prompt}
```

## Human Feedback (Preference Pairs)
The following pairs show responses that humans preferred (CHOSEN) vs. responses they disliked (REJECTED) for the same query:
{pairs_text}

## Your Task
1. Analyze the patterns in what makes CHOSEN responses better than REJECTED ones
2. Identify specific weaknesses in the current prompt that led to rejected responses
3. Suggest concrete, minimal edits to the system prompt to improve quality
4. Pay special attention to any human corrections — these are gold-standard preferences

## Output Format
First, return a JSON object with your analysis:
```json
{{
    "analysis": "Brief analysis of patterns found",
    "edits": [
        {{
            "section": "Which part of the prompt to modify",
            "original": "The original text (or 'NEW' if adding)",
            "replacement": "The improved text",
            "rationale": "Why this change helps"
        }}
    ]
}}
```

Then output the complete improved system prompt under the header:
### NEW PROMPT
"""
    return meta_prompt

def run_refinement(version: str) -> dict:
    """
    Run Claude-powered refinement for a version.

    Returns the parsed refinement result dict.
    """
    from app.services.llm_service import call_claude

    # Get current prompt
    current_prompt = get_active_prompt(version)

    # Get preference pairs
    pairs = get_preference_pairs(version, min_gap=2)
    if not pairs:
        logger.warning(f"No preference pairs found for version {version}")
        return {"status": "skipped", "reason": "No preference pairs with sufficient rating gap"}

    # Build meta-prompt
    meta_prompt = build_meta_prompt(pairs, current_prompt)

    # Call Claude
    logger.info(f"Calling Claude for prompt refinement (version={version}, {len(pairs)} pairs)")
    response = call_claude(meta_prompt, max_tokens=8192)
    raw_text = response.content[0].text

    json_text = ""
    new_prompt_text = ""

    # 1. Extract JSON block
    if "```json" in raw_text:
        start = raw_text.find("```json") + 7
        end = raw_text.find("```", start)
        if end == -1:
            json_text = raw_text[start:] # Try best effort if truncated
        else:
            json_text = raw_text[start:end].strip()
    else:
        # Fallback if no json tags
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1:
            json_text = raw_text[start:end+1]

    # 2. Extract NEW PROMPT block
    if "### NEW PROMPT" in raw_text:
        prompt_start = raw_text.find("### NEW PROMPT") + 14
        new_prompt_text = raw_text[prompt_start:].strip()
        # Clean off trailing markdown backticks if Claude accidentally wrapped it
        if new_prompt_text.startswith("```"):
            new_prompt_text = new_prompt_text.split("\n", 1)[-1]
        if new_prompt_text.endswith("```"):
            new_prompt_text = new_prompt_text.rsplit("\n", 1)[0]
    else:
        # If Claude fails to use the exact header, fallback to taking whatever is after the JSON block
        end_of_json = raw_text.rfind("}") + 1
        new_prompt_text = raw_text[end_of_json:].strip()
        new_prompt_text = new_prompt_text.strip("` \n")

    try:
        result = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse refinement JSON: {e}\nRaw output: {raw_text[:500]}...")
        return {"status": "error", "reason": f"Invalid JSON from Claude: {e}"}

    if not new_prompt_text:
        return {"status": "error", "reason": "Failed to extract the new prompt text from Claude's response."}

    result["new_prompt"] = new_prompt_text
    result["status"] = "success"
    return result


def apply_refinement(refinement_result: dict, base_version: str) -> str:
    """
    Write a new versioned prompt file and register it in the database.

    Returns the new version tag.
    """
    new_prompt = refinement_result.get("new_prompt")
    if not new_prompt:
        raise ValueError("Refinement result missing 'new_prompt' field")

    # Determine next version number
    with get_session() as session:
        latest = (
            session.query(PromptVersion)
            .order_by(PromptVersion.id.desc())
            .first()
        )
        if latest:
            # Extract version number from tag like "v3"
            try:
                current_num = int(latest.version_tag.lstrip("v"))
            except ValueError:
                current_num = 1
            next_num = current_num + 1
        else:
            next_num = 2

    new_tag = f"v{next_num}"
    new_filename = f"intent_extraction_{new_tag}.txt"
    new_filepath = PROMPTS_DIR / new_filename

    # Optionally inject few-shots
    top_responses = get_top_responses(base_version, top_n=5)
    if top_responses:
        new_prompt = inject_few_shots(new_prompt, top_responses)
        few_shot_count = len(top_responses)
    else:
        few_shot_count = 0

    # Write file
    new_filepath.write_text(new_prompt, encoding="utf-8")
    logger.info(f"Wrote new prompt: {new_filepath} ({len(new_prompt)} chars, {few_shot_count} few-shots)")

    # Register in DB
    with get_session() as session:
        version = PromptVersion(
            version_tag=new_tag,
            filename=new_filename,
            few_shot_count=few_shot_count,
            is_active=False,  # Not active until promoted
            parent_version=base_version,
        )
        session.add(version)

    return new_tag


def rollback_version(version_tag: str) -> str:
    """
    Rollback to the parent version.

    Deactivates the given version and reactivates its parent.
    Returns the parent version tag.
    Raises ValueError if no parent exists.
    """
    with get_session() as session:
        current = session.query(PromptVersion).filter_by(version_tag=version_tag).first()
        if not current:
            raise ValueError(f"Version {version_tag} not found")

        if not current.parent_version:
            raise ValueError(f"Version {version_tag} has no parent version — cannot rollback")

        parent_tag = current.parent_version
        parent = session.query(PromptVersion).filter_by(version_tag=parent_tag).first()
        if not parent:
            raise ValueError(f"Parent version {parent_tag} not found in database")

        # Deactivate all, reactivate parent
        session.query(PromptVersion).update({"is_active": False})
        parent.is_active = True
        logger.info(f"Rolled back from {version_tag} to {parent_tag}")

    return parent_tag


def promote_version(version_tag: str) -> None:
    """Promote a version to active. Deactivates all others."""
    with get_session() as session:
        target = session.query(PromptVersion).filter_by(version_tag=version_tag).first()
        if not target:
            raise ValueError(f"Version {version_tag} not found")

        session.query(PromptVersion).update({"is_active": False})
        target.is_active = True
        logger.info(f"Promoted version {version_tag} to active")
