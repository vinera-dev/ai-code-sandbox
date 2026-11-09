import shutil
import subprocess
from pathlib import Path

import pytest

TEST_IMAGE = "sbx-python:test"
DOCKER_DIR = Path(__file__).resolve().parent.parent / "docker"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def leftover_containers() -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=sbx-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.split()


def pytest_collection_modifyitems(config, items):
    if docker_available():
        return
    skip = pytest.mark.skip(reason="Docker is not available")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def sandbox_image():
    subprocess.run(
        [
            "docker",
            "build",
            "-q",
            "-t",
            TEST_IMAGE,
            "-f",
            str(DOCKER_DIR / "Dockerfile"),
            str(DOCKER_DIR),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )
    yield TEST_IMAGE
    subprocess.run(
        ["docker", "rmi", "-f", TEST_IMAGE], capture_output=True, timeout=60, check=False
    )


@pytest.fixture(scope="session", autouse=True)
def no_containers_left():
    yield
    if docker_available():
        assert leftover_containers() == []
