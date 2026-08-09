"""text formatting and manipulation helpers.
shorten join ordinal plural and markdown utils.
all functions are pure no side effects"""

from typing import Sequence, Union


def join(
    seq: Sequence[str],
    delim: str = ", ",
    final: str = "or",
    md: str = "",
    *,
    markdown: str | None = None,
) -> str:
    """join a list of strings with a final word.
    eg join(['a','b','c']) returns 'a, b or c'.
    md/markdown wraps each item eg backtick for code"""
    wrap = markdown if markdown is not None else md
    items = [str(item) for item in seq if str(item)]
    n = len(items)
    if n == 0:
        return ""
    if n == 1:
        return f"{wrap}{items[0]}{wrap}"
    if n == 2:
        return f"{wrap}{items[0]}{wrap} {final} {wrap}{items[1]}{wrap}"
    return (
        delim.join(f"{wrap}{i}{wrap}" for i in items[:-1])
        + f" {final} {wrap}{items[-1]}{wrap}"
    )



human_join = join


def shorten(value: str, length: int = 20) -> str:
    """truncate string and add .. if too long"""
    if len(value) > length:
        return value[: length - 2].rstrip() + ".."
    return value


def ordinal(n: int) -> str:
    """convert int to ordinal string eg 1st 2nd 3rd"""
    n = int(n)
    return "%d%s" % (n, "tsnrhtdd"[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10 :: 4])


def humanize_duration(seconds: int) -> str:
    """Humanize a duration in seconds: 3600 -> 'an hour', 300 -> '5 minutes'."""
    seconds = max(0, int(seconds))
    if seconds == 0:
        return "0 seconds"
    units = (
        ("year", 31_536_000),
        ("week", 604_800),
        ("day", 86_400),
        ("hour", 3_600),
        ("minute", 60),
        ("second", 1),
    )
    parts: list[str] = []
    for name, size in units:
        count, seconds = divmod(seconds, size)
        if not count:
            continue
        if count == 1:
            parts.append(("an" if name == "hour" else "a") + f" {name}")
        else:
            parts.append(f"{count} {name}s")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def plural(value: Union[int, list], singular: str, plural_form: str | None = None) -> str:
    """return singular or plural word based on count"""
    count = len(value) if isinstance(value, list) else value
    word = plural_form or f"{singular}s"
    return f"{count} {singular if abs(count) == 1 else word}"


def percentage(lowest: float, highest: float = 100) -> str:
    """format a ratio as percentage string"""
    return "%.0f%%" % int((lowest / highest) * 100)


def codeblock(text: str, lang: str = "") -> str:
    """wrap text in a discord codeblock"""
    return f"```{lang}\n{text}\n```"


def hyperlink(text: str, url: str) -> str:
    """make a discord markdown hyperlink"""
    return f"[{text}]({url})"
