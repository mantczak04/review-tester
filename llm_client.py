"""LLM client – sends code review prompts to Google Gemini."""

import json
import re

from google import genai

AVAILABLE_MODELS = [
    "gemini-flash-latest",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash-lite",
]


def run_review(prompt: str, diff_payload: str, model: str) -> dict:
    """Send the master prompt (with diff inserted) to Gemini and return parsed JSON.

    The prompt must contain a ``{DIFF}`` placeholder that will be replaced with
    *diff_payload*.

    Returns a dict like::

        {
            "comments": [{"file": ..., "line": ..., "type": ..., "comment": ...}, ...],
            "summary": "..."
        }
    """
    full_prompt = prompt.replace("{DIFF}", diff_payload)

    client = genai.Client()  # reads GEMINI_API_KEY from env
    response = client.models.generate_content(model=model, contents=full_prompt)

    text = response.text.strip()

    # Strip markdown code fences if present (```json ... ```)
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    return json.loads(text)
