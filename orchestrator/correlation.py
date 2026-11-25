from crewai_runner import make_agent, run_task
from orchestrator.models import CorrelationResult
from orchestrator.report import specialist_citations
from project_paths import PROMPTS_DIR

PROMPT = PROMPTS_DIR / "incident_analyst.md"


async def correlate_findings(
    incident_report: str,
    log_findings: str,
    change_findings: str,
) -> CorrelationResult:
    log_refs, change_refs = specialist_citations(log_findings, change_findings)
    agent = make_agent(
        role="Incident Analyst",
        goal="Join the log and change findings into a defensible incident diagnosis.",
        backstory=PROMPT.read_text(encoding="utf-8"),
    )
    return await run_task(
        agent=agent,
        description=(
            "Correlate the incident report with the two independent specialist findings. "
            "Do not infer causation from timing alone, and use only the citations listed "
            "below.\n\nIncident report:\n{incident_report}\n\n"
            "Log findings:\n{log_findings}\n\n"
            "Change findings:\n{change_findings}\n\n"
            "Available log citations: {log_citations}\n"
            "Available change citations: {change_citations}"
        ),
        expected_output=(
            "A structured result with symptoms, timeline, root cause, ruled-out theories "
            "and open questions."
        ),
        inputs={
            "incident_report": incident_report,
            "log_findings": log_findings,
            "change_findings": change_findings,
            "log_citations": sorted(log_refs),
            "change_citations": sorted(change_refs),
        },
        response_model=CorrelationResult,
        stage="incident_analyst",
    )
