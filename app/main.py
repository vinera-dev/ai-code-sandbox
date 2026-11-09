import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.policy import Policy, check_code, load_policy
from app.runner import Execution, Runner, RunnerUnavailable, UnavailableRunner
from app.schemas import RunRequest, RunResponse


def create_app(runner: Runner | None = None, policy: Policy | None = None) -> FastAPI:
    active_runner = runner or UnavailableRunner()
    active_policy = policy or load_policy()
    application = FastAPI(title="ai-code-sandbox", version="0.1.0")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/runs", response_model=RunResponse)
    def create_run(request: RunRequest):
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        violations = check_code(request.code, active_policy)
        if violations:
            blocked = RunResponse(run_id=run_id, status="blocked", violations=violations)
            return JSONResponse(status_code=403, content=blocked.model_dump())
        try:
            execution = active_runner.run(request.code, request.timeout_seconds)
        except RunnerUnavailable as error:
            raise HTTPException(status_code=501, detail=str(error)) from error
        return build_response(run_id, execution, started)

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
