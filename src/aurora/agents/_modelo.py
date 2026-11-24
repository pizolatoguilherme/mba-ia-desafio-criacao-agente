"""Modelo Gemini compartilhado pelos agentes, com retry para limites de taxa (429)."""

from __future__ import annotations

from google.adk.models.google_llm import Gemini
from google.genai import types

from .. import config


def modelo() -> Gemini:
    return Gemini(
        model=config.GEMINI_MODEL,
        retry_options=types.HttpRetryOptions(
            attempts=6, initial_delay=2.0, max_delay=30.0, exp_base=2.0,
            http_status_codes=[429, 500, 502, 503, 504],
        ),
    )
