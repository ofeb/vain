"""tiktok api client for video lookup.
searches tiktok and fetches video metadata.
use TikTok class methods directly"""

import aiohttp
from typing import Optional


class TikTok:
    """tiktok public api wrapper"""

    API = "https://api.tiklydown.eu.org/api"

    async def info(self, url: str) -> Optional[dict]:
        """get metadata for a tiktok url"""
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{self.API}/download/v3", params={"url": url}) as r:
                if r.status != 200:
                    return None
                return await r.json()

    async def user(self, username: str) -> Optional[dict]:
        """get tiktok user profile info"""
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{self.API}/user", params={"username": username}) as r:
                if r.status != 200:
                    return None
                return await r.json()
