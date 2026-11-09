import ast
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.schemas import Violation

DEFAULT_POLICY_PATH = Path(__file__).parent / "policy.yaml"
POLICY_KEYS = {"forbidden_imports", "forbidden_calls", "forbidden_attributes"}


@dataclass(frozen=True)
class Policy:
    forbidden_imports: frozenset[str]
    forbidden_calls: frozenset[str]
    forbidden_attributes: frozenset[str]


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> Policy:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("The policy file must contain a mapping.")
    unknown = set(data) - POLICY_KEYS
    if unknown:
        raise ValueError(f"Unknown policy keys: {', '.join(sorted(unknown))}.")
    values = {}
    for key in POLICY_KEYS:
        items = data.get(key, [])
        if not isinstance(items, list) or not all(isinstance(item, str) and item for item in items):
            raise ValueError(f"{key} must be a list of non-empty strings.")
        values[key] = frozenset(items)
    return Policy(**values)


class Checker(ast.NodeVisitor):
    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.violations: list[Violation] = []

    def add(self, rule: str, detail: str, node: ast.AST) -> None:
        self.violations.append(
            Violation(rule=rule, detail=detail, line=getattr(node, "lineno", None))
        )

    def check_module(self, name: str, node: ast.AST) -> None:
        root = name.split(".")[0]
        if root in self.policy.forbidden_imports:
            self.add("forbidden_import", f"Importing '{root}' is not allowed.", node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.check_module(alias.name, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.check_module(node.module, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in self.policy.forbidden_calls:
            self.add("forbidden_call", f"Calling '{node.func.id}' is not allowed.", node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in self.policy.forbidden_attributes:
            self.add("forbidden_attribute", f"Accessing '{node.attr}' is not allowed.", node)
        self.generic_visit(node)


def check_code(code: str, policy: Policy) -> list[Violation]:
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError) as error:
        line = getattr(error, "lineno", None)
        return [Violation(rule="unparseable", detail="The code could not be parsed.", line=line)]
    checker = Checker(policy)
    checker.visit(tree)
    return sorted(checker.violations, key=lambda item: (item.line or 0, item.rule))
