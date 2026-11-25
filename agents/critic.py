from pydantic import BaseModel, Field

from crewai_runner import make_agent, run_task
from project_paths import PROMPTS_DIR

PROMPT_FILE = PROMPTS_DIR / "critic.md"


class CriticReview(BaseModel):
    issues: list[str] = Field(default_factory=list)


async def review_evidence(report: dict, sources: dict[str, str]) -> CriticReview:
    agent = make_agent(
        role="Evidence Critic",
        goal="Identify claims in the incident report that are not supported by the supplied evidence.",
        backstory=PROMPT_FILE.read_text(encoding="utf-8"),
    )
    return await run_task(
        agent=agent,
        description="Review this report against the supplied source excerpts. Return only specific, actionable evidence issues.\n\nReport: {report}\n\nSource excerpts: {sources}",
        expected_output="A structured list of unsupported claims or an empty list if the report is grounded.",
        inputs={"report": report, "sources": sources},
        response_model=CriticReview,
        stage="evidence_critic",
    )
