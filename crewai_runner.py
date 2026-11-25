"""Helpers for creating agents and running focused CrewAI tasks."""

from time import perf_counter
from typing import TypeVar

from crewai import Agent, Crew, Process, Task
from pydantic import BaseModel

from agent_tools import meter_tool
from crewai_config import build_llm
from run_metrics import active_metrics

ModelT = TypeVar("ModelT", bound=BaseModel)


def make_agent(
    *,
    role: str,
    goal: str,
    backstory: str,
    tools: list | None = None,
) -> Agent:
    metrics = active_metrics.get()
    sdk_tools = [meter_tool(tool, metrics) for tool in (tools or [])]
    # CopilotLLM registers these tools with the SDK and applies metering
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        tools=[],
        llm=build_llm(tools=sdk_tools),
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )


async def run_task(
    *,
    agent: Agent,
    description: str,
    expected_output: str,
    inputs: dict,
    response_model: type[ModelT] | None = None,
    stage: str,
) -> str | ModelT:
    task = Task(
        description=description,
        expected_output=expected_output,
        agent=agent,
        output_pydantic=response_model,
    )
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
        tracing=False,
    )

    started = perf_counter()
    metrics = active_metrics.get()
    try:
        result = await crew.akickoff(inputs=inputs)
    finally:
        if metrics is not None:
            metrics.record_stage(stage, perf_counter() - started)

    if metrics is not None:
        usage = getattr(result, "token_usage", None)
        if usage is not None:
            if hasattr(usage, "model_dump"):
                usage = usage.model_dump()
            elif not isinstance(usage, dict):
                usage = getattr(usage, "__dict__", {})
            metrics.record_usage({"stage": stage, **usage})

    raw = getattr(result, "raw", None)
    if response_model is None:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"CrewAI task {stage!r} returned no text.")
        return raw.strip()

    parsed = getattr(result, "pydantic", None)
    if isinstance(parsed, response_model):
        return parsed
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"CrewAI task {stage!r} did not return structured output.")
    return response_model.model_validate_json(raw)
