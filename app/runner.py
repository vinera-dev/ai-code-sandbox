from dataclasses import dataclass
from typing import Protocol


class RunnerUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Execution:
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool = False
    output_truncated: bool = False


class Runner(Protocol):
    def run(self, code: str, timeout_seconds: float) -> Execution: ...


class UnavailableRunner:
    def run(self, code: str, timeout_seconds: float) -> Execution:
        raise RunnerUnavailable("No container runner is configured.")
