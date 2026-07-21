"""
Shared Gemini / Vertex AI client factory.
=========================================
Centralises construction of the Gemini client so all LLM call sites share
one authentication path (Google Application Default Credentials — no API key).
Project/location come from the environment (.env → GOOGLE_CLOUD_PROJECT /
GOOGLE_CLOUD_LOCATION).
"""

import json
import os
from typing import Optional, Union

from google import genai

from src.core.dev_config import get_param


def get_gemini_client() -> "genai.Client":
    """Return a Vertex AI-backed Gemini client using ADC."""
    return genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
    )


def call_gemini_json(contents: Union[str, list], model: Optional[str] = None) -> dict:
    """Call Gemini and parse its response as a raw JSON object.

    `contents` is passed straight through to `generate_content` — a plain
    text prompt (str) or a multimodal list of `types.Part`s. Strips markdown
    code fences if present, parses the result, and validates it's a dict.

    Raises ValueError/json.JSONDecodeError on any failure (empty response,
    non-dict JSON, malformed JSON) — callers apply their own fallback.
    """
    client = get_gemini_client()
    response = client.models.generate_content(
        model=model or get_param("GEMINI_MODEL"),
        contents=contents,
    )
    raw = (response.text or "").strip()
    if not raw:
        raise ValueError("LLM returned an empty response.")

    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM returned unexpected type: {type(parsed).__name__}")
    return parsed
