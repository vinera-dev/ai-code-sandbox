import shutil
import subprocess
import threading
import uuid

from app.runner import Execution, RunnerUnavailable

DEFAULT_IMAGE = "sbx-python:latest"
CONTAINER_PREFIX = "sbx-"
TMP_SIZE = "16m"
SANDBOX_USER = "10001:10001"
DEFAULT_MEMORY = "128m"
DEFAULT_CPUS = "0.5"
DEFAULT_PIDS = 64
REMOVE_TIMEOUT_SECONDS = 30


class DockerRunner:
    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        memory: str = DEFAULT_MEMORY,
        cpus: str = DEFAULT_CPUS,
        pids: int = DEFAULT_PIDS,
    ) -> None:
        self._image = image
        self._memory = memory
        self._cpus = cpus
        self._pids = pids
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
            "--user",
            SANDBOX_USER,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            self._cpus,
            "--pids-limit",
            str(self._pids),
            "--memory",
            self._memory,
            "--memory-swap",
            self._memory,
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
        timed_out = False
        try:
            _feed(process, code)
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            self._dispose(name, process)
            stdout.join()
            stderr.join()
        return Execution(
            stdout=stdout.text(),
            stderr=stderr.text(),
            exit_code=None if timed_out else process.returncode,
            timed_out=timed_out,
        )

    def _dispose(self, name: str, process: subprocess.Popen) -> None:
        self._remove(name)
        if process.poll() is None:
            process.kill()
            process.wait()
            self._remove(name)

    def _remove(self, name: str) -> None:
        subprocess.run(
            [self._docker, "rm", "--force", name],
            capture_output=True,
            timeout=REMOVE_TIMEOUT_SECONDS,
            check=False,
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
