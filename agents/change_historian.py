from project_paths import PROMPTS_DIR
from tools.search_changes_tool import SearchChangesTool
from crewai_runner import make_agent, run_task

PROMPT_FILE = PROMPTS_DIR / "change_historian.md"


async def run_change_historian(inputs: dict[str, str]) -> str:
    agent = make_agent(
        role="Change Historian",
        goal="Find recent changes that may explain the incident timeline.",
        backstory=PROMPT_FILE.read_text(encoding="utf-8"),
        tools=[SearchChangesTool()],
    )
    return await run_task(
        agent=agent,
        description=(
            "Investigate change history for incident {incident}. Use the incident "
            "report to identify relevant services and symptoms. Search for changes "
            "and cite exact change IDs.\n\n{incident_report}"
        ),
        expected_output="A concise change-history analysis with exact change IDs and open questions.",
        inputs=inputs,
        stage="change_historian",
    )
