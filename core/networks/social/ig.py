"""instagram public api client.
fetches public profile and post metadata.
no auth needed for public accounts"""

import aiohttp, re
from typing import Optional

_SHORT_RE = re.compile(r"https?://(www\.)?instagram\.com/(p|reel)/([\w-]+)")


class Instagram:
    """instagram unofficial api wrapper"""

    HDR = {"User-Agent": "Mozilla/5.0"}

    async def post(self, url: str) -> Optional[dict]:
        """get metadata for an instagram post or reel"""
        m = _SHORT_RE.match(url)
        if not m:
            return None
        code = m.group(3)
        async with aiohttp.ClientSession(headers=self.HDR) as s:
            async with s.get(f"https://www.instagram.com/p/{code}/?__a=1&__d=dis") as r:
                if r.status != 200:
                    return None
                return await r.json()
