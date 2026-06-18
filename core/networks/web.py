"""shared aiohttp session and web utilities.
manages a single session for the whole bot.
use fetch get_bytes or get_json"""

from __future__ import annotations
import asyncio
from typing import Any, Optional
import aiohttp
from loguru import logger

_session: Optional[aiohttp.ClientSession] = None


async def get_session() -> aiohttp.ClientSession:
    """get or create shared session"""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_session() -> None:
    """close shared session on shutdown"""
    global _session
    if _session and not _session.closed:
        await _session.close()


async def fetch(url: str, **kw) -> str:
    """get url and return response text"""
    s = await get_session()
    async with s.get(url, **kw) as r:
        r.raise_for_status()
        return await r.text()


async def get_json(url: str, **kw) -> Any:
    """get url and return parsed json"""
    s = await get_session()
    async with s.get(url, **kw) as r:
        r.raise_for_status()
        return await r.json()


async def get_bytes(url: str, max_size: int = 52_428_800, **kw) -> bytes:
    """download url and return raw bytes.
    raises ValueError if content is too big or not an image"""
    s = await get_session()
    async with s.head(url, **kw) as head:
        if int(head.headers.get("Content-Length", 0)) > max_size:
            raise ValueError("file too large")
        if "image/" not in head.content_type:
            raise ValueError(f"not an image: {head.content_type}")
    async with s.get(url, **kw) as r:
        return await r.read()
