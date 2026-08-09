"""Shared Last.fm HTTP client used by ``ext.lastfm.interface``."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientSession, ClientTimeout, TCPConnector

from config import api as api_cfg

log = logging.getLogger("vain.lastfm.http")

BASE_URL = "https://ws.audioscrobbler.com"


def _api_key() -> str:
    key = getattr(api_cfg.lastfm, "key", "") or ""
    keys = getattr(api_cfg.lastfm, "keys", ()) or ()
    if key:
        return str(key)
    if keys:
        return str(keys[0])
    return ""


class LastfmHTTP(ClientSession):
    """aiohttp session that injects Last.fm api_key + format=json."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("connector", TCPConnector(ssl=False))
        kwargs.setdefault(
            "headers",
            {"User-Agent": "Vain Last.fm Integration (Discord Bot)"},
        )
        kwargs.setdefault("timeout", ClientTimeout(total=20))
        super().__init__(*args, **kwargs)

    async def get(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        params = {
            "api_key": _api_key(),
            "autocorrect": 1,
            "format": "json",
            **(kwargs.pop("params", None) or {}),
        }
        kwargs["params"] = params
        method = params.get("method", "?")
        log.debug("lastfm GET %s", method)
        
        if args and isinstance(args[0], str) and not args[0].startswith("http"):
            url = f"{BASE_URL}/2.0/"
            args = (url, *args[1:])
        elif not args:
            args = (f"{BASE_URL}/2.0/",)
        response = await super().get(*args, **kwargs)
        if response.status == 429:
            log.warning("Last.fm rate limited")
        return response


http = LastfmHTTP()
