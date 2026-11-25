"""Configuration for the model used by CrewAI agents."""

import os

from copilot_llm import CopilotLLM

DEFAULT_MODEL = "claude-sonnet-5.5"


def build_llm(tools: list | None = None) -> CopilotLLM:
    """Build the Copilot-backed CrewAI LLM.

    Authentication is provided by the GitHub Copilot CLI sign-in; no provider
    API key is required. COPILOT_MODEL can override the default model ID.
    """
    return CopilotLLM(model=os.getenv("COPILOT_MODEL", DEFAULT_MODEL), tools=tools)
