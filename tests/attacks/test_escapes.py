import textwrap

import pytest

from app.docker_runner import DockerRunner

pytestmark = pytest.mark.docker

CANARY_FILE = "sbx-host-canary.txt"
CANARY_TEXT = "sbx-host-canary-content-27ac"


def source(text):
    return textwrap.dedent(text)


@pytest.fixture(scope="module")
def runner(sandbox_image):
    return DockerRunner(image=sandbox_image)


def test_symlinks_cannot_reach_outside_the_container(runner):
    code = source(
        """
        import os
        os.symlink('/', '/tmp/rootlink')
        os.symlink('/proc/1/root', '/tmp/initroot')
        os.symlink('/etc/shadow', '/tmp/shadow')
        results = []
        for path in ('/tmp/rootlink/etc/shadow', '/tmp/initroot/etc/shadow', '/tmp/shadow'):
            try:
                open(path).read()
                results.append('read')
            except OSError as error:
                results.append(error.errno)
        try:
            open('/tmp/rootlink/escape', 'w').write('x')
            results.append('written')
        except OSError as error:
            results.append(error.errno)
        print(results)
        """
    )

    result = runner.run(code, 20)

    assert "read" not in result.stdout
    assert "written" not in result.stdout
    assert result.stdout.strip() == "[13, 13, 13, 30]"


def test_no_host_mounts_or_docker_socket_are_visible(runner):
    code = source(
        """
        import os
        mounts = open('/proc/self/mountinfo').read().splitlines()
        sources = [line.split(' - ')[1].split()[1] for line in mounts]
        suspicious = [
            line for line in mounts
            if any(token in line for token in ('/host_mnt', '/run/desktop', 'docker.sock', 'C:'))
        ]
        print(suspicious)
        print(sorted(set(sources)))
        for path in ('/var/run/docker.sock', '/run/docker.sock', '/host_mnt', '/mnt/host', '/c'):
            print(path, os.path.exists(path))
        """
    )

    result = runner.run(code, 20)

    lines = result.stdout.splitlines()
    assert lines[0] == "[]"
    assert all(line.endswith("False") for line in lines[2:])


def test_host_files_are_not_found_anywhere(runner, tmp_path):
    (tmp_path / CANARY_FILE).write_text(CANARY_TEXT, encoding="utf-8")
    code = source(
        """
        import os
        hits = []
        for root, directories, files in os.walk('/'):
            skip = ('/proc', '/sys')
            directories[:] = [d for d in directories if os.path.join(root, d) not in skip]
            if 'sbx-host-canary.txt' in files:
                hits.append(root)
        print(hits)
        """
    )

    result = runner.run(code, 60)

    assert result.stdout.strip() == "[]"
