from __future__ import annotations

from typing import List, Optional, Any

from discord.ext.commands import CommandError
from ext.lastfm.proper.http import http
from ext.lastfm.interface.spotify.proper.track import SpotifyTrack
from pydantic import BaseModel, Field


class Artist(BaseModel):
    name: str
    mbid: Optional[str] = None
    url: str

    def __str__(self) -> str:
        return self.name


class ImageItem(BaseModel):
    text: str = Field(..., alias="#text")
    size: str

    def __str__(self) -> str:
        return self.text


class Album(BaseModel):
    artist: str
    title: str
    mbid: Optional[str] = None
    url: str
    image: List[ImageItem]

    def __str__(self) -> str:
        return self.title


class Wiki(BaseModel):
    published: str
    summary: str
    content: str

    def __str__(self) -> str:
        return self.summary


class Track(BaseModel):
    name: str
    mbid: Optional[str] = None
    url: str
    duration: Optional[int] = 0
    listeners: Optional[int] = 0
    playcount: Optional[int] = 0
    artist: Artist
    album: Optional[Album] = None
    userplaycount: Optional[int] = 0
    userloved: Optional[bool] = False
    wiki: Optional[Wiki] = None
    image: Optional[str] = None
    spotify: Optional[SpotifyTrack] = None 
    def __str__(self) -> str:
        return self.name

    @property
    def plays(self) -> int:
        return self.userplaycount or 0

    @classmethod
    async def fetch(
        cls,
        track: str,
        artist: str,
        username: str = "",
        image_url: Optional[str] = None,
    ) -> Track:
        response = await http.get(
            "/2.0/",
            params={
                "method": "track.getInfo",
                "username": username,
                "artist": artist,
                "track": track,
            },
        )

        try:
            data = (await response.json())["track"]
            return cls(**data, image=image_url)
        except KeyError as exc:
            raise CommandError(f"Last.fm track **{track}** not found!") from exc