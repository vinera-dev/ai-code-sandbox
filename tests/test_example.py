import pytest

from app.docker_runner import DockerRunner
from app.runner import Execution
from examples.llm_integration import SCRIPTED_ANSWERS, ScriptedModel, execute_model_code


class StubRunner:
    def __init__(self, execution):
        self.execution = execution
        self.calls = []

    def run(self, code, timeout_seconds):
        self.calls.append(code)
        return self.execution


def test_blocked_code_never_reaches_the_runner():
    runner = StubRunner(Execution(stdout="", stderr="", exit_code=0))
    model = ScriptedModel(SCRIPTED_ANSWERS)

    outcome = execute_model_code(model, "call an external host", runner)

    assert outcome.status == "blocked"
    assert runner.calls == []


def test_completed_output_is_returned():
    runner = StubRunner(Execution(stdout="5050\n", stderr="", exit_code=0))
    model = ScriptedModel(SCRIPTED_ANSWERS)

    outcome = execute_model_code(model, "sum the first hundred integers", runner)

    assert (outcome.status, outcome.output) == ("completed", "5050")


@pytest.mark.docker
def test_example_runs_against_real_containers(sandbox_image):
    runner = DockerRunner(image=sandbox_image)
    model = ScriptedModel(SCRIPTED_ANSWERS)

    outcomes = {
        task: execute_model_code(model, task, runner, timeout=6) for task in SCRIPTED_ANSWERS
    }

    assert outcomes["sum the first hundred integers"].output == "5050"
    assert outcomes["read the service secrets"].status == "blocked"
    assert outcomes["call an external host"].status == "blocked"
    assert outcomes["wait forever"].status == "timeout"
