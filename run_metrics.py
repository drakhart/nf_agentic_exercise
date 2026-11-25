from collections import Counter
from copy import deepcopy
from contextvars import ContextVar
from threading import Lock
from time import perf_counter
from typing import Any


class RunMetrics:
    """Collect measurements and tool evidence for one incident run."""

    def __init__(self, tool_budget: int | None = None, per_tool_budget: int | None = None):
        for name, value in (("tool_budget", tool_budget), ("per_tool_budget", per_tool_budget)):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be nonnegative")

        self.tool_budget = tool_budget
        self.per_tool_budget = per_tool_budget
        self.tool_calls: Counter[str] = Counter()
        self.denied_calls: Counter[str] = Counter()
        self.usage: list[dict[str, Any]] = []
        self.stage_seconds: dict[str, float] = {}
        self.branch_failures: dict[str, str] = {}
        self.search_results: list[tuple[str, dict[str, Any]]] = []
        self._lock = Lock()

    def claim(self, tool: str) -> bool:
        """Reserve a call before invoking a tool; safe across parallel branches."""
        with self._lock:
            over_total = (
                self.tool_budget is not None
                and self.tool_calls.total() >= self.tool_budget
            )
            over_tool = (
                self.per_tool_budget is not None
                and self.tool_calls[tool] >= self.per_tool_budget
            )
            if over_total or over_tool:
                self.denied_calls[tool] += 1
                return False
            self.tool_calls[tool] += 1
            return True

    def was_denied_without_call(self, tool: str) -> bool:
        with self._lock:
            return self.denied_calls[tool] > 0 and self.tool_calls[tool] == 0

    def has_denied_calls(self) -> bool:
        with self._lock:
            return bool(self.denied_calls)

    def record_search(self, tool: str, result: dict) -> None:
        with self._lock:
            self.search_results.append((tool, deepcopy(result)))

    def record_usage(self, event: dict) -> None:
        with self._lock:
            self.usage.append(deepcopy(event))

    def record_stage(self, name: str, seconds: float) -> None:
        with self._lock:
            self.stage_seconds[name] = max(0.0, seconds)

    def record_branch_failure(self, name: str, reason: str) -> None:
        with self._lock:
            self.branch_failures[name] = reason

    def missing_search_evidence(self, tool: str) -> bool:
        with self._lock:
            if not (self.tool_budget is not None or self.per_tool_budget is not None):
                return self.tool_calls[tool] > 0 and not self._has_results(tool)
            return not self._has_results(tool)

    def _has_results(self, tool: str) -> bool:
        return any(
            name == tool and result.get("results")
            for name, result in self.search_results
        )

    def returned_sources(self) -> dict[str, dict]:
        with self._lock:
            searches = list(self.search_results)

        sources: dict[str, dict] = {}
        for tool, result in searches:
            for entry in result.get("results", []):
                if tool == "search_logs":
                    filename, line = entry.get("file"), entry.get("line")
                    if not filename or not isinstance(line, int):
                        continue
                    citation = f"{filename}:{line}"
                else:
                    citation = entry.get("id")
                    if not citation:
                        continue
                sources[citation] = dict(entry)
        return sources

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "tool_calls": dict(self.tool_calls),
                "denied_calls": dict(self.denied_calls),
                "usage": deepcopy(self.usage),
                "stage_seconds": dict(self.stage_seconds),
                "branch_failures": dict(self.branch_failures),
            }


active_metrics: ContextVar[RunMetrics | None] = ContextVar("active_metrics", default=None)
branch_deadline: ContextVar[float | None] = ContextVar("branch_deadline", default=None)


def remaining_time(maximum: float) -> float:
    deadline = branch_deadline.get()
    if deadline is None:
        return maximum
    return max(0.0, min(maximum, deadline - perf_counter()))
