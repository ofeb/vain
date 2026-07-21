from __future__ import annotations

from core.networks.web import get_bytes, get_json

_GIF_ENDPOINT = "https://api.otakugifs.xyz/gif"

# otakugifs.xyz reaction names (GET /gif?reaction=NAME). Aliases map local command
# names that are not API reactions onto the closest valid one.
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


def resolve_reaction(action: str) -> str:
    """Map a roleplay action name to a valid otakugifs reaction."""
    key = (action or "").strip().lower()
    if key in _REACTION_ALIASES:
        return _REACTION_ALIASES[key]
    if key in _VALID_REACTIONS:
        return key
    # last resort: pat is a safe, widely available reaction
    return "pat"


async def fetch_action_gif(action: str) -> bytes:
    """
    Return the raw bytes of a reaction GIF for action.

    Two hops are required: the API hands back a JSON document pointing at the
    real asset, which we then download.
    """
    reaction = resolve_reaction(action)
    payload = await get_json(_GIF_ENDPOINT, params={"reaction": reaction})
    asset_url = payload["url"]
    return await get_bytes(asset_url)
