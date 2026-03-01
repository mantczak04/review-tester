"""LLM client – sends code review prompts to Google Gemini."""

import json
import re

from google import genai

AVAILABLE_MODELS = [
    "gemini-flash-latest",
    "gemini-3.1-pro-preview"
]


def run_review(prompt: str, diff_payload: str, model: str, api_key: str = "") -> dict:
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

    client = genai.Client(api_key=api_key or None)  # api_key=None falls back to GEMINI_API_KEY env var
    response = client.models.generate_content(model=model, contents=full_prompt)

    text = response.text.strip()

    # Strip markdown code fences if present (```json ... ```)
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    return json.loads(text)
