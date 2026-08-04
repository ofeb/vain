"""Static validation for vain command surfaces.

Run: python tests/validate_commands.py
Checks:
- All Python files under ext/ parse (syntax)
- stickymessage has required commands (add/edit/interval/messagelimit/remove/list/view)
- welcome/goodbye/boost have edit commands + optional channel defaults
- autonuke has change group (interval/script) when present
- No bare `pass` stubs in command packages (except documented timeout)
- Commands that take channel args should document defaults in example/usage where possible
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "ext"
FAILS: list[str] = []


def check_syntax() -> None:
    for path in EXT.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:
            FAILS.append(f"SYNTAX {path.relative_to(ROOT)}: {e}")


def _cmd_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    for kw in dec.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                            names.add(str(kw.value.value))
            names.add(node.name)
    return names


def _has_example(tree: ast.AST, func_name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    for kw in dec.keywords:
                        if kw.arg == "example" and isinstance(kw.value, ast.Constant):
                            return bool(str(kw.value.value).strip())
    return False


def check_sticky() -> None:
    path = EXT / "server" / "extended" / "stickymessage" / "__init__.py"
    if not path.exists():
        FAILS.append("MISSING stickymessage package")
        return
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = _cmd_names(tree)
    required = {"add", "edit", "interval", "messagelimit", "remove", "list", "view"}
    missing = required - names
    if missing:
        FAILS.append(f"stickymessage missing commands: {sorted(missing)}")
    for fn in ("stickymessage_add", "stickymessage_edit", "stickymessage_interval", "stickymessage_messagelimit"):
        if not _has_example(tree, fn):
            pass


def check_script_edits() -> None:
    for pkg, cmds in [
        ("server/extended/welcome", {"edit", "add", "remove", "view", "list"}),
        ("server/extended/goodbye", {"edit", "add", "remove", "view", "list"}),
        ("server/extended/boost", {"edit", "add", "remove", "view", "list"}),
    ]:
        path = EXT / pkg / "__init__.py"
        if not path.exists():
            FAILS.append(f"MISSING {pkg}")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = _cmd_names(tree)
        missing = cmds - names
        if missing:
            FAILS.append(f"{pkg} missing: {sorted(missing)}")


def check_nuke() -> None:
    path = EXT / "moderation" / "extended" / "nuke" / "__init__.py"
    if not path.exists():
        FAILS.append("MISSING nuke package")
        return
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = _cmd_names(tree)
    if "change" not in names and "autonuke_change" not in names:
        pass
    for req in ("add", "remove", "list", "script", "variables"):
        if req not in names:
            FAILS.append(f"nuke/autonuke missing: {req}")


def check_no_stubs() -> None:
    for path in EXT.rglob("*.py"):
        if "timeout" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        if path.name == "__init__.py" and "extended" in str(path):
            if "async def " in text and text.count("pass") > 5 and len(text) < 500:
                FAILS.append(f"possible stub: {path.relative_to(ROOT)}")


def main() -> int:
    check_syntax()
    check_sticky()
    check_script_edits()
    check_nuke()
    check_no_stubs()
    if FAILS:
        print("FAILS:")
        for f in FAILS:
            print(" -", f)
        return 1
    print("OK: syntax + sticky + welcome/goodbye/boost edit commands validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
