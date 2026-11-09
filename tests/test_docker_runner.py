import textwrap

import pytest

from app.docker_runner import DockerRunner

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
