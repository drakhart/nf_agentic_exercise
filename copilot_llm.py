"""CrewAI LLM adapter for GitHub Copilot SDK sessions."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from crewai import BaseLLM
from pydantic import BaseModel, PrivateAttr

from copilot import CopilotClient, RuntimeConnection, ToolSet, define_tool

from agent_tools import MeteredTool
from tools.search_changes_tool import SearchChangesTool
from tools.search_logs_tool import SearchLogsTool
from tools.search_runbook_tool import SearchRunbookTool

logger = logging.getLogger(__name__)


class CopilotLLM(BaseLLM):
    """A synchronous/asynchronous CrewAI LLM adapter using GitHub Copilot."""

    model: str = "claude-sonnet-5.5"
    _project_tools: list[Any] = PrivateAttr(default_factory=list)

    def __init__(self, *, tools: list[Any] | None = None, model: str | None = None, **kwargs: Any):
        super().__init__(model=model or "claude-sonnet-5.5", **kwargs)
        self._project_tools = list(tools or [])

    def supports_function_calling(self) -> bool:
        return False

    @staticmethod
    def _messages_to_prompt(messages: str | list[Any]) -> str:
        if isinstance(messages, str):
            return messages
        parts: list[str] = []
        for message in messages:
            if isinstance(message, dict):
                role = str(message.get("role", "user")).upper()
                content = message.get("content", "")
            else:
                role = str(getattr(message, "role", "user")).upper()
                content = getattr(message, "content", "")
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False, default=str)
            if content:
                parts.append(f"{role}: {content}")
        return "\n\n".join(parts)

    def _sdk_tools(self) -> list[Any]:
        definitions = []
        for project_tool in self._project_tools:
            schema = project_tool.args_schema
            tool_name = str(project_tool.name)
            tool_description = str(project_tool.description)

            def make_handler(tool: Any, params_model: type[BaseModel], name: str):
                async def invoke(params: BaseModel) -> Any:
                    logger.info("Tool call (%s)", name)
                    result = tool.run(**params.model_dump())
                    if isinstance(result, BaseModel):
                        result = result.model_dump(mode="json")
                    elif result is not None and not isinstance(result, (dict, list, str, int, float, bool)):
                        result = str(result)
                    return result

                invoke.__name__ = name
                invoke.__annotations__ = {"params": params_model, "return": Any}
                return invoke

            handler = make_handler(project_tool, schema, tool_name)
            delegate = project_tool.delegate if isinstance(project_tool, MeteredTool) else project_tool
            definitions.append(define_tool(
                description=tool_description,
                skip_permission=isinstance(delegate, (SearchLogsTool, SearchChangesTool, SearchRunbookTool)),
            )(handler))
        return definitions

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        """Remove an optional Markdown fence around model-produced JSON."""
        text = content.strip()
        if not text.startswith("```"):
            return text

        _opening, separator, remainder = text.partition("\n")
        if not separator:
            return text
        if remainder.rstrip().endswith("```"):
            remainder = remainder.rstrip()[:-3]
        return remainder.strip()

    @staticmethod
    def _structured_prompt(prompt: str, response_model: type[BaseModel] | None) -> str:
        if response_model is None:
            return prompt
        schema = response_model.model_json_schema()
        return (
            f"{prompt}\n\nReturn only valid JSON matching this JSON Schema. "
            "Do not include markdown fences or explanatory text.\n"
            f"JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
        )

    async def _acall_copilot(
        self,
        messages: str | list[Any],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        prompt = self._structured_prompt(self._messages_to_prompt(messages), response_model)
        copilot_home = Path(os.environ.get("COPILOT_HOME") or "~/.copilot").expanduser().absolute()
        runtime = RuntimeConnection.for_default(base_directory=str(copilot_home))
        tool_definitions = self._sdk_tools()
        available_tools = ToolSet()
        for definition in tool_definitions:
            available_tools.add_custom(definition.name)
        async with CopilotClient(mode="empty", runtime=runtime) as client:
            async with await client.create_session(
                model=self.model,
                tools={"definitions": tool_definitions, "available_tools": available_tools},
            ) as session:
                logger.info("Model call (%s)", self.model)
                response = await session.send_and_wait(prompt)

        content = getattr(getattr(response, "data", None), "content", None)
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("GitHub Copilot returned an empty response.")
        if response_model is not None:
            return response_model.model_validate_json(
                self._strip_code_fence(content)
            )
        return content.strip()

    def call(
        self,
        messages: str | list[Any],
        tools: list[dict[str, Any]] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> str | BaseModel:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._acall_copilot(messages, response_model))
        raise RuntimeError(
            "CopilotLLM.call() cannot run inside an active event loop; use CrewAI's async kickoff."
        )

    async def acall(
        self,
        messages: str | list[Any],
        tools: list[dict[str, Any]] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> str | BaseModel:
        return await self._acall_copilot(messages, response_model)
