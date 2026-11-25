from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from typing import Type
from datetime import datetime
import re

from project_paths import DATA_DIR

CHANGES_FILE = DATA_DIR / "changes" / "change-log.md"
MAX_RESULTS_DEFAULT: int = 5

def extract_shipped_date(text: str) -> datetime:
    match = re.search(r"\*\*Shipped:\*\* (\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)", text)

    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M UTC")

    return datetime.min

class Result(BaseModel):
    id: str
    title: str
    text: str

class SearchChangesOutput(BaseModel):
    query: str
    total_matches: int
    returned: int
    truncated: bool
    results: list[Result]

class SearchChangesError(BaseModel):
    error: str

class SearchChangesInput(BaseModel):
    query: str = Field(..., description="Query text to search for in the change logs.")
    max_results: int = Field(MAX_RESULTS_DEFAULT, description="Maximum number of results to return.")

class SearchChangesTool(BaseTool):
    name: str = "search_changes"
    description: str = "Searches through change logs for specific queries"
    args_schema: Type[BaseModel] = SearchChangesInput

    def _run(self, query: str, max_results: int = MAX_RESULTS_DEFAULT) -> SearchChangesOutput | SearchChangesError:
        query_terms: list[str] = query.split()

        if not query_terms:
            return SearchChangesError(error="query must contain at least one term")

        results = []
        with CHANGES_FILE.open(encoding="utf-8") as f:
            content = f.read()
            entries = content.split("## ")

            for entry in entries:
                if entry.startswith("# "):
                    continue

                lines = entry.split("\n")
                [id, title] = lines[0].split(" - ")
                text = "\n".join(lines[1:])

                if all(term.lower() in text.lower() for term in query_terms):
                    results.append(Result(id=id, title=title, text=text))

        results.sort(key=lambda r: extract_shipped_date(r.text), reverse=True)


        return SearchChangesOutput(
            query=query,
            total_matches=len(results),
            returned=min(len(results), max_results),
            truncated=len(results) > max_results,
            results=results[:max_results]
        )