import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.audit import AuditLog
from app.policy import Policy, check_code, load_policy
from app.runner import Execution, Runner, RunnerUnavailable, UnavailableRunner
from app.schemas import RunRequest, RunResponse

DEFAULT_AUDIT_PATH = "audit.jsonl"
DEFAULT_MAX_CONCURRENT_RUNS = 4


def create_app(
    runner: Runner | None = None,
    policy: Policy | None = None,
    audit_log: AuditLog | None = None,
    max_concurrent_runs: int | None = None,
) -> FastAPI:
    active_runner = runner or UnavailableRunner()
    active_policy = policy or load_policy()
    audit = audit_log or AuditLog(Path(os.environ.get("AUDIT_LOG_PATH", DEFAULT_AUDIT_PATH)))
    limit = max_concurrent_runs or int(
        os.environ.get("MAX_CONCURRENT_RUNS", DEFAULT_MAX_CONCURRENT_RUNS)
    )
    slots = threading.BoundedSemaphore(limit)
    policy_hash = active_policy.fingerprint()
    application = FastAPI(title="ai-code-sandbox", version="0.1.0")

    def log(run_id: str, code: str, status: str, started: float, **extra: Any) -> None:
        duration_ms = int((time.monotonic() - started) * 1000)
        audit.record(
            run_id=run_id,
            code=code,
            policy_hash=policy_hash,
            status=status,
            duration_ms=duration_ms,
            **extra,
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/runs", response_model=RunResponse)
    def create_run(request: RunRequest):
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        violations = check_code(request.code, active_policy)
        if violations:
            log(run_id, request.code, "blocked", started, violations=[v.rule for v in violations])
            blocked = RunResponse(run_id=run_id, status="blocked", violations=violations)
            return JSONResponse(status_code=403, content=blocked.model_dump())
        if not slots.acquire(blocking=False):
            log(run_id, request.code, "rejected", started)
            raise HTTPException(status_code=429, detail="Too many runs in progress.")
        try:
            execution = active_runner.run(request.code, request.timeout_seconds)
        except RunnerUnavailable as error:
            log(run_id, request.code, "error", started)
            raise HTTPException(status_code=501, detail=str(error)) from error
        finally:
            slots.release()
        response = build_response(run_id, execution, started)
        log(run_id, request.code, response.status, started, exit_code=execution.exit_code)
        return response

    @application.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        entry = audit.find(run_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return entry

    return application


def build_response(run_id: str, execution: Execution, started: float) -> RunResponse:
    return RunResponse(
        run_id=run_id,
        status="timeout" if execution.timed_out else "completed",
        stdout=execution.stdout,
        stderr=execution.stderr,
        exit_code=execution.exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        output_truncated=execution.output_truncated,
    )


app = create_app()
