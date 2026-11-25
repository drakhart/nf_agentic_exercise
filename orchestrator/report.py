import re

from agents.runbook_keeper import RunbookRecommendation
from orchestrator.models import Action, CorrelationResult, IncidentReport, RootCause, Runbook
from run_metrics import RunMetrics
from tools.search_runbook_tool import SearchRunbookOutput, SearchRunbookTool

LOG_CITATION = re.compile(r"\b[\w.-]+\.log:\d+\b")
CHANGE_CITATION = re.compile(r"\bCHG-\d+\b")
FALLBACK_RUNBOOK_ID = "RB-000"

def _fallback_actions(metrics: RunMetrics | None) -> list[str]:
    if metrics is not None and not metrics.claim("search_runbook"):
        return []

    result = SearchRunbookTool().run(query="partially matching entry")
    if not isinstance(result, SearchRunbookOutput):
        return []

    if metrics is not None:
        payload = result.model_dump()
        payload["results"] = [
            entry for entry in payload["results"]
            if not entry["source"].startswith("_archive/")
        ]
        metrics.record_search("search_runbook", payload)

    for entry in result.results:
        if entry.id != FALLBACK_RUNBOOK_ID or entry.source.startswith("_archive/"):
            continue
        sections = re.findall(
            r"\*\*(?:Remediation|Escalation):\*\*\s*(.*?)(?=\n\s*\*\*|\n---|\Z)",
            entry.text,
            re.DOTALL,
        )
        return [" ".join(section.split()) for section in sections if section.strip()]
    return []


def build_report(
    incident_id: str,
    correlation: CorrelationResult,
    recommendation: RunbookRecommendation,
    metrics: RunMetrics | None = None,
) -> IncidentReport:
    if metrics is not None and metrics.was_denied_without_call("search_runbook"):
        recommendation = RunbookRecommendation(
            matched=None,
            why="The tool-call budget did not allow a runbook search.",
        )

    questions = list(correlation.open_questions) + list(recommendation.open_questions)
    matched = recommendation.matched

    if matched is not None:
        archived = (recommendation.source or "").startswith("_archive/")
        if not re.fullmatch(r"RB-\d{3}", matched) or matched == FALLBACK_RUNBOOK_ID or archived:
            raise ValueError(f"{matched} cannot be selected as a current runbook")
        if metrics is not None:
            returned_entry = metrics.returned_sources().get(matched)
            if returned_entry is None:
                raise ValueError(f"{matched} was not returned by the runbook search tool")
            if recommendation.source != returned_entry.get("source"):
                raise ValueError(f"The reported source for {matched} does not match the search result")
        runbook = Runbook(
            matched=matched,
            title=recommendation.title,
            source=recommendation.source,
            why=recommendation.why,
            remediation=recommendation.remediation,
        )
        action_source = matched
        steps = runbook.remediation
    else:
        runbook = Runbook(why=recommendation.why)
        action_source = FALLBACK_RUNBOOK_ID
        steps = _fallback_actions(metrics)
        if not steps:
            questions.append(f"Where is the current {FALLBACK_RUNBOOK_ID} fallback procedure?")

    # Never infer urgency from the wording of a remediation step
    priorities = recommendation.action_urgencies if matched is not None else []
    if len(priorities) != len(steps):
        if steps and matched is not None:
            questions.append(
                "The runbook priority list did not match its remediation steps; "
                "those steps have been assigned the conservative 'today' priority."
            )
        priorities = ["today"] * len(steps)

    symptoms = correlation.symptoms.rstrip(". ")
    cause = correlation.root_cause.statement.rstrip(". ")
    return IncidentReport(
        incident_id=incident_id,
        summary=f"{symptoms}. {cause}.",
        timeline=correlation.timeline,
        root_cause=correlation.root_cause,
        ruled_out=correlation.ruled_out,
        runbook=runbook,
        actions=[
            Action(action=step, urgency=priority, source=action_source)
            for step, priority in zip(steps, priorities)
        ],
        open_questions=questions,
    )


def specialist_citations(log_findings: str, change_findings: str) -> tuple[set[str], set[str]]:
    return set(LOG_CITATION.findall(log_findings)), set(CHANGE_CITATION.findall(change_findings))


def ground_evidence(
    correlation: CorrelationResult,
    log_findings: str,
    change_findings: str,
    returned_sources: dict[str, dict] | None = None,
) -> None:
    """Keep only citations returned by specialist tools and qualify unsupported claims."""
    log_refs, change_refs = specialist_citations(log_findings, change_findings)

    if returned_sources is not None:
        log_refs.intersection_update(
            citation for citation, source in returned_sources.items()
            if source.get("file") and source.get("line") is not None
        )
        change_refs.intersection_update(
            citation for citation, source in returned_sources.items()
            if citation.startswith("CHG-")
        )

    available = log_refs | change_refs

    def supported(citations: list[str]) -> list[str]:
        return list(dict.fromkeys(citation for citation in citations if citation in available))

    original_claim_count = len(correlation.timeline) + len(correlation.ruled_out)
    for claim in correlation.timeline + correlation.ruled_out:
        claim.evidence = supported(claim.evidence)

    correlation.timeline = [event for event in correlation.timeline if event.evidence]
    correlation.ruled_out = [theory for theory in correlation.ruled_out if theory.evidence]
    if len(correlation.timeline) + len(correlation.ruled_out) < original_claim_count:
        correlation.open_questions.append(
            "What returned specialist evidence supports the omitted timeline events or ruled-out claims?"
        )

    evidence = supported(correlation.root_cause.evidence)
    cites_logs = any(citation in log_refs for citation in evidence)
    cites_changes = any(citation in change_refs for citation in evidence)

    if cites_logs and cites_changes:
        correlation.root_cause.evidence = evidence
        return

    if not log_refs or not change_refs:
        reason = "One or both specialists supplied no verifiable citations from the search tools."
    else:
        reason = "The proposed cause did not cite returned evidence from both logs and changes."

    correlation.root_cause = RootCause(
        statement="The root cause is unresolved.",
        confidence="low",
        evidence=evidence,
        correlation=reason,
    )
    correlation.open_questions.append(
        "What returned log and change evidence links the observed failure to a cause?"
    )
