from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from typing import Type

from project_paths import DATA_DIR

RUNBOOK_DIR = DATA_DIR / "runbook"
MAX_RESULTS_DEFAULT: int = 3

class Result(BaseModel):
    id: str
    title: str
    source: str
    text: str

class SearchRunbookOutput(BaseModel):
    query: str
    total_matches: int
    returned: int
    truncated: bool
    results: list[Result]

class SearchRunbookError(BaseModel):
    error: str

class SearchRunbookInput(BaseModel):
    query: str = Field(..., description="Query text to search for in the runbook files.")
    max_results: int = Field(MAX_RESULTS_DEFAULT, description="Maximum number of results to return.")

class SearchRunbookTool(BaseTool):
    name: str = "search_runbook"
    description: str = "Searches through runbook files for specific queries"
    args_schema: Type[BaseModel] = SearchRunbookInput

    def _run(self, query: str, max_results: int = MAX_RESULTS_DEFAULT) -> SearchRunbookOutput | SearchRunbookError:
        query_terms: list[str] = query.split()

        if not query_terms:
            return SearchRunbookError(error="query must contain at least one term")

        results = []
        for root, _, files in RUNBOOK_DIR.walk():
            for runbook_file in files:
                if not runbook_file.endswith(".md"):
                    continue

                path = root / runbook_file
                content = path.read_text(encoding="utf-8")

                entries = content.split("## ")

                for entry in entries:
                    if entry.startswith("# "):
                        continue

                    lines = entry.split("\n")
                    [id, title] = lines[0].split(" - ")
                    text = "\n".join(lines[1:])

                    if all(term.lower() in text.lower() for term in query_terms):
                        source = path.relative_to(RUNBOOK_DIR).as_posix()
                        results.append(Result(id=id, title=title, source=source, text=text))

        results.sort(key=lambda r: (-sum(term.lower() in r.text.lower() for term in query_terms), r.id))

        return SearchRunbookOutput(
            query=query,
            total_matches=len(results),
            returned=min(len(results), max_results),
            truncated=len(results) > max_results,
            results=results[:max_results]
        )