from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final


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
