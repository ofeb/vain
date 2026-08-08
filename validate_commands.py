
"""Static validation for Vain commands — no Discord connection required.

Checks:
  - all ext packages import without syntax/import errors (best-effort)
  - command callbacks have coherent signatures
  - embed/container/plain script helpers behave
  - caption helper is idempotent
  - builders module loads
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)
    print(f"ERROR: {msg}")


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"WARN:  {msg}")


def ok(msg: str) -> None:
    print(f"OK:    {msg}")


def check_syntax() -> None:
    py_files = list((ROOT / "ext").rglob("*.py")) + list((ROOT / "core").rglob("*.py"))
    bad = 0
    bom_fixed = 0
    for path in py_files:
        if "__pycache__" in path.parts:
            continue
        try:
            raw = path.read_bytes()
            
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
                bom_fixed += 1
            src = raw.decode("utf-8")
            ast.parse(src, filename=str(path))
        except SyntaxError as e:
            bad += 1
            err(f"syntax {path.relative_to(ROOT)}:{e.lineno}: {e.msg}")
        except Exception as e:
            bad += 1
            err(f"read {path.relative_to(ROOT)}: {e}")
    if bom_fixed:
        warn(f"stripped BOM mentally for {bom_fixed} files (not rewritten)")
    if bad == 0:
        ok(f"syntax clean across {len(py_files)} python files")


def check_embed_helpers() -> None:
    from core.tools.embed import (
        is_container_script,
        is_embed_script,
        maybe_wrap_embed_script,
        parse,
        Script,
    )
    from core.discord.views.embed import caption

    assert caption("-# -# hi") == "-# hi"
    assert caption("-# hi") == "-# hi"
    assert caption("hi") == "-# hi"
    assert maybe_wrap_embed_script("hello world") == "hello world"
    assert maybe_wrap_embed_script("welcome {user.mention}") == "welcome {user.mention}"
    assert maybe_wrap_embed_script("{title: x}").startswith("{embed}")
    assert is_container_script("{container}$v{description: x}")
    assert not is_embed_script("{container}$v{description: x}")
    assert is_embed_script("{embed}$v{title: T}")
    assert not is_embed_script("plain text")

    async def _run():
        p = await parse(
            "{container}$v{title: Hello}$v{description: World}"
            "$v{footer: -# already}$v{color: #5865F2}"
            "$v{button: https://discord.com && Click}",
            sendable=True,
        )
        assert "view" in p
        p2 = await parse(
            "{embed}$v{title: T}$v{description: D}"
            "$v{field: A && B && inline}"
            "$v{button: https://discord.com && Go}",
            sendable=True,
        )
        assert p2.get("embed") is not None
        s = Script("Welcome {user}!")
        d = await s.data(True)
        assert "content" in d
        s2 = Script("{title: Hi}$v{description: There}")
        d2 = await s2.data(True)
        assert d2.get("embed") is not None

    asyncio.run(_run())
    ok("embed/container/plain helpers")


def check_builders() -> None:
    from ext.social.proper import builders

    eb = builders.EmbedBuilderView(1, accent=0xE1D2DE)
    assert eb._to_script().startswith("{embed}")
    eb.data["title"] = "Hello"
    eb.data["description"] = "World"
    eb.fields.append({"name": "A", "value": "B", "inline": "1"})
    eb.buttons.append(
        {"label": "Go", "url": "https://discord.com", "emoji": "", "style": "url"}
    )
    script = eb._to_script()
    assert "{title:" in script or "title:" in script
    assert "button:" in script
    emb = eb._preview_embed()
    assert emb.title == "Hello"

    cb = builders.ContainerBuilderView(1, accent=0xE1D2DE)
    cb.data["title"] = "Hi"
    cb.data["description"] = "There"
    cb.data["divider"] = "1"
    cb.buttons.append(
        {"label": "X", "url": "https://discord.com", "emoji": "", "style": "url"}
    )
    assert cb._to_script().startswith("{container}")
    layout = cb._preview_container()
    assert layout is not None
    opts = cb._field_options()
    values = {o.value for o in opts}
    for needed in (
        "title",
        "description",
        "color",
        "author",
        "footer",
        "image",
        "thumbnail",
        "button",
        "divider",
        "field",
        "actionrow",
    ):
        if needed not in values:
            err(f"container builder missing select option: {needed}")
    ok(f"builders load; container options={sorted(values)}")


def check_command_ast() -> None:
    """Walk ext/**/*.py and ensure @command/@group decorated defs look sane."""
    issues = 0
    for path in (ROOT / "ext").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decos = []
            for d in node.decorator_list:
                name = ""
                if isinstance(d, ast.Name):
                    name = d.id
                elif isinstance(d, ast.Attribute):
                    name = d.attr
                elif isinstance(d, ast.Call):
                    f = d.func
                    if isinstance(f, ast.Name):
                        name = f.id
                    elif isinstance(f, ast.Attribute):
                        name = f.attr
                decos.append(name)
            if not any(
                n in {"command", "group", "hybrid", "hybrid_group"} for n in decos
            ):
                continue
            
            args = node.args
            pos = [a.arg for a in args.args]
            if not pos:
                err(f"{path.name}:{node.lineno} {node.name} has no args")
                issues += 1
                continue
            if pos[0] == "self" and len(pos) < 2:
                err(
                    f"{path.relative_to(ROOT)}:{node.lineno} "
                    f"{node.name} missing ctx parameter"
                )
                issues += 1
    if issues == 0:
        ok("command signatures look coherent")


def check_naughty_signature() -> None:
    from pathlib import Path
    import re

    src = (ROOT / "ext/moderation/__init__.py").read_text(encoding="utf-8")
    if 'name="naughty"' not in src:
        err("naughty command missing")
        return
    if 'aliases=["nsfw"]' not in src and "aliases=['nsfw']" not in src:
        err("naughty missing nsfw alias")
        return
    if "duration: str = None" not in src and "duration: str | None = None" not in src:
        warn("naughty duration param style unexpected")
    if "_naughty_tasks" not in src:
        err("naughty missing cancelable task map")
        return
    ok("naughty/nsfw present with timed toggle support")


def check_key_features() -> None:
    checks = {
        "autonuke change": "ext/moderation/extended/nuke/__init__.py",
        "sticky change": "ext/server/extended/stickymessage/__init__.py",
        "boost twoboosts": "ext/server/extended/boost/__init__.py",
        "leveling rank card": "ext/leveling/__init__.py",
        "tickets": "ext/tickets/__init__.py",
    }
    for label, rel in checks.items():
        path = ROOT / rel
        if not path.exists():
            err(f"missing {rel} ({label})")
            continue
        text = path.read_text(encoding="utf-8")
        if label == "autonuke change" and "autonuke_change" not in text:
            err("autonuke change group missing")
        elif label == "sticky change" and "stickymessage_change" not in text:
            err("stickymessage change group missing")
        elif label == "boost twoboosts" and "is_second" not in text:
            err("boost is_second dual-slot missing")
        elif label == "leveling rank card" and "generate_rank_card" not in text:
            err("generate_rank_card missing")
        else:
            ok(label)


def main() -> int:
    print("=== Vain static validation ===")
    check_syntax()
    try:
        check_embed_helpers()
    except Exception:
        err("embed helpers failed:\n" + traceback.format_exc())
    try:
        check_builders()
    except Exception:
        err("builders failed:\n" + traceback.format_exc())
    check_command_ast()
    check_naughty_signature()
    check_key_features()

    print()
    print(f"warnings: {len(WARNINGS)}")
    print(f"errors:   {len(ERRORS)}")
    if ERRORS:
        print("FAILED")
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
