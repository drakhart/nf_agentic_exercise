from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from typing import Type

from project_paths import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
MAX_RESULTS_DEFAULT: int = 20

class Result(BaseModel):
    file: str
    line: int
    text: str

class SearchLogsOutput(BaseModel):
    query: str
    total_matches: int
    returned: int
    truncated: bool
    results: list[Result]

class SearchLogsError(BaseModel):
    error: str

class SearchLogsInput(BaseModel):
    query: str = Field(..., description="Query text to search for in the logs.")
    max_results: int = Field(MAX_RESULTS_DEFAULT, description="Maximum number of results to return.")

class SearchLogsTool(BaseTool):
    name: str = "search_logs"
    description: str = "Searches through log files for specific queries"
    args_schema: Type[BaseModel] = SearchLogsInput

    def _run(self, query: str, max_results: int = MAX_RESULTS_DEFAULT) -> SearchLogsOutput | SearchLogsError:
        query_terms: list[str] = query.split()

        if not query_terms:
            return SearchLogsError(error="query must contain at least one term")

        results = []
        for log_file in LOG_DIR.iterdir():
            if not log_file.name.endswith(".log"):
                continue

            with log_file.open(encoding="utf-8") as f:
                for i, line in enumerate(f):
                    log_message = line.split("  ")[-1]

                    if all(term.lower() in log_message.lower() for term in query_terms):
                        results.append(Result(file=log_file.name, line=i+1, text=line))

        results.sort(key=lambda r: r.text.split(' ')[0])

        return SearchLogsOutput(
            query=query,
            total_matches=len(results),
            returned=min(len(results), max_results),
            truncated=len(results) > max_results,
            results=results[:max_results]
        )