from project_paths import PROMPTS_DIR
from crewai_runner import make_agent, run_task

PROMPT_FILE = PROMPTS_DIR / "impact_analyst.md"


async def impact_question(inputs: dict[str, str]) -> str:
    agent = make_agent(
        role="Impact Analyst",
        goal="Identify the likely scope and customer impact from the incident report.",
        backstory=PROMPT_FILE.read_text(encoding="utf-8"),
    )
    return await run_task(
        agent=agent,
        description="Assess the potential impact described in this incident report. Do not invent affected customer counts.\n\n{incident_report}",
        expected_output="A short impact assessment with uncertainty clearly stated.",
        inputs=inputs,
        stage="impact_analyst",
    )
