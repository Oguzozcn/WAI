"""
Shared Gemini / Vertex AI client factory.
=========================================
Centralises construction of the Gemini client so all LLM call sites share
one authentication path (Google Application Default Credentials — no API key).
Project/location come from the environment (.env → GOOGLE_CLOUD_PROJECT /
GOOGLE_CLOUD_LOCATION).
"""

import os

from google import genai


def get_gemini_client() -> "genai.Client":
    """Return a Vertex AI-backed Gemini client using ADC."""
    return genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
    )
