"""Client for scl.guilt.bot social content API (see api-1.json)."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote

import aiohttp

from config import api as api_cfg

log = logging.getLogger("vain.social.guilt")


def _base() -> str:
    return (getattr(api_cfg, "guilt_base", None) or "https://scl.guilt.bot").rstrip("/")


def _headers() -> dict[str, str]:
    h = {"User-Agent": "VainBot/1.0", "Accept": "application/json"}
    key = getattr(api_cfg, "guilt_key", "") or ""
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


async def guilt_get(path: str, *, params: dict | None = None, timeout: float = 20.0) -> Any | None:
    url = f"{_base()}{path if path.startswith('/') else '/' + path}"
    try:
        async with aiohttp.ClientSession(headers=_headers()) as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status != 200:
                    log.debug("guilt %s -> %s", path, resp.status)
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if "json" in ctype:
                    return await resp.json()
                return await resp.text()
    except Exception as exc:
        log.debug("guilt error %s: %s", path, exc)
        return None


async def instagram_user(username: str) -> Optional[dict]:
    data = await guilt_get(f"/api/instagram/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def instagram_post(shortcode: str) -> Optional[dict]:
    data = await guilt_get(f"/api/instagram/p/{quote(shortcode)}")
    return data if isinstance(data, dict) else None


async def tiktok_user(username: str) -> Optional[dict]:
    data = await guilt_get(f"/api/tiktok/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def tiktok_item(item_id: str) -> Optional[dict]:
    data = await guilt_get(f"/api/tiktok/p/{quote(item_id)}")
    return data if isinstance(data, dict) else None


async def tiktok_shortcode(code: str) -> Optional[dict]:
    data = await guilt_get(f"/api/tiktok/shortcode/{quote(code)}")
    return data if isinstance(data, dict) else None
