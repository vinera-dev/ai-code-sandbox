import json
import os
import textwrap
import time

import pytest

from app.docker_runner import DockerRunner
from tests.conftest import leftover_containers

pytestmark = pytest.mark.docker

CANARY_NAME = "SBX_ATTACK_CANARY"
CANARY_VALUE = "sbx-attack-canary-81d2e6"


def source(text):
    return textwrap.dedent(text)


@pytest.fixture(scope="module")
def runner(sandbox_image):
    return DockerRunner(image=sandbox_image)


def test_fork_bomb_is_contained(runner):
    code = source(
        """
        import os, time
        spawned = 0
        try:
            while True:
                if os.fork() == 0:
                    time.sleep(60)
                    os._exit(0)
                spawned += 1
        except OSError as error:
            print(spawned, error.errno, flush=True)
        os._exit(0)
        """
    )

    result = runner.run(code, 30)

    spawned, errno = (int(value) for value in result.stdout.split())
    assert errno == 11
    assert spawned < 64
    assert leftover_containers() == []


def test_outbound_traffic_is_blocked(runner):
    code = source(
        """
        import socket
        targets = [('1.1.1.1', 80), ('10.0.0.1', 80), ('192.168.1.1', 80), ('169.254.169.254', 80)]
        outcomes = []
        for target in targets:
            try:
                socket.create_connection(target, timeout=2).close()
                outcomes.append('open')
            except OSError:
                outcomes.append('closed')
        try:
            socket.getaddrinfo('example.org', 80)
            outcomes.append('resolved')
        except OSError:
            outcomes.append('unresolved')
        print(outcomes)
        """
    )

    result = runner.run(code, 30)

    assert result.stdout.strip() == "['closed', 'closed', 'closed', 'closed', 'unresolved']"


def test_writing_to_the_root_filesystem_fails(runner):
    code = source(
        """
        import os
        results = {}
        for path in ('/pwned', '/etc/passwd', '/usr/local/bin/python3', '/bin/sh'):
            try:
                open(path, 'a').write('x')
                results[path] = 'written'
            except OSError as error:
                results[path] = error.errno
        try:
            os.mkdir('/newdir')
            results['/newdir'] = 'created'
        except OSError as error:
            results['/newdir'] = error.errno
        print(sorted(set(results.values()), key=str))
        """
    )

    result = runner.run(code, 20)

    assert result.stdout.strip() in {"[13, 30]", "[13]", "[30]"}


def test_proc_does_not_expose_the_host(runner):
    code = source(
        """
        import os
        pids = [name for name in os.listdir('/proc') if name.isdigit()]
        print(len(pids) <= 3)
        try:
            print(len(open('/proc/kcore', 'rb').read(16)))
        except OSError as error:
            print(error.errno)
        try:
            open('/proc/sys/kernel/hostname', 'w').write('pwned')
            print('written')
        except OSError as error:
            print(error.errno)
        """
    )

    result = runner.run(code, 20)

    pid_check, kcore, hostname = result.stdout.split()
    assert pid_check == "True"
    assert kcore in {"0", "13"}
    assert hostname in {"13", "30"}


def test_service_secrets_are_not_readable(runner, monkeypatch):
    monkeypatch.setenv(CANARY_NAME, CANARY_VALUE)
    code = source(
        """
        import json, os
        found = dict(os.environ)
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                found[pid] = open(f'/proc/{pid}/environ', 'rb').read().decode(errors='replace')
            except OSError:
                pass
        print(json.dumps(found))
        """
    )

    result = runner.run(code, 20)

    assert CANARY_VALUE not in result.stdout
    assert CANARY_NAME not in json.loads(result.stdout)
    assert not (set(os.environ) - {"PATH", "HOME", "LANG", "HOSTNAME"}) & set(
        json.loads(result.stdout)
    )


def test_memory_exhaustion_is_killed(runner):
    code = source(
        """
        hoard = []
        while True:
            hoard.append(bytearray(64 * 1024 * 1024))
        """
    )

    result = runner.run(code, 30)

    assert result.exit_code == 137
    assert result.timed_out is False


def test_infinite_loop_is_terminated_on_time(runner):
    started = time.monotonic()

    result = runner.run("while True:\n    pass", 5)

    assert result.timed_out is True
    assert time.monotonic() - started < 5 + 10
    assert leftover_containers() == []


def test_privileged_operations_are_refused(runner):
    code = source(
        """
        import ctypes, os
        libc = ctypes.CDLL(None, use_errno=True)
        outcomes = []
        outcomes.append(libc.mount(b'none', b'/mnt', b'tmpfs', 0, None))
        outcomes.append(libc.ptrace(16, 1, 0, 0))
        outcomes.append(libc.unshare(0x10000000))
        outcomes.append(libc.chroot(b'/tmp'))
        try:
            os.setuid(0)
            outcomes.append(0)
        except PermissionError:
            outcomes.append(-1)
        print(outcomes)
        """
    )

    result = runner.run(code, 20)

    assert result.stdout.strip() == "[-1, -1, -1, -1, -1]"
