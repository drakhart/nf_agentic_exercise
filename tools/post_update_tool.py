from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from typing import Type
from datetime import datetime, timezone

from project_paths import OUTPUT_DIR

CHANNEL = "#incident-updates"
LOG_FILE = OUTPUT_DIR / "comms.log"
MAX_CHARS = 600

class PostUpdateOutput(BaseModel):
    status: str
    channel: str
    characters: int

class PostUpdateError(BaseModel):
    error: str

class PostUpdateInput(BaseModel):
    text: str = Field(..., description="Text of the update to post.")

class PostUpdateTool(BaseTool):
    name: str = "post_update"
    description: str = "Posts an update with the given text"
    args_schema: Type[BaseModel] = PostUpdateInput

    def _run(self, text: str) -> PostUpdateOutput | PostUpdateError:
        if not text:
            return PostUpdateError(error="text must not be empty")

        if len(text) > MAX_CHARS:
            return PostUpdateError(error=f"update exceeds {MAX_CHARS} characters")

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {text}\n")

        return PostUpdateOutput(
            status="posted",
            channel=CHANNEL,
            characters=len(text)
        )