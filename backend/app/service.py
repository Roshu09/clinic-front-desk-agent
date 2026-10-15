"""Wiring: builds the agent with the optional LLM extractor, driven by environment variables."""
from __future__ import annotations

import os
from typing import Optional

from .agent import Extractor


def build_extractor() -> Optional[Extractor]:
    """LLM extraction is optional. With no LLM_API_KEY the agent runs rules-only and fully offline."""
    if not os.environ.get("LLM_API_KEY"):
        return None
    from .nlu_llm import LLMExtractor
    return LLMExtractor.from_env()
