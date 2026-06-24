from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

import discord


EMOJI_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "emoji"
_EMOJI_CACHE: dict[str, str] | None = None


def emoji_root() -> Path:
    return EMOJI_ROOT


def emoji_manifest_path(*parts: str) -> Path:
    return EMOJI_ROOT.joinpath(*parts, "app_emojis.json")


def _load_manifests() -> dict[str, str]:
    global _EMOJI_CACHE
    if _EMOJI_CACHE is not None:
        return _EMOJI_CACHE

    loaded: dict[str, str] = {}
    if not EMOJI_ROOT.is_dir():
        _EMOJI_CACHE = loaded
        return loaded

    for manifest_path in sorted(EMOJI_ROOT.glob("**/app_emojis.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for raw_key, raw_value in payload.items():
            key = str(raw_key).strip()
            value = str(raw_value).strip()
            if not key or not value or key in loaded:
                continue
            loaded[key] = value

    _EMOJI_CACHE = loaded
    return loaded


def prime_emoji_environment() -> dict[str, str]:
    loaded = _load_manifests()
    for key, value in loaded.items():
        if not key.startswith("BLEED_EMOJI_"):
            continue
        os.environ.setdefault(key, value)
    return loaded


_UNICODE_FALLBACKS: dict[str, str] = {
    "approve": "✅",
    "success": "✅",
    "warn": "⚠️",
    "deny": "❌",
    "cooldown": "⏰",
    "loading": "⏳",
    "info": "ℹ️",
}


def default_emoji(key: str, fallback: str) -> str:
    env_key = f"BLEED_EMOJI_{key.upper()}"
    return os.environ.get(env_key, fallback)


def format_embed_emoji(
    bot,
    emoji: str,
    *,
    fallback_key: str = "",
    fallback: str = "",
) -> str:
    """return an emoji string that renders in embeds for this bot."""
    text = str(emoji or "").strip()
    if not text:
        return fallback or _UNICODE_FALLBACKS.get(fallback_key, "•")

    try:
        partial = discord.PartialEmoji.from_str(text)
    except ValueError:
        return text

    if partial.is_unicode_emoji():
        return str(partial)

    if partial.id is None:
        return text

    cached = bot.get_emoji(partial.id)
    if cached is not None:
        return str(cached)

    for owned in bot.emojis:
        if owned.id == partial.id:
            return str(owned)

    application = getattr(bot, "application", None)
    if application is not None:
        app_emojis = getattr(application, "emojis", None)
        if app_emojis is not None:
            for owned in app_emojis:
                if owned.id == partial.id:
                    return str(owned)

    manifest_ids: set[int] = set()
    for value in _load_manifests().values():
        if not str(value).startswith("<"):
            continue
        try:
            listed = discord.PartialEmoji.from_str(str(value))
        except ValueError:
            continue
        if listed.id is not None:
            manifest_ids.add(listed.id)
    if partial.id in manifest_ids and text.startswith("<"):
        return text

    return fallback or _UNICODE_FALLBACKS.get(fallback_key, "•")
