"""last.fm api wrapper client.
fetches user track artist and album data.
set api key in config under Authorization.lastfm"""

from __future__ import annotations
from typing import Any, Dict, Optional
import aiohttp
from config import api


BASE = "https://ws.audioscrobbler.com/2.0/"


class LastFM:
    """last.fm api client.
    all methods return parsed json dicts.
    raises ValueError if api returns error"""

    def __init__(self, api_key: Optional[str] = None):
        self.key = api_key or api.lastfm.key

    async def _get(self, method: str, **params) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                BASE,
                params={"method": method, "api_key": self.key, "format": "json", **params},
            ) as r:
                data = await r.json()
                if "error" in data:
                    raise ValueError(f"lastfm error {data['error']}: {data['message']}")
                return data

    async def get_user(self, username: str) -> dict:
        """fetch last.fm user profile info"""
        return (await self._get("user.getInfo", user=username)).get("user", {})

    async def recent_tracks(self, username: str, limit: int = 5) -> list:
        """get recent tracks for a user"""
        data = await self._get("user.getRecentTracks", user=username, limit=limit)
        return data.get("recenttracks", {}).get("track", [])

    async def top_artists(self, username: str, period: str = "overall", limit: int = 10) -> list:
        """get top artists for a user in a period"""
        data = await self._get("user.getTopArtists", user=username, period=period, limit=limit)
        return data.get("topartists", {}).get("artist", [])

    async def top_tracks(self, username: str, period: str = "overall", limit: int = 10) -> list:
        """get top tracks for a user in a period"""
        data = await self._get("user.getTopTracks", user=username, period=period, limit=limit)
        return data.get("toptracks", {}).get("track", [])

    async def artist_info(self, artist: str) -> dict:
        """fetch info about an artist"""
        return (await self._get("artist.getInfo", artist=artist)).get("artist", {})

    async def track_info(self, artist: str, track: str) -> dict:
        """fetch info about a track"""
        return (await self._get("track.getInfo", artist=artist, track=track)).get("track", {})
