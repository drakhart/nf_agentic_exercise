from crewai_runner import make_agent, run_task
from project_paths import PROMPTS_DIR

PROMPT_FILE = PROMPTS_DIR / "update_poster.md"


async def draft_update(report_json: str) -> str:
    agent = make_agent(
        role="Incident Communications Drafter",
        goal="Write a concise, accurate stakeholder update based only on the incident report.",
        backstory=PROMPT_FILE.read_text(encoding="utf-8"),
    )
    return await run_task(
        agent=agent,
        description="Draft the stakeholder update from this report. Preserve uncertainty and distinguish completed work from recommendations.\n\n{report}",
        expected_output="Exactly three plain-text lines, at most 600 characters, with no headings.",
        inputs={"report": report_json},
        stage="update_poster",
    )
