"""download and validate image bytes.
checks content type and size before returning.
use fetch_image in image manipulation commands"""

import aiohttp
from typing import Optional

_ALLOWED = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MAX = 52_428_800


async def fetch_image(url: str, max_bytes: int = _MAX) -> bytes:
    """download image from url and return bytes.
    raises ValueError if too big or wrong content type.
    raises aiohttp errors if request fails"""
    async with aiohttp.ClientSession() as s:
        async with s.head(url) as h:
            ct = h.headers.get("Content-Type", "")
            if not any(ct.startswith(m) for m in _ALLOWED):
                raise ValueError(f"not an image: {ct}")
            if int(h.headers.get("Content-Length", 0)) > max_bytes:
                raise ValueError("image too large")
        async with s.get(url) as r:
            return await r.read()
