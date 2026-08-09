from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from core.networks.web import get_bytes, get_json

log = logging.getLogger("vain.roleplay.media")

_TIMEOUT = 12

_OTAKUGIFS_ENDPOINT = "https://api.otakugifs.xyz/gif"


_VALID_REACTIONS: frozenset[str] = frozenset(
    {
        "airkiss",
        "angrystare",
        "bite",
        "bleh",
        "blush",
        "brofist",
        "celebrate",
        "cheers",
        "clap",
        "confused",
        "cool",
        "cry",
        "cuddle",
        "dance",
        "drool",
        "evillaugh",
        "facepalm",
        "handhold",
        "happy",
        "headbang",
        "hug",
        "huh",
        "kiss",
        "laugh",
        "lick",
        "love",
        "mad",
        "nervous",
        "no",
        "nom",
        "nosebleed",
        "nuzzle",
        "nyah",
        "pat",
        "peek",
        "pinch",
        "poke",
        "pout",
        "punch",
        "roll",
        "run",
        "sad",
        "scared",
        "shout",
        "shrug",
        "shy",
        "sigh",
        "sing",
        "sip",
        "slap",
        "sleep",
        "slowclap",
        "smack",
        "smile",
        "smug",
        "sneeze",
        "sorry",
        "stare",
        "stop",
        "surprised",
        "sweat",
        "thumbsup",
        "tickle",
        "tired",
        "wave",
        "wink",
        "woah",
        "yawn",
        "yay",
        "yes",
    }
)

_REACTION_ALIASES: dict[str, str] = {
    "headpat": "pat",
    "headpats": "pat",
    "pats": "pat",
    "highfive": "brofist",
    "high-five": "brofist",
    "high_five": "brofist",
    "kick": "smack",
    "kicks": "smack",
}

_OTAKUGIFS_ACTIONS: frozenset[str] = _VALID_REACTIONS | frozenset(_REACTION_ALIASES)

_NEKOSBEST_ACTIONS: frozenset[str] = frozenset(
    {
        "bleh",
        "bite",
        "blush",
        "clap",
        "confused",
        "cry",
        "cuddle",
        "dance",
        "facepalm",
        "happy",
        "highfive",
        "hug",
        "kick",
        "kiss",
        "laugh",
        "nom",
        "pat",
        "poke",
        "pout",
        "punch",
        "run",
        "shoot",
        "shrug",
        "sip",
        "sleep",
        "slap",
        "smile",
        "smug",
        "stare",
        "thumbsup",
        "tickle",
        "wave",
        "wink",
        "yawn",
    }
)

_NEKOSLIFE_ACTIONS: frozenset[str] = frozenset(
    {"cuddle", "hug", "kiss", "pat", "slap", "smug", "tickle"}
)


def resolve_reaction(action: str) -> str:
    """Map a roleplay action name to a valid otakugifs reaction."""
    key = (action or "").strip().lower()
    if key in _REACTION_ALIASES:
        return _REACTION_ALIASES[key]
    if key in _VALID_REACTIONS:
        return key

    return "pat"


async def _otakugifs(action: str) -> bytes:
    reaction = resolve_reaction(action)
    payload = await get_json(
        _OTAKUGIFS_ENDPOINT,
        params={"reaction": reaction},
        timeout=_TIMEOUT,
    )
    return await get_bytes(payload["url"], timeout=_TIMEOUT)


async def _nekos_best(action: str) -> bytes:
    payload = await get_json(
        f"https://nekos.best/api/v2/{action}",
        timeout=_TIMEOUT,
    )
    return await get_bytes(payload["results"][0]["url"], timeout=_TIMEOUT)


async def _nekos_life(action: str) -> bytes:
    payload = await get_json(
        f"https://nekos.life/api/v2/img/{action}",
        timeout=_TIMEOUT,
    )
    return await get_bytes(payload["url"], timeout=_TIMEOUT)


_FETCHERS: dict[str, Callable[[str], Awaitable[bytes]]] = {
    "otakugifs": _otakugifs,
    "nekos.best": _nekos_best,
    "nekos.life": _nekos_life,
}


def _sources_for(action: str) -> list[tuple[str, Callable[[str], Awaitable[bytes]]]]:
    """Ordered (name, fetcher) chain for an action, main source first."""
    if action in _OTAKUGIFS_ACTIONS:
        yield ("otakugifs", _otakugifs)
    if action in _NEKOSBEST_ACTIONS:
        yield ("nekos.best", _nekos_best)
    if action in _NEKOSLIFE_ACTIONS:
        yield ("nekos.life", _nekos_life)


async def fetch_action_gif(action: str) -> bytes:
    """
    Return the raw bytes of a reaction GIF for action.

    Sources are tried in order (otakugifs -> nekos.best -> nekos.life). Each
    source hands back a JSON document pointing at the real asset, which we then
    download. We only cycle to the next source when the current one fails.
    """
    action = (action or "").strip().lower()
    last_error: Exception | None = None
    tried: list[str] = []
    for name, fetcher in _sources_for(action):
        tried.append(name)
        try:
            return await asyncio.wait_for(fetcher(action), timeout=_TIMEOUT + 5)
        except Exception as error:
            last_error = error
            log.warning(
                "roleplay source %s failed for %r: %s", name, action, error,
            )
    raise RuntimeError(
        f"no GIF source available for {action!r} (tried: {', '.join(tried) or 'none'})"
    ) from last_error
