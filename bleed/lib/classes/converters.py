from __future__ import annotations

import re
from pathlib import Path


class _EventMapping(dict):
    def __missing__(self, key):
        value = (str(key).replace("_", " "), "")
        self[key] = value
        return value


EVENT_MAPPING = _EventMapping(
    {
        "y/n": ("y/n", "Toggle upvote/downvote to messages."),
        "v/s": ("v/s", "Toggle left arrow/right arrow to messages."),
        "afk": ("afk", "Toggle away messages when pinging AFK members."),
        "previousreaction": (
            "previousreaction",
            "Toggle any previous reaction triggers.",
        ),
        "reactiontrigger": (
            "reactiontrigger",
            "Toggle any reaction triggers.",
        ),
        "autoresponder": ("autoresponder", "Toggle all auto responders."),
        "commandfailure": (
            "commandfailure",
            "Toggle failed command execution messages.",
        ),
        "snipe": ("snipe", "Toggle messages from being sniped completely."),
        "cleverbot": ("cleverbot", "Toggle clever bot conversations."),
        "automodmessage": (
            "automodmessage",
            "Toggle bleed auto-mod messages upon user punishment.",
        ),
        "instagram": ("instagram", "Toggle Instagram reposting from members."),
        "tiktok": ("tiktok", "Toggle TikTok reposting from members."),
        "grailed": ("grailed", "Toggle Grailed reposting from members."),
        "twitch": ("twitch", "Toggle Twitch reposting from members."),
        "streamable": ("streamable", "Toggle Streamable reposting from members."),
        "twitter": ("twitter", "Toggle Twitter/X reposting from members."),
        "medal": ("medal", "Toggle Medal reposting from members."),
        "soundcloud": ("soundcloud", "Toggle SoundCloud reposting from members."),
        "tumblr": ("tumblr", "Toggle Tumblr reposting from members."),
        "shorts": ("shorts", "Toggle Shorts reposting from members."),
        "kick": ("kick", "Toggle Kick reposting from members."),
        "youtube": ("youtube", "Toggle YouTube reposting from members."),
        "reddit": ("reddit", "Toggle Reddit reposting from members."),
    }
)

_EVENT_ALIASES = {
    "yn": "y/n",
    "upvote": "y/n",
    "downvote": "y/n",
    "vs": "v/s",
    "leftright": "v/s",
    "previousreactions": "previousreaction",
    "reactiontriggers": "reactiontrigger",
    "commandfail": "commandfailure",
    "command_fail": "commandfailure",
    "automod": "automodmessage",
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize_event_name(value: str) -> str:
    normalized = _normalize(value)
    if normalized in _EVENT_ALIASES:
        return _EVENT_ALIASES[normalized]
    for event_name in EVENT_MAPPING:
        if _normalize(event_name) == normalized:
            return event_name
    return normalized
