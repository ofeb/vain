"""Regex / token name matching for roles, members, channels, threads, etc.

Handles decorative names like ``ʚ .  own``, ``・boost・``, ``『VIP』`` by:

1. Exact match (case-insensitive)
2. Starts-with
3. Substring contains
4. **Word-token match** — strips symbols/emoji/punctuation, splits alphanumerics,
   then matches the query as a whole word (``own`` → ``ʚ .  own``, not ``owner``
   unless no better hit)
5. Compact alnum contains (``boost`` in ``ʚ.boost.role``)
6. Fuzzy closest match (optional)

Priority prefers shorter / more exact names so ``own`` picks ``ʚ .  own`` over
``ownership`` when both match.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence, TypeVar

T = TypeVar("T")

try:
    from fast_string_match import closest_match as _closest_match
except ImportError:  

    def _closest_match(query: str, candidates: Sequence[str]):  # type: ignore
        q = (query or "").lower()
        if not q:
            return None
        for c in candidates:
            if c.lower() == q:
                return c
        for c in candidates:
            if c.lower().startswith(q):
                return c
        for c in candidates:
            if q in c.lower():
                return c
        return None



_INVISIBLE_RE = re.compile(
    "[​-‏‪-‮⁠-⁤﻿­]"
)


_EDGE_JUNK_RE = re.compile(r"^[\s@#.<\>\"'`|]+|[\s@#.<\>\"'`|]+$")


_NON_ALNUM_RE = re.compile(r"[^\w]+", re.UNICODE)


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def clean_query(token: str | None) -> str:
    """Strip invisible chars, mention junk, surrounding punctuation."""
    raw = _INVISIBLE_RE.sub("", str(token or "")).strip()
    raw = raw.strip("`\"'")
    prev = None
    while prev != raw:
        prev = raw
        raw = _EDGE_JUNK_RE.sub("", raw)
    while raw.startswith(("@", "#")):
        raw = raw[1:].lstrip()
    return raw.strip()


def normalize_name(name: str | None) -> str:
    """Lowercase + NFKC + strip invisibles for comparisons."""
    text = _INVISIBLE_RE.sub("", str(name or ""))
    text = unicodedata.normalize("NFKC", text)
    return text.casefold().strip()


def compact_alnum(name: str | None) -> str:
    """Only alphanumeric characters, lowercased (for ``ʚ.boost.`` → ``boost``)."""
    text = normalize_name(name)
    return _NON_ALNUM_RE.sub("", text)


def name_tokens(name: str | None) -> list[str]:
    """Alphanumeric word tokens from a decorative name."""
    text = normalize_name(name)
    
    text = text.replace("_", " ")
    return [t for t in _TOKEN_RE.findall(text) if t]


def _query_tokens(query: str) -> list[str]:
    q = normalize_name(query)
    q = q.replace("_", " ")
    tokens = [t for t in _TOKEN_RE.findall(q) if t]
    if tokens:
        return tokens
    compact = compact_alnum(query)
    return [compact] if compact else []


@dataclass(frozen=True, slots=True)
class _Scored:
    score: int
    length: int
    item: object


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _word_boundary_prefix(name: str, query: str) -> bool:
    """True if *name* starts with *query* as a whole word (not ``own``→``ownership``)."""
    if not name.startswith(query):
        return False
    if len(name) == len(query):
        return True
    return not _is_word_char(name[len(query)])


def _word_boundary_contains(name: str, query: str) -> bool:
    """True if *query* appears in *name* as a whole word (bounded by non-word chars).

    ``own`` in ``my own role`` → True; ``own`` in ``ownership`` → False.
    """
    start = 0
    while True:
        idx = name.find(query, start)
        if idx < 0:
            return False
        before_ok = idx == 0 or not _is_word_char(name[idx - 1])
        end = idx + len(query)
        after_ok = end >= len(name) or not _is_word_char(name[end])
        if before_ok and after_ok:
            return True
        start = idx + 1


def score_name(query: str, name: str | None) -> int | None:
    """Return a match score (lower is better) or None if no match.

    Score bands:
      0   exact (casefold)
      10  exact compact alnum
      20  query is an exact word-token in the name (``own`` → ``ʚ .  own``)
      30  all query tokens appear as tokens in the name
      40  starts-with as a whole word
      50  full name contains query as a whole word
      60  compact name contains compact query
      70  query token is a prefix of a name token (``own`` → ``owner`` only here)
    """
    q_raw = clean_query(query)
    if not q_raw:
        return None
    n_raw = str(name or "")
    if not n_raw:
        return None

    q = normalize_name(q_raw)
    n = normalize_name(n_raw)
    if not q or not n:
        return None

    if n == q:
        return 0

    q_compact = compact_alnum(q_raw)
    n_compact = compact_alnum(n_raw)
    if q_compact and n_compact == q_compact:
        return 10

    n_tokens = name_tokens(n_raw)
    q_tokens = _query_tokens(q_raw)

    if q_tokens and n_tokens:
        
        if len(q_tokens) == 1 and q_tokens[0] in n_tokens:
            return 20
        
        if len(q_tokens) > 1 and all(t in n_tokens for t in q_tokens):
            return 30

    
    if _word_boundary_prefix(n, q):
        return 40

    
    if _word_boundary_contains(n, q):
        return 50

    if q_compact and q_compact in n_compact and n_compact != q_compact:
        
        
        
        if not (
            q_tokens
            and n_tokens
            and all(any(nt.startswith(qt) for nt in n_tokens) for qt in q_tokens)
        ):
            return 60

    
    if q_tokens and n_tokens:
        if all(any(nt.startswith(qt) for nt in n_tokens) for qt in q_tokens):
            return 70

    
    if q_compact and q_compact in n_compact:
        return 80

    return None


def regex_find(
    query: str,
    items: Iterable[T],
    *,
    names_of: Callable[[T], Sequence[str | None]],
    fuzzy: bool = True,
) -> Optional[T]:
    """Pick the best item whose name(s) match *query* via token/regex scoring.

    ``names_of`` should return one or more display strings per item
    (e.g. role name; member name + display_name + global_name).
    """
    q = clean_query(query)
    if not q:
        return None

    scored: list[_Scored] = []
    fuzzy_map: dict[str, T] = {}

    for item in items:
        best: int | None = None
        best_len = 10_000
        for name in names_of(item):
            if not name:
                continue
            s = score_name(q, name)
            length = len(str(name))
            if s is not None and (
                best is None or s < best or (s == best and length < best_len)
            ):
                best = s
                best_len = length
            key = normalize_name(name)
            if key and key not in fuzzy_map:
                fuzzy_map[key] = item
        if best is not None:
            scored.append(_Scored(best, best_len, item))

    if scored:
        scored.sort(key=lambda x: (x.score, x.length))
        return scored[0].item  # type: ignore[return-value]

    if fuzzy and fuzzy_map:
        hit = _closest_match(normalize_name(q), list(fuzzy_map.keys()))
        if hit and hit in fuzzy_map:
            return fuzzy_map[hit]

    return None


def regex_findall(
    query: str,
    items: Iterable[T],
    *,
    names_of: Callable[[T], Sequence[str | None]],
    limit: int = 25,
) -> list[T]:
    """All matches sorted best-first (for disambiguation UIs)."""
    q = clean_query(query)
    if not q:
        return []

    scored: list[_Scored] = []
    seen: set[int] = set()
    for item in items:
        best: int | None = None
        best_len = 10_000
        for name in names_of(item):
            s = score_name(q, name)
            if s is None:
                continue
            length = len(str(name or ""))
            if best is None or s < best or (s == best and length < best_len):
                best = s
                best_len = length
        if best is None:
            continue
        ident = id(item)
        if ident in seen:
            continue
        seen.add(ident)
        scored.append(_Scored(best, best_len, item))

    scored.sort(key=lambda x: (x.score, x.length))
    return [s.item for s in scored[:limit]]  # type: ignore[misc]
