from __future__ import annotations

import asyncio
from io import BytesIO

import aiohttp
from colorthief import ColorThief


async def get_dominant_color(source) -> str | None:
    """Fetch image and return dominant color as hex using colorthief (for all dominants)."""
    if source is None:
        return None

    url = source if isinstance(source, str) else getattr(
        getattr(source, "display_avatar", None),
        "url",
        None,
    )
    if not url:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as response:
                if response.status != 200:
                    return None
                data = await response.read()

        def _extract():
            ct = ColorThief(BytesIO(data))
            r, g, b = ct.get_color(quality=1)
            
            if (r + g + b) < 80:
                r = min(r + 60, 255)
                g = min(g + 60, 255)
                b = min(b + 60, 255)
            return f"#{r:02x}{g:02x}{b:02x}"

        return await asyncio.to_thread(_extract)
    except Exception:
        return None
