from __future__ import annotations

import base64
from typing import Optional
from urllib.parse import quote_plus

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.values import color

CLIENT_ID = ""
CLIENT_SECRET = ""
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"


class SpotifyClient:
    def __init__(self):
        self._token = None

    async def _get_token(self) -> Optional[str]:
        if not CLIENT_ID or not CLIENT_SECRET:
            return None
        auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}
        data = {"grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(TOKEN_URL, headers=headers, data=data, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    result = await resp.json()
                    self._token = result.get("access_token")
                    return self._token
            except Exception:
                return None

    async def _request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        token = await self._get_token()
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{API_URL}/{endpoint}", headers=headers, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            except Exception:
                return None

    async def search_tracks(self, query: str, limit: int = 5) -> Optional[dict]:
        return await self._request("search", {"q": query, "type": "track", "limit": limit})

    async def search_albums(self, query: str, limit: int = 5) -> Optional[dict]:
        return await self._request("search", {"q": query, "type": "album", "limit": limit})

    async def search_artists(self, query: str, limit: int = 5) -> Optional[dict]:
        return await self._request("search", {"q": query, "type": "artist", "limit": limit})

    async def get_track(self, track_id: str) -> Optional[dict]:
        return await self._request(f"tracks/{track_id}")

    async def get_album(self, album_id: str) -> Optional[dict]:
        return await self._request(f"albums/{album_id}")

    async def get_artist(self, artist_id: str) -> Optional[dict]:
        return await self._request(f"artists/{artist_id}")


class Spotify(commands.Cog):
    """Spotify track lookup, search, and now playing."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = SpotifyClient()

    @group(
        name="spotify",
        description="Search and display Spotify tracks",
        invoke_without_command=True,
        aliases=["sp"],
    )
    async def spotify(self, ctx: Context, *, query: str) -> None:
        result = await self.client.search_tracks(query)
        if not result or not result.get("tracks", {}).get("items"):
            await ctx.fail(f"No results found for `{query}`.")
            return

        tracks = result["tracks"]["items"]
        entries = []
        for i, track in enumerate(tracks[:5], 1):
            artists = ", ".join(a["name"] for a in track["artists"])
            duration = f"{track['duration_ms'] // 60000}:{(track['duration_ms'] % 60000) // 1000:02d}"
            entries.append(f"`{i}.` **{track['name']}** — {artists} ({duration})")

        embed = discord.Embed(
            title=f"Spotify Search — {query}",
            description="\n".join(entries),
            color=color.base,
        )
        embed.set_footer(text="Powered by Spotify")
        await ctx.send(embed=embed)

    @spotify.command(
        name="search",
        description="Search for a track on Spotify",
    )
    @describe(query="Track name to search for")
    async def spotify_search(self, ctx: Context, *, query: str) -> None:
        await self.spotify.callback(ctx, query=query)

    @spotify.command(
        name="track",
        description="Get details about a Spotify track",
    )
    @describe(url_or_id="Spotify track URL or ID")
    async def spotify_track(self, ctx: Context, url_or_id: str) -> None:
        track_id = url_or_id.split("/")[-1].split("?")[0] if "/" in url_or_id else url_or_id
        track = await self.client.get_track(track_id)
        if not track:
            await ctx.fail("Could not find that track.")
            return

        artists = ", ".join(a["name"] for a in track["artists"])
        duration = f"{track['duration_ms'] // 60000}:{(track['duration_ms'] % 60000) // 1000:02d}"
        embed = discord.Embed(
            title=track["name"],
            description=f"By **{artists}**\nAlbum: {track['album']['name']}",
            color=color.base,
        )
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Popularity", value=f"{track['popularity']}/100", inline=True)
        embed.add_field(name="Release Date", value=track["album"]["release_date"], inline=True)
        embed.add_field(name="Listen on Spotify", value=f"[Open]({track['external_urls']['spotify']})", inline=True)
        if track["album"]["images"]:
            embed.set_thumbnail(url=track["album"]["images"][0]["url"])
        await ctx.send(embed=embed)

    @spotify.command(
        name="artist",
        description="Get details about a Spotify artist",
    )
    @describe(name="Artist name to search for")
    async def spotify_artist(self, ctx: Context, *, name: str) -> None:
        result = await self.client.search_artists(name)
        if not result or not result.get("artists", {}).get("items"):
            await ctx.fail(f"No artist found for `{name}`.")
            return

        artist = result["artists"]["items"][0]
        embed = discord.Embed(
            title=artist["name"],
            description=f"{artist.get('followers', {}).get('total', 0):,} followers",
            color=color.base,
        )
        genres = artist.get("genres", [])
        if genres:
            embed.add_field(name="Genres", value=", ".join(g[:5] for g in genres[:3]).title(), inline=True)
        embed.add_field(name="Popularity", value=f"{artist['popularity']}/100", inline=True)
        embed.add_field(name="Open on Spotify", value=f"[Link]({artist['external_urls']['spotify']})", inline=True)
        if artist["images"]:
            embed.set_thumbnail(url=artist["images"][0]["url"])
        await ctx.send(embed=embed)

    @spotify.command(
        name="album",
        description="Get details about a Spotify album",
    )
    @describe(url_or_id="Spotify album URL or ID")
    async def spotify_album(self, ctx: Context, url_or_id: str) -> None:
        album_id = url_or_id.split("/")[-1].split("?")[0] if "/" in url_or_id else url_or_id
        album = await self.client.get_album(album_id)
        if not album:
            await ctx.fail("Could not find that album.")
            return

        artists = ", ".join(a["name"] for a in album["artists"])
        embed = discord.Embed(
            title=album["name"],
            description=f"By **{artists}**",
            color=color.base,
        )
        embed.add_field(name="Tracks", value=album["total_tracks"], inline=True)
        embed.add_field(name="Release Date", value=album["release_date"], inline=True)
        embed.add_field(name="Open on Spotify", value=f"[Link]({album['external_urls']['spotify']})", inline=True)
        if album["images"]:
            embed.set_thumbnail(url=album["images"][0]["url"])
        await ctx.send(embed=embed)

    @hybrid(
        name="spotifyalbum",
        description="Search for an album on Spotify",
        aliases=["spalbum"],
    )
    @describe(query="Album name to search for, or leave empty to use your current Last.fm album")
    async def spotifyalbum(self, ctx: Context, *, query: str | None = None) -> None:
        query_value = query.strip() if query else ""
        if not query_value:
            lastfm = ctx.bot.get_cog("Lastfm")
            if lastfm is None:
                await ctx.info("No **album** is playing right now.")
                return
            username = await lastfm._username_for(ctx, None)
            if not username:
                return
            resolved = await lastfm._resolve_album_identity(username, None)
            if not resolved:
                await ctx.info("No **album** is playing right now.")
                return
            query_value = f"{resolved[0]} {resolved[1]}"

        url = f"https://open.spotify.com/search/{quote_plus(query_value)}"
        embed = discord.Embed(
            title="Spotify album search",
            description="Open Spotify album results for your query.",
            color=color.base,
        )
        embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.display_avatar.url,
        )
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                emoji="🟢",
                label="Spotify",
                url=url,
            )
        )
        await ctx.send(embed=embed, view=view)

    @hybrid(
        name="spotifytrack",
        description="Search for a track on Spotify",
        aliases=["sptrack"],
    )
    @describe(query="Track name to search for, or leave empty to use your current Last.fm track")
    async def spotifytrack(self, ctx: Context, *, query: str | None = None) -> None:
        query_value = query.strip() if query else ""
        if not query_value:
            lastfm = ctx.bot.get_cog("Lastfm")
            if lastfm is None:
                await ctx.info("No **track** is playing right now.")
                return
            username = await lastfm._username_for(ctx, None)
            if not username:
                return
            resolved = await lastfm._resolve_track_identity(username, None)
            if not resolved:
                await ctx.info("No **track** is playing right now.")
                return
            query_value = f"{resolved[0]} {resolved[1]}"

        url = f"https://open.spotify.com/search/{quote_plus(query_value)}"
        embed = discord.Embed(
            title="Spotify track search",
            description="Open Spotify track results for your query.",
            color=color.base,
        )
        embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.display_avatar.url,
        )
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                emoji="🟢",
                label="Spotify",
                url=url,
            )
        )
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Spotify(bot))
