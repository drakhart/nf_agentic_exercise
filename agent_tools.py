from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from run_metrics import RunMetrics, remaining_time

logger = logging.getLogger(__name__)
RUNBOOK_FETCH_LIMIT = 100


def _log_timestamp(entry: BaseModel) -> datetime:
    """Parse the ISO-8601 timestamp at the start of a log line."""
    raw = str(getattr(entry, "text", "")).split(maxsplit=1)
    if not raw:
        return datetime.max.replace(tzinfo=timezone.utc)
    try:
        value = datetime.fromisoformat(raw[0].replace("Z", "+00:00"))
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)


def _prepare_result(tool_name: str, result: object, requested_limit: int | None):
    """Filter and order tool results without changing the source tool."""
    if not isinstance(result, BaseModel) or not hasattr(result, "results"):
        return result

    original_entries = list(result.results)
    entries = original_entries

    if tool_name == "search_runbook":
        entries = [
            entry for entry in entries
            if not str(getattr(entry, "source", "")).startswith("_archive/")
        ]
    elif tool_name == "search_logs":
        entries = sorted(entries, key=_log_timestamp)

    if requested_limit is not None:
        entries = entries[:requested_limit]

    removed = len(entries) < len(original_entries)
    updates = {
        "results": entries,
        "returned": len(entries),
        "total_matches": getattr(result, "total_matches", len(original_entries)),
        "truncated": bool(getattr(result, "truncated", False) or removed),
    }
    return result.model_copy(update=updates)


class MeteredTool(BaseTool):
    """Apply per-run limits before delegating to a project tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    delegate: BaseTool
    metrics: RunMetrics | None = None
    name: str
    description: str
    args_schema: Type[BaseModel]

    def _run(self, **kwargs) -> str:
        if remaining_time(180) <= 0:
            return json.dumps({"error": "The incident investigation deadline expired."})

        requested_limit = kwargs.get("max_results")
        if requested_limit is not None:
            if not isinstance(requested_limit, int) or isinstance(requested_limit, bool):
                return json.dumps({"error": "max_results must be an integer."})
            if requested_limit < 1:
                return json.dumps({"error": "max_results must be at least 1."})

        if self.metrics is not None and not self.metrics.claim(self.name):
            return json.dumps({"error": "The tool-call budget has been exhausted."})

        call_args = dict(kwargs)
        if self.name == "search_runbook":
            call_args["max_results"] = max(requested_limit or 0, RUNBOOK_FETCH_LIMIT)

        try:
            result = self.delegate.run(**call_args)
            result = _prepare_result(self.name, result, requested_limit)
        except Exception as error:
            logger.exception("Tool %s failed", self.name)
            return json.dumps({"error": f"{self.name} failed: {type(error).__name__}"})

        if isinstance(result, BaseModel):
            payload = result.model_dump()
            if self.metrics is not None and "results" in payload:
                self.metrics.record_search(self.name, payload)
            return result.model_dump_json()

        return str(result)


def meter_tool(tool: BaseTool, metrics: RunMetrics | None) -> MeteredTool:
    return MeteredTool(
        delegate=tool,
        metrics=metrics,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )
