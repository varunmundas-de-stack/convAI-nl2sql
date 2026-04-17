"""
Versioned Prompt Manager.

- Load prompt files by version tag
- List available versions with DB metadata
- Resolve A/B version for a session
- Inject few-shot examples into prompts
"""

import logging
from pathlib import Path
from typing import Optional

from app.rlhf.db import get_session
from app.rlhf.models import PromptVersion, ABTestConfig

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def get_active_prompt(version: str) -> str:
    """
    Read prompt file for a given version tag (e.g. "v1").

    Falls back to intent_extraction.txt if versioned file not found.
    """
    filename = f"intent_extraction_{version}.txt"
    filepath = PROMPTS_DIR / filename

    if not filepath.exists():
        logger.warning(f"Versioned prompt {filename} not found, falling back to default")
        filepath = PROMPTS_DIR / "intent_extraction.txt"

    if not filepath.exists():
        raise FileNotFoundError(f"Prompt file not found: {filepath}")

    return filepath.read_text(encoding="utf-8")


def list_versions() -> list[dict]:
    """List all prompt versions from the database with metadata."""
    with get_session() as session:
        versions = session.query(PromptVersion).order_by(PromptVersion.created_at.desc()).all()
        return [
            {
                "version_tag": v.version_tag,
                "filename": v.filename,
                "few_shot_count": v.few_shot_count,
                "is_active": v.is_active,
                "parent_version": v.parent_version,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ]


def get_active_version_tag() -> str:
    """Get the currently active prompt version tag. Defaults to 'v1'."""
    with get_session() as session:
        active = session.query(PromptVersion).filter_by(is_active=True).first()
        return active.version_tag if active else "v1"


def get_ab_version(session_id: str) -> tuple[str, str]:
    """
    Resolve prompt version via A/B config for a session.

    Returns (version_tag, ab_group) tuple.
    If no A/B test is active, returns (active_version, None).
    """
    from app.rlhf.ab_router import assign_ab_group, get_prompt_version_for_group

    with get_session() as session:
        config = session.query(ABTestConfig).filter_by(is_active=True).first()

    if not config:
        return get_active_version_tag(), None

    group = assign_ab_group(session_id)
    version = get_prompt_version_for_group(group)
    return version, group


def inject_few_shots(prompt: str, examples: list[dict]) -> str:
    """
    Append top-rated Q&A pairs as few-shot examples to the prompt.

    Each example dict should have 'query' and 'response' keys.
    Examples are inserted before the final user query section.
    """
    if not examples:
        return prompt

    few_shot_block = "\n\n## FEW-SHOT EXAMPLES (top-rated responses)\n"
    for i, ex in enumerate(examples, 1):
        few_shot_block += f"\n### Example {i}\n"
        few_shot_block += f"User Query: {ex.get('query', '')}\n"
        few_shot_block += f"Expected Response: {ex.get('response', '')}\n"

    # Insert before the {query} placeholder if it exists, otherwise append
    if "{query}" in prompt:
        prompt = prompt.replace("{query}", few_shot_block + "\n{query}")
    else:
        prompt += few_shot_block

    return prompt


def ensure_v1_registered():
    """Ensure v1 is registered in the database. Called at startup."""
    with get_session() as session:
        existing = session.query(PromptVersion).filter_by(version_tag="v1").first()
        if not existing:
            v1 = PromptVersion(
                version_tag="v1",
                filename="intent_extraction_v1.txt",
                few_shot_count=0,
                is_active=True,
                parent_version=None,
            )
            session.add(v1)
            logger.info("Registered v1 as the baseline prompt version")
