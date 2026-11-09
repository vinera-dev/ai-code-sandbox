import shutil
import subprocess
import threading
import uuid

from app.runner import Execution, RunnerUnavailable

DEFAULT_IMAGE = "sbx-python:latest"
CONTAINER_PREFIX = "sbx-"
TMP_SIZE = "16m"


class DockerRunner:
    def __init__(self, image: str = DEFAULT_IMAGE) -> None:
        self._image = image
        self._docker = shutil.which("docker")

    def _arguments(self, name: str) -> list[str]:
        return [
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={TMP_SIZE}",
            self._image,
        ]

    def run(self, code: str, timeout_seconds: float) -> Execution:
        if self._docker is None:
            raise RunnerUnavailable("The docker command was not found.")
        name = f"{CONTAINER_PREFIX}{uuid.uuid4().hex}"
        process = subprocess.Popen(
            [self._docker, *self._arguments(name)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout = _Collector(process.stdout)
        stderr = _Collector(process.stderr)
        try:
            _feed(process, code)
            process.wait()
        finally:
            stdout.join()
            stderr.join()
        return Execution(
            stdout=stdout.text(),
            stderr=stderr.text(),
            exit_code=process.returncode,
        )


def _feed(process: subprocess.Popen, code: str) -> None:
    try:
        process.stdin.write(code.encode("utf-8"))
        process.stdin.close()
    except (BrokenPipeError, OSError):
        return


class _Collector:
    def __init__(self, stream) -> None:
        self._stream = stream
        self._chunks: list[bytes] = []
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        for chunk in iter(lambda: self._stream.read(4096), b""):
            self._chunks.append(chunk)

    def join(self) -> None:
        self._thread.join()

    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")
