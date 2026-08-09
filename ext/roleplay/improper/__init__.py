from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import aiohttp

from core.networks.web import get_bytes, get_json, get_session

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
}

_OTAKUGIFS_ACTIONS: frozenset[str] = _VALID_REACTIONS | frozenset(_REACTION_ALIASES)

_NEKOSBEST_ACTIONS: frozenset[str] = frozenset(
    {
        "angry",
        "baka",
        "bleh",
        "bite",
        "blowkiss",
        "blush",
        "bonk",
        "bored",
        "carry",
        "clap",
        "confused",
        "cry",
        "cuddle",
        "dance",
        "facepalm",
        "feed",
        "handshake",
        "happy",
        "highfive",
        "hug",
        "kabedon",
        "kick",
        "kiss",
        "lappillow",
        "laugh",
        "lurk",
        "nod",
        "nom",
        "nope",
        "nya",
        "pat",
        "peck",
        "poke",
        "pout",
        "punch",
        "run",
        "salute",
        "shake",
        "shocked",
        "shoot",
        "shrug",
        "sip",
        "sleep",
        "slap",
        "smile",
        "smug",
        "spin",
        "stare",
        "tableflip",
        "teehee",
        "think",
        "thumbsup",
        "tickle",
        "wag",
        "wave",
        "wink",
        "yawn",
        "yeet",
    }
)

_NEKOSLIFE_ACTIONS: frozenset[str] = frozenset(
    {"cuddle", "hug", "kiss", "pat", "slap", "smug", "tickle"}
)

_NEKOSBEST_PREFERRED: frozenset[str] = frozenset(
    {
        "angry",
        "baka",
        "blowkiss",
        "bonk",
        "bored",
        "carry",
        "feed",
        "handshake",
        "highfive",
        "kabedon",
        "kick",
        "lappillow",
        "lurk",
        "nod",
        "nope",
        "nya",
        "peck",
        "salute",
        "shake",
        "shocked",
        "shoot",
        "spin",
        "tableflip",
        "teehee",
        "think",
        "wag",
        "yeet",
    }
)

_NEKOSBEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
        "Gecko/20100101 Firefox/153.0"
    ),
}

_OTAKUGIFS_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
        "Gecko/20100101 Firefox/153.0"
    ),
}

_CURATED_GIFS: dict[str, tuple[str, ...]] = {
    "highfive": (
        "https://media1.tenor.com/m/tbGQf-3K6CYAAAAC/high-five-anime.gif",
        "https://media1.tenor.com/m/JBBZ9mQntx8AAAAC/anime-high-five.gif",
    ),
    "kick": (
        "https://media1.tenor.com/m/o52AZQZ_PloAAAAC/kick-anime.gif",
        "https://media1.tenor.com/m/06XcN2z7G0gAAAAC/kick-go-away.gif",
    ),
    "shoot": (
        "https://media1.tenor.com/m/guXgm-Ie55wAAAAC/anime-gun.gif",
        "https://media1.tenor.com/m/9PY4E3GrtZ4AAAAC/symphogear-senki-zesshou-symphogear.gif",
    ),
}


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
        headers=_OTAKUGIFS_HEADERS,
        timeout=_TIMEOUT,
    )
    return await get_bytes(payload["url"], timeout=_TIMEOUT)


async def _nekos_best(action: str) -> bytes:
    payload = await get_json(
        f"https://nekos.best/api/v2/{action}",
        headers=_NEKOSBEST_HEADERS,
        timeout=_TIMEOUT,
    )
    return await get_bytes(
        payload["results"][0]["url"],
        headers=_NEKOSBEST_HEADERS,
        timeout=_TIMEOUT,
    )


async def _nekos_life(action: str) -> bytes:
    payload = await get_json(
        f"https://nekos.life/api/v2/img/{action}",
        timeout=_TIMEOUT,
    )
    return await get_bytes(payload["url"], timeout=_TIMEOUT)


async def _curated(action: str) -> bytes:
    """Download a curated Tenor GIF via GET (Tenor's CDN rejects HEAD)."""
    session = await get_session()
    last_error: Exception | None = None
    for url in _CURATED_GIFS[action]:
        try:
            timeout = aiohttp.ClientTimeout(total=_TIMEOUT)
            async with session.get(url, timeout=timeout) as response:
                response.raise_for_status()
                if "image/" not in response.content_type:
                    raise ValueError(f"not an image: {response.content_type}")
                data = await response.read()
            if len(data) > 52_428_800:
                raise ValueError("file too large")
            return data
        except Exception as error:
            last_error = error
            log.warning("curated GIF %s failed for %r: %s", url, action, error)
    raise RuntimeError(f"no curated GIF reachable for {action!r}") from last_error


_FETCHERS: dict[str, Callable[[str], Awaitable[bytes]]] = {
    "otakugifs": _otakugifs,
    "nekos.best": _nekos_best,
    "nekos.life": _nekos_life,
    "curated": _curated,
}


def _sources_for(action: str) -> list[tuple[str, Callable[[str], Awaitable[bytes]]]]:
    """Ordered (name, fetcher) chain for an action, main source first."""
    if action in _NEKOSBEST_PREFERRED:
        yield ("nekos.best", _nekos_best)
    if action in _CURATED_GIFS:
        yield ("curated", _curated)
        return
    if action in _OTAKUGIFS_ACTIONS:
        yield ("otakugifs", _otakugifs)
    if action in _NEKOSBEST_ACTIONS and action not in _NEKOSBEST_PREFERRED:
        yield ("nekos.best", _nekos_best)
    if action in _NEKOSLIFE_ACTIONS:
        yield ("nekos.life", _nekos_life)


async def fetch_action_gif(action: str) -> bytes:
    """
    Return the raw bytes of a reaction GIF for action.

    Sources are tried in order: for shoot/highfive/kick, nekos.best is used
    first with curated Tenor GIFs as fallback; everything else goes
    otakugifs -> nekos.best -> nekos.life. Each source hands back either raw
    bytes (curated) or a JSON document pointing at the real asset, which we
    then download. We only cycle to the next source when the current one fails.
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
