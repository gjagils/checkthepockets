"""One place for Claude calls that return JSON (rule suggestions, recurring patterns, savings analysis).

Replaces four copies of the same client setup, model name, markdown-fence stripping and parsing in
ai_suggest.py. The model comes from config (`ANTHROPIC_MODEL`), every call has a timeout, and callers
treat any exception as "no suggestion" exactly as before.
"""
import json
import logging

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60


class AIUnavailable(Exception):
    """No API key configured."""


def strip_json_fences(text: str) -> str:
    """Remove an optional ```json ... ``` wrapper around a model answer."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


def call_json(prompt: str, *, max_tokens: int):
    """Send one user prompt and return the parsed JSON answer (dict or list).

    Raises AIUnavailable without an API key; any API or JSON error propagates to the caller.
    """
    if not ANTHROPIC_API_KEY:
        raise AIUnavailable("ANTHROPIC_API_KEY is not set")
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=TIMEOUT_SECONDS)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(strip_json_fences(response.content[0].text))
