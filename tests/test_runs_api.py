import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runner import Execution
from app.schemas import MAX_CODE_CHARS, MAX_TIMEOUT_SECONDS


class StubRunner:
    def __init__(self, execution=None):
        self.execution = execution or Execution(stdout="hi\n", stderr="", exit_code=0)
        self.calls = []

    def run(self, code, timeout_seconds):
        self.calls.append((code, timeout_seconds))
        return self.execution


@pytest.fixture
def runner():
    return StubRunner()


@pytest.fixture
def client(runner):
    return TestClient(create_app(runner))


def test_valid_run_returns_the_execution_result(client, runner):
    response = client.post("/runs", json={"code": "print('hi')"})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["stdout"] == "hi\n"
    assert body["exit_code"] == 0
    assert len(body["run_id"]) == 32
    assert runner.calls == [("print('hi')", 5.0)]


def test_timeout_is_passed_to_the_runner(client, runner):
    client.post("/runs", json={"code": "pass", "timeout_seconds": 2.5})

    assert runner.calls[0][1] == 2.5


def test_timed_out_execution_is_reported(runner):
    runner.execution = Execution(stdout="", stderr="", exit_code=None, timed_out=True)

    response = TestClient(create_app(runner)).post("/runs", json={"code": "while True: pass"})

    assert response.json()["status"] == "timeout"
    assert response.json()["exit_code"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"code": ""},
        {"code": "x" * (MAX_CODE_CHARS + 1)},
        {"code": "pass", "timeout_seconds": 0},
        {"code": "pass", "timeout_seconds": -1},
        {"code": "pass", "timeout_seconds": MAX_TIMEOUT_SECONDS + 1},
        {"code": "pass", "timeout_seconds": "soon"},
        {"code": 123},
    ],
)
def test_invalid_input_returns_422_and_never_reaches_the_runner(client, runner, body):
    response = client.post("/runs", json=body)

    assert response.status_code == 422
    assert runner.calls == []


def test_code_at_the_size_limit_is_accepted(client):
    assert client.post("/runs", json={"code": "#" * MAX_CODE_CHARS}).status_code == 200


def test_without_a_runner_the_service_answers_501():
    response = TestClient(create_app()).post("/runs", json={"code": "print(1)"})

    assert response.status_code == 501
