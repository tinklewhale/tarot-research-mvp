"""Provider-agnostic "give me a JSON object" LLM call shared by the pipeline and the transcript analyzer.

Provider selection (``LLM_PROVIDER``):
    openai      OpenAI chat completions (``OPENAI_API_KEY``, ``OPENAI_MODEL``, default gpt-4.1-mini)
    anthropic   Claude API via ``llm_anthropic.py`` (``ANTHROPIC_API_KEY``, ``ANTHROPIC_MODEL``)
    (unset)     openai if OPENAI_API_KEY is set, else anthropic if ANTHROPIC_API_KEY is set, else none

``call_llm_json`` returns None when no provider is configured so callers can fall back to heuristics.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests


def active_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider in {"openai", "anthropic"}:
        return provider
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    return ""


def active_model() -> str:
    provider = active_provider()
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5").strip()
    return ""


def _call_openai_json(system_prompt: str, user_prompt: str, max_tokens: int) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    if response.status_code >= 400:
        # Surface the API's own reason (e.g. billing_not_active) instead of a bare status code.
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = response.text[:200]
        raise requests.HTTPError(f"{response.status_code} {detail}".strip(), response=response)
    return json.loads(response.json()["choices"][0]["message"]["content"])


def call_llm_json(system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Optional[Dict[str, Any]]:
    provider = active_provider()
    if provider == "openai":
        return _call_openai_json(system_prompt, user_prompt, max_tokens)
    if provider == "anthropic":
        from llm_anthropic import call_claude_json

        return call_claude_json(system_prompt, user_prompt, max_tokens=max_tokens)
    return None
