from project_paths import PROMPTS_DIR
from tools.search_logs_tool import SearchLogsTool
from crewai_runner import make_agent, run_task

PROMPT_FILE = PROMPTS_DIR / "log_analyst.md"


async def run_log_analyst(inputs: dict[str, str]) -> str:
    agent = make_agent(
        role="Log Analyst",
        goal="Find timestamped log evidence that explains the incident symptoms.",
        backstory=PROMPT_FILE.read_text(encoding="utf-8"),
        tools=[SearchLogsTool()],
    )
    return await run_task(
        agent=agent,
        description=(
            "Investigate incident {incident} using the incident report below. "
            "Search the logs with the available tool. Return factual findings "
            "with exact filename:line citations.\n\n{incident_report}"
        ),
        expected_output="A concise evidence-based summary with exact log citations and unresolved questions.",
        inputs=inputs,
        stage="log_analyst",
    )
