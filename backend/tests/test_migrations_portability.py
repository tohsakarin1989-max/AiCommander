import ast
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_boolean_server_defaults_are_database_portable():
    invalid: list[str] = []
    for path in VERSIONS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != "Column":
                continue
            if not any(_call_name(argument) == "Boolean" for argument in node.args):
                continue
            default = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "server_default"),
                None,
            )
            if isinstance(default, ast.Constant) and default.value in {"0", "1"}:
                invalid.append(f"{path.name}:{node.lineno}")
            if (
                _call_name(default) == "text"
                and default.args
                and isinstance(default.args[0], ast.Constant)
                and default.args[0].value in {"0", "1"}
            ):
                invalid.append(f"{path.name}:{node.lineno}")

    assert invalid == [], f"布尔默认值必须使用 sa.true()/sa.false(): {invalid}"
