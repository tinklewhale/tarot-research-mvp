"""Claude API backend for the JSON-returning LLM calls in this project.

Selected by ``LLM_PROVIDER=anthropic`` (see ``llm_client.py``). Uses the official ``anthropic`` SDK.

Environment:
    ANTHROPIC_API_KEY   required
    ANTHROPIC_MODEL     default "claude-opus-5-5"
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

import anthropic


DEFAULT_MODEL = "claude-opus-5-5"
_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=3)
    return _client


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model response contained no JSON object")
    return json.loads(text[start : end + 1])


def call_claude_json(system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Optional[Dict[str, Any]]:
    """Ask Claude for a JSON object. Returns None when no API key is configured."""
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return None
    model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    response = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt + "\n\n응답은 설명 없이 JSON 객체 하나만 출력한다.",
        messages=[{"role": "user", "content": user_prompt}],
        # Server-side refusal fallback: if a safety classifier declines, the API re-runs on a fallback model.
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise RuntimeError(f"claude refused the request ({getattr(details, 'category', None)})")
    text = "".join(block.text for block in response.content if block.type == "text")
    return _extract_json(text)
