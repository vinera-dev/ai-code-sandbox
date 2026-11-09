import subprocess

import pytest

pytestmark = pytest.mark.docker


def run_in_image(image, entrypoint, *args, user="10001"):
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            "sbx-image-probe",
            "--network",
            "none",
            "--user",
            user,
            "--entrypoint",
            entrypoint,
            image,
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_image_builds_and_runs_python(sandbox_image):
    result = run_in_image(sandbox_image, "python", "-c", "print(1 + 1)")

    assert result.returncode == 0
    assert result.stdout.strip() == "2"


def test_image_default_user_is_unprivileged(sandbox_image):
    result = run_in_image(sandbox_image, "id", "-u")

    assert result.stdout.strip() == "10001"


def test_image_has_no_setuid_binaries(sandbox_image):
    result = run_in_image(
        sandbox_image, "find", "/", "-xdev", "-perm", "/6000", "-type", "f", user="0"
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""
