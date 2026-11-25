import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from threading import Event
from time import perf_counter
from unittest.mock import patch

from dotenv import load_dotenv

from orchestrator import IncidentOrchestrator, IncidentReport
from project_paths import ENV_FILE, OUTPUT_DIR
from run_metrics import RunMetrics
from tools.search_changes_tool import SearchChangesError
from tools.search_logs_tool import SearchLogsOutput

CASES = ENV_FILE.with_name("eval_cases.json")
FAULTS = (
    "branch-error",
    "branch-timeout",
    "missing-changes",
    "empty-logs",
    "three-calls-total",
    "three-calls-per-specialist",
)
CHANGE_HISTORIAN = "orchestrator.incident_orchestrator.run_change_historian"


def timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace(" UTC", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def grade(report: IncidentReport, case: dict, metrics: RunMetrics) -> dict[str, bool]:
    cause = report.root_cause
    returned = metrics.returned_sources()
    valid_evidence = set(cause.evidence) & returned.keys()
    starts = {timestamp(value) for value in case["starts"]}
    starts.discard(None)

    if report.runbook.matched is None:
        has_steps = bool(report.actions) and all(
            action.source == "RB-000" for action in report.actions
        )
    else:
        has_steps = bool(report.runbook.remediation)

    log_evidence = valid_evidence.intersection(case["log_evidence"])
    change_evidence = valid_evidence.intersection(case["change_evidence"])

    return {
        "root_cause": all(
            re.search(pattern, cause.statement, re.IGNORECASE)
            for pattern in case["cause"]
        ),
        "start_time": any(
            timestamp(event.time) in starts
            and bool(set(event.evidence) & set(case["log_evidence"]) & returned.keys())
            for event in report.timeline
        ),
        "log_evidence": bool(log_evidence),
        "change_evidence": bool(change_evidence),
        "correlation": bool(log_evidence and change_evidence)
        and bool(cause.correlation.strip())
        and cause.confidence in {"high", "medium"},
        "reporter_theory_ruled_out": any(
            re.search(case["rejected_theory"], item.theory, re.IGNORECASE)
            and any(citation in returned for citation in item.evidence)
            for item in report.ruled_out
        ),
        "runbook": report.runbook.matched == case["runbook"] and has_steps,
    }


def grade_fault(
    scenario: str, report: IncidentReport, metrics: RunMetrics
) -> dict[str, bool]:
    """Check the behaviour expected from each injected failure."""
    calls = metrics.tool_calls
    failures = metrics.snapshot()["branch_failures"]
    unresolved = (
        report.root_cause.confidence == "low"
        and "unresolved" in report.root_cause.statement.lower()
    )
    degraded = unresolved and bool(report.open_questions)

    if scenario == "branch-error":
        return {
            "failed_branch_recorded": "Change Historian" in failures,
            "other_specialist_ran": calls["search_logs"] > 0,
            "partial_result_returned": degraded,
        }
    if scenario == "branch-timeout":
        timed_out = any(
            "timeout" in reason.lower() for reason in failures.values()
        )
        return {
            "timeout_recorded": timed_out,
            "parallel_phase_completed": "parallel_investigation" in metrics.stage_seconds,
            "report_returned_with_uncertainty": bool(report.open_questions),
        }
    if scenario == "missing-changes":
        return {
            "change_search_was_attempted": calls["search_changes"] > 0,
            "change_evidence_unavailable": metrics.missing_search_evidence("search_changes"),
            "log_search_still_returned_evidence": calls["search_logs"] > 0
            and not metrics.missing_search_evidence("search_logs"),
            "cause_not_invented": degraded,
        }
    if scenario == "empty-logs":
        return {
            "log_search_was_attempted": calls["search_logs"] > 0,
            "log_evidence_empty": metrics.missing_search_evidence("search_logs"),
            "change_search_still_returned_evidence": calls["search_changes"] > 0
            and not metrics.missing_search_evidence("search_changes"),
            "timeline_not_invented": not report.timeline and degraded,
        }
    if scenario == "three-calls-total":
        return {
            "total_budget_respected": calls.total() <= 3,
            "budget_exhaustion_reported": bool(metrics.denied_calls),
            "degrades_gracefully": bool(report.open_questions) or unresolved,
        }
    if scenario == "three-calls-per-specialist":
        specialist_calls = (
            calls["search_logs"],
            calls["search_changes"],
            calls["search_runbook"],
        )
        return {
            "each_specialist_budget_respected": all(count <= 3 for count in specialist_calls),
            "degrades_gracefully": bool(report.open_questions) or unresolved,
        }
    raise ValueError(f"Unknown fault scenario: {scenario}")


async def _run_scenario_async(
    incident_id: str,
    scenario: str,
    metrics: RunMetrics,
) -> IncidentReport:
    orchestrator = IncidentOrchestrator()

    if scenario == "branch-error":
        with patch(CHANGE_HISTORIAN, side_effect=RuntimeError("injected specialist error")):
            return await asyncio.to_thread(orchestrator.run, incident_id, metrics=metrics)

    if scenario == "branch-timeout":
        release = Event()

        async def slow_specialist(_inputs):
            await asyncio.to_thread(release.wait, 180)
            return ""

        try:
            with patch(CHANGE_HISTORIAN, side_effect=slow_specialist):
                timed = IncidentOrchestrator(timeout=0.1)
                return await asyncio.to_thread(timed.run, incident_id, metrics=metrics)
        finally:
            release.set()

    if scenario == "missing-changes":
        error = SearchChangesError(error="change log unavailable")
        with patch("tools.search_changes_tool.SearchChangesTool._run", return_value=error):
            return await asyncio.to_thread(orchestrator.run, incident_id, metrics=metrics)

    if scenario == "empty-logs":
        def empty_logs(query, **_kwargs):
            return SearchLogsOutput(
                query=query,
                total_matches=0,
                returned=0,
                truncated=False,
                results=[],
            )

        with patch("tools.search_logs_tool.SearchLogsTool._run", side_effect=empty_logs):
            return await asyncio.to_thread(orchestrator.run, incident_id, metrics=metrics)

    return await asyncio.to_thread(orchestrator.run, incident_id, metrics=metrics)


def _run_scenario(incident_id: str, scenario: str, metrics: RunMetrics) -> IncidentReport:
    return asyncio.run(_run_scenario_async(incident_id, scenario, metrics))


def run_attempt(incident_id: str, case: dict, scenario: str, attempt: int) -> dict:
    metrics = RunMetrics(
        tool_budget=3 if scenario == "three-calls-total" else None,
        per_tool_budget=3 if scenario == "three-calls-per-specialist" else None,
    )
    started = perf_counter()
    record = {
        "incident_id": incident_id,
        "scenario": scenario,
        "attempt": attempt,
        "holdout": case["holdout"],
    }

    try:
        report = _run_scenario(incident_id, scenario, metrics)
        checks = (
            grade_fault(scenario, report, metrics)
            if scenario in FAULTS
            else grade(report, case, metrics)
        )
        record.update(properties=checks, report=report.model_dump())
    except Exception as error:
        record.update(properties={"completed": False}, error=f"{type(error).__name__}: {error}")

    snapshot = metrics.snapshot()
    costs = [event.get("cost") for event in snapshot["usage"]]
    record["passed"] = all(record["properties"].values())
    record["seconds"] = perf_counter() - started
    record["stage_seconds"] = snapshot["stage_seconds"]
    record["branch_failures"] = snapshot["branch_failures"]
    record["tool_calls"] = snapshot["tool_calls"]
    record["denied_calls"] = snapshot["denied_calls"]
    record["usage"] = snapshot["usage"]
    numeric_costs = [value for value in costs if isinstance(value, (int, float))]
    record["reported_cost"] = (
        sum(numeric_costs)
        if costs and len(numeric_costs) == len(costs)
        else None
    )
    return record


def main() -> int:
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(
        description="Run repeated CrewAI incident evaluations and record each attempt."
    )
    parser.add_argument("--runs", type=int)
    parser.add_argument("--split", choices=("all", "training", "holdout"), default="all")
    parser.add_argument("--golden", action="store_true", help="Run only INC-2043, ten times by default.")
    parser.add_argument(
        "--faults",
        action="store_true",
        help="Add specialist failure, timeout, missing-evidence and tool-budget experiments.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "evals.jsonl")
    args = parser.parse_args()

    runs = args.runs if args.runs is not None else (10 if args.golden else 5)
    if runs < 1:
        parser.error("--runs must be positive")

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    selected = []
    for incident_id, case in cases.items():
        if args.golden and incident_id != "INC-2043":
            continue
        split = "holdout" if case["holdout"] else "training"
        if args.split == "all" or args.split == split:
            selected.append((incident_id, "baseline"))

    if args.faults and args.split != "holdout":
        selected.extend(("INC-2043", scenario) for scenario in FAULTS)
    if not selected:
        parser.error("no cases selected")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    passed = 0
    totals = defaultdict(Counter)

    with args.output.open("a", encoding="utf-8") as output:
        for incident_id, scenario in selected:
            for attempt in range(1, runs + 1):
                record = run_attempt(incident_id, cases[incident_id], scenario, attempt)
                output.write(json.dumps(record) + "\n")
                output.flush()
                passed += record["passed"]
                tally = totals[f"{incident_id}/{scenario}"]
                tally["passed"] += record["passed"]
                for name, success in record["properties"].items():
                    tally[name] += success
                print(
                    json.dumps({key: value for key, value in record.items() if key != "report"}),
                    flush=True,
                )

    print(
        json.dumps({"runs_per_case": runs, "passed_by_case_and_property": totals}),
        file=sys.stderr,
    )
    return int(passed != runs * len(selected))


if __name__ == "__main__":
    raise SystemExit(main())
