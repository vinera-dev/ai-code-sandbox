import pytest

from app.docker_runner import DockerRunner

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def runner(sandbox_image):
    return DockerRunner(image=sandbox_image)


def test_print_is_captured(runner):
    result = runner.run("print('hello')", 20)

    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.exit_code == 0


def test_stderr_and_exit_code_are_captured(runner):
    result = runner.run("import sys\nsys.stderr.write('bad')\nsys.exit(3)", 20)

    assert result.stderr == "bad"
    assert result.exit_code == 3


def test_uncaught_exception_is_reported(runner):
    result = runner.run("raise ValueError('boom')", 20)

    assert "ValueError: boom" in result.stderr
    assert result.exit_code == 1
