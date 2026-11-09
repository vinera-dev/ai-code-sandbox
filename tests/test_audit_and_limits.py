import hashlib
import json
import threading

import pytest
from fastapi.testclient import TestClient

from app.audit import AuditLog
from app.main import create_app
from app.policy import load_policy
from app.runner import Execution, RunnerUnavailable


class StubRunner:
    def __init__(self, execution=None, error=None):
        self.execution = execution or Execution(stdout="secret output", stderr="", exit_code=0)
        self.error = error

    def run(self, code, timeout_seconds):
        if self.error:
            raise self.error
        return self.execution


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def entries(audit):
    return [json.loads(line) for line in audit._path.read_text(encoding="utf-8").splitlines()]


def test_completed_runs_are_audited_without_code_or_output(audit):
    client = TestClient(create_app(StubRunner(), audit_log=audit))
    code = "print('very secret code')"

    run_id = client.post("/runs", json={"code": code}).json()["run_id"]

    (entry,) = entries(audit)
    assert entry["run_id"] == run_id
    assert entry["status"] == "completed"
    assert entry["exit_code"] == 0
    assert entry["code_sha256"] == hashlib.sha256(code.encode()).hexdigest()
    assert entry["code_chars"] == len(code)
    assert entry["policy_sha256"] == load_policy().fingerprint()
    assert entry["duration_ms"] >= 0
    assert entry["timestamp"].endswith("+00:00")
    raw = audit._path.read_text(encoding="utf-8")
    assert "very secret code" not in raw
    assert "secret output" not in raw


def test_blocked_runs_are_audited_with_the_violated_rules(audit):
    client = TestClient(create_app(StubRunner(), audit_log=audit))

    client.post("/runs", json={"code": "import os\neval('1')"})

    (entry,) = entries(audit)
    assert entry["status"] == "blocked"
    assert entry["violations"] == ["forbidden_import", "forbidden_call"]


def test_unavailable_runner_is_audited_as_error(audit):
    client = TestClient(create_app(StubRunner(error=RunnerUnavailable("down")), audit_log=audit))

    assert client.post("/runs", json={"code": "print(1)"}).status_code == 501
    assert entries(audit)[0]["status"] == "error"


def test_timeouts_are_audited(audit):
    execution = Execution(stdout="", stderr="", exit_code=None, timed_out=True)
    client = TestClient(create_app(StubRunner(execution), audit_log=audit))

    client.post("/runs", json={"code": "print(1)"})

    assert entries(audit)[0]["status"] == "timeout"


def test_invalid_requests_are_not_audited(audit):
    client = TestClient(create_app(StubRunner(), audit_log=audit))

    client.post("/runs", json={"code": ""})

    assert not audit._path.exists()


def test_get_run_returns_the_audit_entry(audit):
    client = TestClient(create_app(StubRunner(), audit_log=audit))
    run_id = client.post("/runs", json={"code": "print(1)"}).json()["run_id"]

    response = client.get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["run_id"] == run_id
    assert response.json()["status"] == "completed"


def test_get_run_for_a_blocked_run(audit):
    client = TestClient(create_app(StubRunner(), audit_log=audit))
    run_id = client.post("/runs", json={"code": "import os"}).json()["run_id"]

    assert client.get(f"/runs/{run_id}").json()["status"] == "blocked"


@pytest.mark.parametrize("run_id", ["0" * 32, "unknown", "../../etc/passwd", "A" * 32])
def test_unknown_or_malformed_run_ids_return_404(audit, run_id):
    client = TestClient(create_app(StubRunner(), audit_log=audit))
    client.post("/runs", json={"code": "print(1)"})

    assert client.get(f"/runs/{run_id}").status_code == 404


def test_get_run_without_any_log_returns_404(audit):
    client = TestClient(create_app(StubRunner(), audit_log=audit))

    assert client.get(f"/runs/{'a' * 32}").status_code == 404


def test_concurrent_audit_writes_stay_one_json_object_per_line(audit):
    client = TestClient(create_app(StubRunner(), audit_log=audit, max_concurrent_runs=50))

    def submit():
        client.post("/runs", json={"code": "print(1)"})

    threads = [threading.Thread(target=submit) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(entries(audit)) == 20
    assert len({entry["run_id"] for entry in entries(audit)}) == 20


class BlockingRunner:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, code, timeout_seconds):
        self.started.set()
        self.release.wait(timeout=10)
        return Execution(stdout="", stderr="", exit_code=0)


def test_runs_above_the_concurrency_limit_are_rejected_with_429(audit):
    runner = BlockingRunner()
    client = TestClient(create_app(runner, audit_log=audit, max_concurrent_runs=1))
    first = {}

    def submit_first():
        first["response"] = client.post("/runs", json={"code": "print(1)"})

    thread = threading.Thread(target=submit_first)
    thread.start()
    assert runner.started.wait(timeout=10)

    rejected = client.post("/runs", json={"code": "print(2)"})
    runner.release.set()
    thread.join(timeout=10)

    assert rejected.status_code == 429
    assert first["response"].status_code == 200
    assert sorted(entry["status"] for entry in entries(audit)) == ["completed", "rejected"]


def test_slot_is_released_after_a_run_so_the_next_one_is_accepted(audit):
    client = TestClient(create_app(StubRunner(), audit_log=audit, max_concurrent_runs=1))

    statuses = [client.post("/runs", json={"code": "print(1)"}).status_code for _ in range(3)]

    assert statuses == [200, 200, 200]


def test_slot_is_released_when_the_runner_fails(audit):
    client = TestClient(
        create_app(
            StubRunner(error=RunnerUnavailable("down")), audit_log=audit, max_concurrent_runs=1
        )
    )

    statuses = [client.post("/runs", json={"code": "print(1)"}).status_code for _ in range(3)]

    assert statuses == [501, 501, 501]
