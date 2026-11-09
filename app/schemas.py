from typing import Literal

from pydantic import BaseModel, Field

MAX_CODE_CHARS = 20_000
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 30.0

RunStatus = Literal["completed", "timeout", "blocked", "rejected", "error"]


class RunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0, le=MAX_TIMEOUT_SECONDS)


class Violation(BaseModel):
    rule: str
    detail: str
    line: int | None = None


class RunResponse(BaseModel):
    run_id: str
    status: RunStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    output_truncated: bool = False
    violations: list[Violation] = Field(default_factory=list)
