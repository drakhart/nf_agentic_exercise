from typing import Literal

from pydantic import BaseModel, Field

from crewai_runner import make_agent, run_task
from project_paths import PROMPTS_DIR
from tools.search_runbook_tool import SearchRunbookTool

PROMPT_FILE = PROMPTS_DIR / "runbook_keeper.md"


class RunbookRecommendation(BaseModel):
    matched: str | None = None
    why: str
    title: str | None = None
    source: str | None = None
    remediation: list[str] = Field(default_factory=list)
    action_urgencies: list[Literal["now", "today", "follow-up"]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


async def run_runbook_keeper(symptoms: str) -> RunbookRecommendation:
    agent = make_agent(
        role="Runbook Keeper",
        goal="Select a current, applicable remediation procedure or explain why none fits.",
        backstory=PROMPT_FILE.read_text(encoding="utf-8"),
        tools=[SearchRunbookTool()],
    )
    return await run_task(
        agent=agent,
        description=(
            "Find a current runbook for these incident symptoms. Search the runbook "
            "and return the matched ID, title, source and supported remediation. "
            "Do not select archived material or RB-000.\n\nSymptoms:\n{symptoms}"
        ),
        expected_output="A structured runbook recommendation. Use matched=null if no current entry fits.",
        inputs={"symptoms": symptoms},
        response_model=RunbookRecommendation,
        stage="runbook_keeper",
    )
