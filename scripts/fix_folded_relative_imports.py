"""Fix relative imports broken by folding <pkg>/<pkg>.py into <pkg>/__init__.py.

Examples:
  ext/level/events:  from ..level import X  -> from .. import X
  ext/server/extended/autoresponder/events: from ..autoresponder import X -> from .. import X
  from ..foo.foo import X -> from ..foo import X  (when foo.py was folded)
"""

from __future__ import annotations

import re
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "ext"


def fix_file(path: Path) -> list[str]:
    original = path.read_text(encoding="utf-8-sig")
    changes: list[str] = []
    out: list[str] = []

    for line in original.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        m = re.match(r"^(\s*)from\s+(\.+)([\w.]+)\s+import\s+(.+)$", raw)
        if not m:
            out.append(line)
            continue

        indent, dots, modpath, imports = m.groups()
        segs = modpath.split(".")

        # Resolve filesystem target of the relative import
        # File package = path.parent; N leading dots means go up N-1 from that package
        base = path.parent
        for _ in range(len(dots) - 1):
            base = base.parent

        target = base
        for s in segs:
            target = target / s
        py = Path(str(target) + ".py")
        pkg = target / "__init__.py"

        if py.exists() or pkg.exists():
            out.append(line)
            continue

        # 1) from ..level import X when symbols live on parent package package __init__
        #    target would be base/level which doesn't exist; base itself is the package
        #    named `level` and segs == [base.name]
        if len(segs) == 1 and segs[0] == base.name and (base / "__init__.py").exists():
            # from ..level import X  -> from .. import X
            newline = f"{indent}from {dots} import {imports}\n"
            if line.endswith("\r\n"):
                newline = newline[:-1] + "\r\n"
            out.append(newline)
            changes.append(f"{path.relative_to(EXT)}: from {dots}{modpath} -> from {dots}")
            continue

        # 2) from ..foo.foo import when foo was folded into package
        if len(segs) >= 2 and segs[-1] == segs[-2]:
            target2 = base
            for s in segs[:-1]:
                target2 = target2 / s
            if (target2 / "__init__.py").exists() or Path(str(target2) + ".py").exists():
                new_mod = ".".join(segs[:-1])
                newline = f"{indent}from {dots}{new_mod} import {imports}\n"
                if line.endswith("\r\n"):
                    newline = newline[:-1] + "\r\n"
                out.append(newline)
                changes.append(
                    f"{path.relative_to(EXT)}: strip dup {modpath} -> {new_mod}"
                )
                continue

        # 3) from .level import inside package that was folded (same package)
        #    e.g. from .level import X in ext/level/something - rare
        if not py.exists() and not pkg.exists():
            # try: last segment equals parent of target's intended package
            pass

        out.append(line)

    result = "".join(out)
    if result != original:
        path.write_text(result, encoding="utf-8")
    return changes


def report_missing() -> list[str]:
    missing: list[str] = []
    for path in EXT.rglob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        for i, line in enumerate(text.splitlines(), 1):
            m = re.match(r"^\s*from\s+(\.+)([\w.]+)\s+import\s+", line)
            if not m:
                continue
            dots, modpath = m.group(1), m.group(2)
            base = path.parent
            for _ in range(len(dots) - 1):
                base = base.parent
            target = base
            for s in modpath.split("."):
                target = target / s
            py = Path(str(target) + ".py")
            pkg = target / "__init__.py"
            if not py.exists() and not pkg.exists():
                # also allow import of symbols from base itself via wrong path already fixed
                missing.append(f"{path.relative_to(EXT)}:{i}: {line.strip()}")
    return missing


def main() -> None:
    all_changes: list[str] = []
    for path in EXT.rglob("*.py"):
        all_changes.extend(fix_file(path))

    for c in all_changes:
        print(c)
    print(f"\ndone: {len(all_changes)} changes")

    missing = report_missing()
    print(f"\nremaining missing targets: {len(missing)}")
    for m in missing:
        print(m)


if __name__ == "__main__":
    main()
