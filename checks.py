"""i use ts and what r u gonna do ab it."""
import io
import re
import tokenize
from pathlib import Path

_KEEP = re.compile(
    r'#\s*(noqa|type:\s*(ignore|check|error|warning|var|arg|retval|func|'
    r'typed_dict|alias|overload|typed_dict_key|asserts|comment|reveal_type|'
    r'always|override))',
    re.IGNORECASE,
)


def _blm(source: str) -> list[int]:
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return offsets


def _commentstripper5000(source: str) -> str:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return source

    line_map = _blm(source)

    def to_pos(line: int, col: int) -> int:
        return line_map[line - 1] + col

    result_parts = []
    cursor = 0
    for tok in tokens:
        start_pos = to_pos(tok.start[0], tok.start[1])
        end_pos = to_pos(tok.end[0], tok.end[1])
        if start_pos > cursor:
            result_parts.append(source[cursor:start_pos])
        if tok.type == tokenize.COMMENT:
            if not _KEEP.search(tok.string):
                cursor = end_pos
                continue
        if tok.type == tokenize.ENDMARKER:
            cursor = end_pos
            continue
        result_parts.append(source[start_pos:end_pos])
        cursor = end_pos

    if cursor < len(source):
        result_parts.append(source[cursor:])

    return "".join(result_parts)


def fileravager2026(path: Path) -> bool:
    try:
        original = path.read_text(encoding="utf-8")
    except Exception:
        return False
    cleaned = _commentstripper5000(original)
    if cleaned != original:
        path.write_text(cleaned, encoding="utf-8")
        return True
    return False


def main():
    changed = []
    root = Path(".")
    for path in sorted(root.rglob("*.py")):
        if any(p in path.parts for p in ("venv", "__pycache__", ".git")):
            continue
        if fileravager2026(path):
            changed.append(path)
    if changed:
        print(f"Stripped comments from {len(changed)} files:")
        for p in changed:
            print(f"  {p}")
    else:
        print("No files had any # comments.")


if __name__ == "__main__":
    main()