"""youtube api client for video and channel lookup.
wraps youtube data api v3 endpoints.
set api key in config under Authorization.youtube"""

import aiohttp
from typing import Optional
from config import api

BASE = "https://www.googleapis.com/youtube/v3"


class YouTube:
    """youtube data api v3 wrapper"""

    def __init__(self):
        self.key = api.google_perspective

    async def _get(self, endpoint: str, **params) -> dict:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{BASE}/{endpoint}", params={"key": self.key, **params}) as r:
                r.raise_for_status()
                return await r.json()

    async def search(self, query: str, limit: int = 5) -> list:
        """search youtube and return video items"""
        data = await self._get("search", q=query, type="video", maxResults=limit, part="snippet")
        return data.get("items", [])

    async def video(self, video_id: str) -> Optional[dict]:
        """get details for a specific video id"""
        data = await self._get("videos", id=video_id, part="snippet,statistics,contentDetails")
        items = data.get("items", [])
        return items[0] if items else None

    async def channel(self, channel_id: str) -> Optional[dict]:
        """get channel info by id"""
        data = await self._get("channels", id=channel_id, part="snippet,statistics")
        items = data.get("items", [])
        return items[0] if items else None
