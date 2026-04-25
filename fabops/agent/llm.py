"""Minimal Gemini and Claude wrappers with token-cost tracking.

Spec Section 14.1: cost discipline. Every call returns both the text and an
estimated cost so the hard-switch budget logic can enforce caps.
"""
import os
from typing import Optional, Tuple

import google.generativeai as genai
from anthropic import Anthropic

from fabops.config import CLAUDE_JUDGE_MODEL, GEMINI_FLASH_MODEL, GEMINI_PRO_MODEL

# Rough token pricing (April 2026 approximate)
GEMINI_FLASH_PRICE_IN = 0.0  # free tier
GEMINI_FLASH_PRICE_OUT = 0.0
GEMINI_PRO_PRICE_IN = 0.0  # free tier
GEMINI_PRO_PRICE_OUT = 0.0
CLAUDE_HAIKU_PRICE_IN = 1.0 / 1_000_000  # $1 per MTok
CLAUDE_HAIKU_PRICE_OUT = 5.0 / 1_000_000  # $5 per MTok


def _gemini_client():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])


def gemini_flash(prompt: str, system: Optional[str] = None) -> Tuple[str, float]:
    """Fast routing / planner call. Returns (text, cost_usd)."""
    _gemini_client()
    model = genai.GenerativeModel(GEMINI_FLASH_MODEL, system_instruction=system)
    resp = model.generate_content(prompt)
    return resp.text, 0.0  # free tier


def gemini_pro(prompt: str, system: Optional[str] = None) -> Tuple[str, float]:
    """Diagnose / verify call. Returns (text, cost_usd)."""
    _gemini_client()
    model = genai.GenerativeModel(GEMINI_PRO_MODEL, system_instruction=system)
    resp = model.generate_content(prompt)
    return resp.text, 0.0


def claude_judge(prompt: str, system: Optional[str] = None) -> Tuple[str, float]:
    """Cross-family Claude Haiku judge. Returns (text, cost_usd)."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages = [{"role": "user", "content": prompt}]
    resp = client.messages.create(
        model=CLAUDE_JUDGE_MODEL,
        max_tokens=1024,
        system=system or "",
        messages=messages,
    )
    text = resp.content[0].text
    cost = (resp.usage.input_tokens * CLAUDE_HAIKU_PRICE_IN +
            resp.usage.output_tokens * CLAUDE_HAIKU_PRICE_OUT)
    return text, cost
