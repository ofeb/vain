from __future__ import annotations

from io import BytesIO

import aiohttp
from PIL import Image


async def get_dominant_color(source) -> str | None:
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
        async with aiohttp.ClientSession() as session, session.get(url) as response:
            if response.status != 200:
                return None
            buffer = BytesIO(await response.read())
        with Image.open(buffer).convert("RGB").resize((1, 1)) as image:
            red, green, blue = image.getpixel((0, 0))
            return f"#{red:02x}{green:02x}{blue:02x}"
    except Exception:
        return None
