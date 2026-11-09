import json
import os
import textwrap
import time

import pytest

from app import docker_runner
from app.docker_runner import DockerRunner
from tests.conftest import leftover_containers

pytestmark = pytest.mark.docker


def source(text):
    return textwrap.dedent(text)


@pytest.fixture(scope="module")
def runner(sandbox_image):
    return DockerRunner(image=sandbox_image)


def test_print_is_captured(runner):
    result = runner.run("print('hello')", 20)

    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.exit_code == 0


def test_stderr_and_exit_code_are_captured(runner):
    result = runner.run(
        source(
            """
            import sys
            sys.stderr.write('bad')
            sys.exit(3)
            """
        ),
        20,
    )

    assert result.stderr == "bad"
    assert result.exit_code == 3


def test_uncaught_exception_is_reported(runner):
    result = runner.run("raise ValueError('boom')", 20)

    assert "ValueError: boom" in result.stderr
    assert result.exit_code == 1


def test_external_connection_fails(runner):
    code = source(
        """
        import socket
        try:
            socket.create_connection(('1.1.1.1', 80), timeout=3)
            print('connected')
        except OSError:
            print('blocked')
        """
    )

    result = runner.run(code, 20)

    assert result.stdout == "blocked\n"


def test_only_loopback_interface_exists(runner):
    code = "import socket\nprint(sorted(name for _, name in socket.if_nameindex()))"

    result = runner.run(code, 20)

    assert result.stdout == "['lo']\n"


WRITE_ATTEMPT = source(
    """
    try:
        open({path!r}, 'w').write('x')
        print('written')
    except OSError as error:
        print(error.errno)
    """
)


def test_write_outside_tmp_fails(runner):
    for path in ("/probe", "/etc/probe", "/usr/probe", "/home/probe"):
        result = runner.run(WRITE_ATTEMPT.format(path=path), 20)

        assert result.stdout.strip() == "30", path


def test_tmp_is_writable_but_small(runner):
    code = source(
        """
        open('/tmp/small', 'w').write('x')
        try:
            with open('/tmp/big', 'wb') as handle:
                for _ in range(64):
                    handle.write(b'0' * 1024 * 1024)
                    handle.flush()
            print('filled')
        except OSError as error:
            print(error.errno)
        """
    )

    result = runner.run(code, 30)

    assert result.stdout.strip() == "28"


def test_tmp_does_not_allow_executing_files(runner):
    code = source(
        """
        import os, shutil
        shutil.copy('/bin/true', '/tmp/tool')
        try:
            os.execv('/tmp/tool', ['/tmp/tool'])
        except OSError as error:
            print(error.errno)
        """
    )

    result = runner.run(code, 20)

    assert result.stdout.strip() == "13"


def test_code_does_not_run_as_root(runner):
    code = source(
        """
        import os
        print(os.getuid(), os.getgid(), os.geteuid())
        """
    )

    result = runner.run(code, 20)

    assert result.stdout.split() == ["10001", "10001", "10001"]


def test_all_capabilities_are_dropped(runner):
    code = source(
        """
        fields = dict(line.split(':\t') for line in open('/proc/self/status') if ':\t' in line)
        print(fields['CapEff'].strip(), fields['CapBnd'].strip(), fields['NoNewPrivs'].strip())
        """
    )

    result = runner.run(code, 20)

    assert result.stdout.split() == ["0000000000000000", "0000000000000000", "1"]


def test_escalation_to_root_is_refused(runner):
    code = source(
        """
        import os
        try:
            os.setuid(0)
            print('root')
        except PermissionError:
            print('refused')
        """
    )

    result = runner.run(code, 20)

    assert result.stdout.strip() == "refused"


def test_huge_allocation_is_killed(runner):
    code = source(
        """
        blocks = []
        while True:
            blocks.append(bytearray(32 * 1024 * 1024))
            print(len(blocks), flush=True)
        """
    )

    result = runner.run(code, 30)

    allocated = [int(line) for line in result.stdout.split()]
    assert result.exit_code == 137
    assert max(allocated) * 32 < 160


def test_memory_below_the_limit_is_allowed(runner):
    result = runner.run("data = bytearray(32 * 1024 * 1024)\nprint(len(data))", 20)

    assert result.stdout.strip() == str(32 * 1024 * 1024)


def test_fork_bomb_is_contained(runner):
    code = source(
        """
        import os, time
        children = 0
        try:
            while True:
                if os.fork() == 0:
                    time.sleep(30)
                    os._exit(0)
                children += 1
        except OSError as error:
            print(children, error.errno, flush=True)
        os._exit(0)
        """
    )

    result = runner.run(code, 30)

    children, errno = (int(value) for value in result.stdout.split())
    assert errno == 11
    assert 0 < children < 64


def test_cpu_usage_is_capped(runner):
    code = source(
        """
        import time
        wall = time.monotonic()
        cpu = time.process_time()
        while time.monotonic() - wall < 4:
            pass
        print((time.process_time() - cpu) / (time.monotonic() - wall))
        """
    )

    result = runner.run(code, 30)

    assert float(result.stdout) < 0.75


def test_infinite_loop_ends_at_the_deadline(runner):
    started = time.monotonic()

    result = runner.run("while True:\n    pass", 6)

    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert result.exit_code is None
    assert elapsed < 6 + 10
    assert leftover_containers() == []


def test_sleeping_code_is_stopped_too(runner):
    result = runner.run("import time\ntime.sleep(600)", 5)

    assert result.timed_out is True
    assert leftover_containers() == []


def test_output_before_the_deadline_is_kept(runner):
    result = runner.run("print('before', flush=True)\nwhile True:\n    pass", 8)

    assert result.timed_out is True
    assert result.stdout == "before\n"


def test_huge_output_is_truncated(runner):
    code = source(
        """
        import sys
        chunk = 'x' * 1024 * 1024
        for _ in range(64):
            sys.stdout.write(chunk)
            sys.stderr.write(chunk)
        """
    )

    result = runner.run(code, 60)

    assert result.exit_code == 0
    assert result.output_truncated is True
    assert len(result.stdout) == 64 * 1024
    assert len(result.stderr) == 64 * 1024


def test_endless_output_is_capped_until_the_deadline(runner):
    result = runner.run("while True:\n    print('y' * 1000)", 8)

    assert result.timed_out is True
    assert result.output_truncated is True
    assert len(result.stdout) == 64 * 1024


def test_output_at_the_limit_is_not_flagged(sandbox_image):
    small = DockerRunner(image=sandbox_image, max_output_bytes=10)

    result = small.run("import sys\nsys.stdout.write('0123456789')", 20)

    assert result.stdout == "0123456789"
    assert result.output_truncated is False


def test_container_is_removed_when_the_runner_fails_midway(runner, monkeypatch):
    seen = []
    original = docker_runner._feed

    def feed_then_fail(process, code):
        original(process, code)
        time.sleep(5)
        seen.extend(leftover_containers())
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(docker_runner, "_feed", feed_then_fail)

    with pytest.raises(RuntimeError):
        runner.run("import time\ntime.sleep(600)", 60)

    assert len(seen) == 1
    assert leftover_containers() == []


def test_no_container_remains_when_the_image_is_missing():
    broken = DockerRunner(image="sbx-missing-image:none")

    result = broken.run("print(1)", 30)

    assert result.exit_code != 0
    assert leftover_containers() == []


def test_no_container_remains_after_crashing_code(runner):
    for code in ("raise SystemExit(7)", "import os\nos._exit(9)", "1/0"):
        runner.run(code, 20)

    assert leftover_containers() == []


CANARY_NAME = "SBX_CANARY_SECRET"
CANARY_VALUE = "sbx-canary-value-5f3a9c"


def test_host_environment_is_not_visible(runner, monkeypatch):
    monkeypatch.setenv(CANARY_NAME, CANARY_VALUE)
    code = source(
        """
        import json, os
        print(json.dumps(dict(os.environ)))
        """
    )

    result = runner.run(code, 20)

    visible = json.loads(result.stdout)
    host_only = set(os.environ) - {"PATH", "HOME", "LANG", "HOSTNAME"}
    assert CANARY_NAME not in visible
    assert CANARY_VALUE not in result.stdout
    assert not host_only & set(visible)


def test_canary_is_not_found_in_process_listing_or_files(runner, monkeypatch):
    monkeypatch.setenv(CANARY_NAME, CANARY_VALUE)
    code = source(
        """
        import os
        needle = b'sbx-canary-value-5f3a9c'
        hits = []
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                if needle in open(f'/proc/{pid}/environ', 'rb').read():
                    hits.append(pid)
            except OSError:
                pass
        print(hits)
        """
    )

    result = runner.run(code, 20)

    assert result.stdout.strip() == "[]"
