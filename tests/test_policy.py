import pytest

from app.policy import DEFAULT_POLICY_PATH, check_code, load_policy


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def rules(code, policy):
    return [violation.rule for violation in check_code(code, policy)]


@pytest.mark.parametrize(
    "code",
    [
        "print('hello')",
        "import math\nprint(math.sqrt(16))",
        "from collections import Counter\nprint(Counter('aab'))",
        "import json\nprint(json.dumps({'a': 1}))",
        "def f(x):\n    return x * 2\nprint(f(21))",
        "print(open_count := 3)",
    ],
)
def test_harmless_code_is_allowed(policy, code):
    assert check_code(code, policy) == []


@pytest.mark.parametrize(
    "code",
    [
        "import os",
        "import os.path",
        "from os import path",
        "from os.path import join",
        "import subprocess, math",
        "import socket",
        "from urllib.request import urlopen",
        "import ctypes",
        "import importlib",
    ],
)
def test_forbidden_imports_are_blocked(policy, code):
    assert rules(code, policy) == ["forbidden_import"]


@pytest.mark.parametrize(
    "code",
    ["eval('1+1')", "exec('x = 1')", "compile('1', 'f', 'eval')", "__import__('os')", "input()"],
)
def test_forbidden_calls_are_blocked(policy, code):
    assert rules(code, policy) == ["forbidden_call"]


@pytest.mark.parametrize(
    "code",
    [
        "().__class__.__bases__[0].__subclasses__()",
        "f = lambda: 0\nf.__globals__",
        "f.__code__",
    ],
)
def test_escape_attributes_are_blocked(policy, code):
    assert "forbidden_attribute" in rules(code, policy)


def test_violations_carry_the_line_number_and_are_ordered(policy):
    code = "print(1)\nimport os\nx = 2\neval('x')\n"

    violations = check_code(code, policy)

    assert [(v.rule, v.line) for v in violations] == [
        ("forbidden_import", 2),
        ("forbidden_call", 4),
    ]
    assert "'os'" in violations[0].detail


def test_nested_violations_are_found(policy):
    code = "def run():\n    def inner():\n        import subprocess\n    return inner\n"

    assert rules(code, policy) == ["forbidden_import"]


def test_unparseable_code_is_blocked_fail_closed(policy):
    violations = check_code("def broken(:\n", policy)

    assert [v.rule for v in violations] == ["unparseable"]
    assert violations[0].line == 1


def test_null_bytes_are_blocked_fail_closed(policy):
    assert rules("print(1)\x00", policy) == ["unparseable"]


def test_the_static_check_can_be_bypassed_which_is_why_it_is_not_the_boundary(policy):
    code = "mod = getattr(__builtins__, 'ev' + 'al')\n"

    assert rules(code, policy) == []


def test_default_policy_file_loads():
    policy = load_policy(DEFAULT_POLICY_PATH)

    assert {"os", "subprocess", "socket"} <= policy.forbidden_imports
    assert "eval" in policy.forbidden_calls


def test_custom_policy_file(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("forbidden_imports: [math]\n", encoding="utf-8")

    custom = load_policy(path)

    assert [v.rule for v in check_code("import math", custom)] == ["forbidden_import"]
    assert check_code("import os", custom) == []


@pytest.mark.parametrize(
    "content",
    [
        "forbidden_imports: os\n",
        "forbidden_imports: [1, 2]\n",
        "forbidden_imports: ['']\n",
        "unknown_key: []\n",
        "- a\n- b\n",
    ],
)
def test_invalid_policy_files_are_rejected(tmp_path, content):
    path = tmp_path / "policy.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        load_policy(path)
