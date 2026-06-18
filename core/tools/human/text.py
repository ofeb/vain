"""text formatting and manipulation helpers.
shorten join ordinal plural and markdown utils.
all functions are pure no side effects"""

from typing import Optional, Sequence, Union


def join(seq: Sequence[str], delim: str = ", ", final: str = "or", md: str = "") -> str:
    """join a list of strings with a final word.
    eg join(['a','b','c']) returns 'a, b or c'.
    md wraps each item eg backtick for code"""
    n = len(seq)
    if n == 0:
        return ""
    if n == 1:
        return f"{md}{seq[0]}{md}"
    if n == 2:
        return f"{md}{seq[0]}{md} {final} {md}{seq[1]}{md}"
    return delim.join(f"{md}{i}{md}" for i in seq[:-1]) + f" {final} {md}{seq[-1]}{md}"


def shorten(value: str, length: int = 20) -> str:
    """truncate string and add .. if too long"""
    if len(value) > length:
        return value[: length - 2].rstrip() + ".."
    return value


def ordinal(n: int) -> str:
    """convert int to ordinal string eg 1st 2nd 3rd"""
    n = int(n)
    return "%d%s" % (n, "tsnrhtdd"[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10 :: 4])


def plural(value: Union[int, list], singular: str, plural_form: str = None) -> str:
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
