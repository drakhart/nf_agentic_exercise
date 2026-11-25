import asyncio
import inspect
import logging
import re
from time import perf_counter
from typing import Awaitable, Callable

from agents import run_change_historian, run_log_analyst, run_runbook_keeper
from agents.runbook_keeper import RunbookRecommendation
from orchestrator.correlation import correlate_findings
from orchestrator.models import IncidentReport
from orchestrator.report import build_report, ground_evidence
from orchestrator.stretch import CriticRejected, post_report, review_report
from project_paths import DATA_DIR
from run_metrics import RunMetrics, active_metrics, branch_deadline, remaining_time

INCIDENTS_DIR = DATA_DIR / "incidents"
logger = logging.getLogger(__name__)
Specialist = Callable[[dict[str, str]], str | Awaitable[str]]


class IncidentOrchestrator:
    def __init__(
        self,
        *,
        timeout: float | None = None,
        impact_specialist: Specialist | None = None,
        critic: bool = False,
        post_update: bool = False,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        self.impact_specialist = impact_specialist
        self.critic = critic
        self.post_update = post_update

    @staticmethod
    def read_incident(incident_id: str) -> str:
        if not re.fullmatch(r"INC-\d+", incident_id):
            raise ValueError(f"Invalid incident ID: {incident_id}")

        path = (INCIDENTS_DIR / f"{incident_id}.md").resolve()
        if not path.is_relative_to(INCIDENTS_DIR.resolve()):
            raise ValueError("Invalid incident report path")
        if not path.is_file():
            raise FileNotFoundError(f"Incident report not found: {incident_id}")
        return path.read_text(encoding="utf-8")

    async def _wait_for_specialist(self, work):
        if self.timeout is None:
            return await work

        time_left = remaining_time(self.timeout)
        if time_left <= 0:
            raise TimeoutError("specialist deadline exceeded")
        return await asyncio.wait_for(work, timeout=time_left)

    async def _run_specialist(
        self, name: str, specialist: Specialist, inputs: dict[str, str]
    ) -> str:
        try:
            work = (
                specialist(inputs)
                if inspect.iscoroutinefunction(specialist)
                else asyncio.to_thread(specialist, inputs)
            )
            result = await self._wait_for_specialist(work)
            if inspect.isawaitable(result):
                result = await self._wait_for_specialist(result)

            if result is None:
                return ""
            if not isinstance(result, str):
                raise TypeError(f"{name} returned {type(result).__name__}, expected str")
            return result
        except Exception as error:
            logger.warning(
                "%s branch failed (%s): %s",
                name,
                type(error).__name__,
                error,
                exc_info=True,
            )
            metrics = active_metrics.get()
            if metrics is not None:
                metrics.record_branch_failure(
                    name, f"{type(error).__name__}: {error}"
                )
            return ""

    async def _investigate(self, incident_id: str, incident_report: str) -> dict[str, str]:
        specialists: dict[str, Specialist] = {
            "Log Analyst": run_log_analyst,
            "Change Historian": run_change_historian,
        }
        if self.impact_specialist is not None:
            specialists["Impact Analyst"] = self.impact_specialist

        started = perf_counter()
        token = branch_deadline.set(
            started + self.timeout if self.timeout is not None else None
        )
        try:
            inputs = {"incident": incident_id, "incident_report": incident_report}
            names = list(specialists)
            results = await asyncio.gather(*(
                self._run_specialist(name, specialists[name], inputs.copy())
                for name in names
            ))
            return dict(zip(names, results))
        finally:
            branch_deadline.reset(token)
            metrics = active_metrics.get()
            if metrics is not None:
                metrics.record_stage("parallel_investigation", perf_counter() - started)

    async def _run_async(self, incident_id: str) -> IncidentReport:
        incident_report = self.read_incident(incident_id)
        findings = await self._investigate(incident_id, incident_report)
        logs = findings.get("Log Analyst", "")
        changes = findings.get("Change Historian", "")
        impact = findings.get("Impact Analyst", "")
        metrics = active_metrics.get()

        if metrics is not None:
            if metrics.missing_search_evidence("search_logs"):
                logs = ""
            if metrics.missing_search_evidence("search_changes"):
                changes = ""

        correlation = await correlate_findings(incident_report, logs, changes)
        ground_evidence(
            correlation,
            logs,
            changes,
            returned_sources=metrics.returned_sources() if metrics else None,
        )
        if not logs:
            correlation.open_questions.append(
                "What log evidence is missing from the Log Analyst investigation?"
            )
        if not changes:
            correlation.open_questions.append(
                "What change evidence is missing from the Change Historian investigation?"
            )
        if impact:
            correlation.open_questions.append(impact)
        if metrics is not None and metrics.has_denied_calls():
            correlation.open_questions.append(
                "What additional evidence could be checked after the tool-call budget is replenished?"
            )

        try:
            recommendation = await run_runbook_keeper(correlation.symptoms)
        except Exception as error:
            logger.exception("Runbook Keeper failed")
            if metrics is not None:
                metrics.record_branch_failure(
                    "Runbook Keeper", f"{type(error).__name__}: {error}"
                )
            recommendation = RunbookRecommendation(
                matched=None,
                why="The runbook specialist did not return a usable recommendation.",
                open_questions=["Which current runbook applies to the confirmed symptoms?"],
            )

        report = build_report(incident_id, correlation, recommendation, metrics)
        await self._run_optional_checks(report, metrics)
        return report

    async def _run_optional_checks(
        self, report: IncidentReport, metrics: RunMetrics | None
    ) -> None:
        review_passed = not self.critic
        if self.critic:
            if metrics is None:
                report.open_questions.append(
                    "The stakeholder update was not posted because evidence review had no source metrics."
                )
            else:
                try:
                    await review_report(report, metrics)
                    review_passed = True
                except CriticRejected as error:
                    report.open_questions.append(str(error))
                except Exception as error:
                    logger.exception("Evidence review failed")
                    report.open_questions.append(
                        "The stakeholder update was not posted because evidence review "
                        f"could not be completed ({type(error).__name__})."
                    )

        # Posting is consitional, an enabled critic must approve the report first
        if self.post_update and review_passed:
            await post_report(report, metrics)

    def run(self, incident_id: str, *, metrics: RunMetrics | None = None) -> IncidentReport:
        """Run an investigation from synchronous application code."""
        run = metrics if metrics is not None else RunMetrics()
        token = active_metrics.set(run)
        try:
            return asyncio.run(self._run_async(incident_id))
        finally:
            active_metrics.reset(token)
