from __future__ import annotations

from collections.abc import Sequence


def human_join(
    seq: Sequence[str],
    delim: str = ", ",
    final: str = "or",
    markdown: str | None = None,
) -> str:
    items = [str(item) for item in seq if str(item)]
    if markdown:
        items = [f"{markdown}{item}{markdown}" for item in items]

    size = len(items)
    if size == 0:
        return ""
    if size == 1:
        return items[0]
    if size == 2:
        return f"{items[0]} {final} {items[1]}"
    return f"{delim.join(items[:-1])} {final} {items[-1]}"
