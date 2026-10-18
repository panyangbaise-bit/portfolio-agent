"""Executable dependency rules: backend modules must not depend on the UI."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ("agent", "adapters", "db", "scheduler", "notifier", "memory", "a2a", "common", "domain")


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


@pytest.mark.parametrize("package", BACKEND)
def test_backend_does_not_import_presentation(package):
    violations = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in (ROOT / package).rglob("*.py")
        for name in imports(path)
        if name.split(".")[0] in {"app", "streamlit"}
    ]
    assert not violations, "\n".join(violations)


def test_domain_is_independent_of_application_and_io():
    forbidden = set(BACKEND) - {"domain"} | {
        "config",
        "runtime",
        "requests",
        "sqlalchemy",
        "langchain",
        "langgraph",
    }
    violations = [
        f"{path.name}: {name}"
        for path in (ROOT / "domain").glob("*.py")
        for name in imports(path)
        if name.split(".")[0] in forbidden
    ]
    assert not violations, "\n".join(violations)
