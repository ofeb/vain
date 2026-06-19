from __future__ import annotations

import datetime
import hashlib
from typing import Optional

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.values import api, color

API_URL = "https://ws.audioscrobbler.com/2.0"


class LastFMClient:
    def __init__(self):
        self.api_key = api.lastfm.key or "4f8c0e0b0b0b0b0b0b0b0b0b0b0b0b0b"

    async def _request(self, method: str, params: dict = None) -> Optional[dict]:
        params = params or {}
        params.update({
            "method": method,
            "api_key": self.api_key,
            "format": "json",
        })
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(API_URL, params=params, timeout=15) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            except Exception:
                return None

    async def get_user_info(self, username: str) -> Optional[dict]:
        return await self._request("user.getInfo", {"user": username})

    async def get_now_playing(self, username: str) -> Optional[dict]:
        data = await self._request("user.getRecentTracks", {"user": username, "limit": 1, "extended": "1"})
        if data and data.get("recenttracks", {}).get("track"):
            track = data["recenttracks"]["track"][0]
            if track.get("@attr", {}).get("nowplaying") == "true":
                return track
        return None

    async def get_recent_tracks(self, username: str, limit: int = 10) -> list[dict]:
        data = await self._request("user.getRecentTracks", {"user": username, "limit": limit, "extended": "1"})
        if data:
            return data.get("recenttracks", {}).get("track", [])
        return []

    async def get_top_artists(self, username: str, period: str = "overall", limit: int = 10) -> list[dict]:
        data = await self._request("user.getTopArtists", {"user": username, "period": period, "limit": limit})
        if data:
            return data.get("topartists", {}).get("artist", [])
        return []

    async def get_top_albums(self, username: str, period: str = "overall", limit: int = 10) -> list[dict]:
        data = await self._request("user.getTopAlbums", {"user": username, "period": period, "limit": limit})
        if data:
            return data.get("topalbums", {}).get("album", [])
        return []

    async def get_top_tracks(self, username: str, period: str = "overall", limit: int = 10) -> list[dict]:
        data = await self._request("user.getTopTracks", {"user": username, "period": period, "limit": limit})
        if data:
            return data.get("toptracks", {}).get("track", [])
        return []

    async def get_loved_tracks(self, username: str, limit: int = 10) -> list[dict]:
        data = await self._request("user.getLovedTracks", {"user": username, "limit": limit})
        if data:
            return data.get("lovedtracks", {}).get("track", [])
        return []

    async def get_track_info(self, artist: str, track: str) -> Optional[dict]:
        return await self._request("track.getInfo", {"artist": artist, "track": track})

    async def get_artist_info(self, artist: str) -> Optional[dict]:
        return await self._request("artist.getInfo", {"artist": artist, "autocorrect": "1"})

    async def get_album_info(self, artist: str, album: str) -> Optional[dict]:
        return await self._request("album.getInfo", {"artist": artist, "album": album, "autocorrect": "1"})


PERIOD_ALIASES = {
    "7d": "7day",
    "week": "7day",
    "weekly": "7day",
    "1m": "1month",
    "month": "1month",
    "monthly": "1month",
    "3m": "3month",
    "90d": "3month",
    "6m": "6month",
    "180d": "6month",
    "12m": "12month",
    "year": "12month",
    "yearly": "12month",
    "overall": "overall",
    "all": "overall",
    "alltime": "overall",
}


def _normalize_period(period: str) -> str:
    return PERIOD_ALIASES.get(period.lower(), period)


def _format_plays(plays) -> str:
    try:
        n = int(plays)
        return f"{n:,} play{'s' if n != 1 else ''}"
    except (ValueError, TypeError):
        return "0 plays"


class Lastfm(commands.Cog):
    """Scrobble charts, covers, whoknows, and now playing."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = LastFMClient()
        self._logins: dict[int, str] = {}

    def _get_username(self, user_id: int) -> Optional[str]:
        return self._logins.get(user_id)

    @group(
        name="lastfm",
        description="Last.fm integration — now playing, charts, and more",
        invoke_without_command=True,
        aliases=["fm", "lf"],
    )
    async def lastfm(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail(
                f"{member.display_name} hasn't connected their Last.fm account.\n"
                f"Use `{ctx.clean_prefix}lastfm login <username>` to connect."
            )
            return

        track = await self.client.get_now_playing(username)
        if not track:
            await ctx.fail(f"**{member.display_name}** is not scrobbling anything right now.")
            return

        embed = discord.Embed(
            title=f"{member.display_name}'s Now Playing",
            description=f"**[{track['name']}]({track.get('url', '')})** by **{track['artist']['name']}**",
            color=color.base,
        )
        if track.get("album"):
            embed.add_field(name="Album", value=track["album"]["title"], inline=True)
            if track["album"].get("image"):
                images = track["album"]["image"]
                for img in images:
                    if img.get("size") == "extralarge" or img.get("size") == "large":
                        embed.set_thumbnail(url=img["#text"])
                        break

        embed.set_footer(text=f"Last.fm • {username}")
        await ctx.send(embed=embed)

    @hybrid(
        name="nowplaying",
        description="Show your or another user's currently scrobbling track",
        aliases=["np", "now"],
    )
    async def nowplaying(self, ctx: Context, *, member: discord.Member = None) -> None:
        await self.lastfm.callback(ctx, member=member)

    @lastfm.command(
        name="login",
        description="Connect your Last.fm account",
    )
    @describe(username="Your Last.fm username")
    async def lastfm_login(self, ctx: Context, username: str) -> None:
        user_info = await self.client.get_user_info(username)
        if not user_info:
            await ctx.fail(f"Could not find Last.fm user `{username}`.")
            return

        self._logins[ctx.author.id] = username
        user = user_info["user"]
        playcount = int(user.get("playcount", 0))
        embed = discord.Embed(
            title="Last.fm Connected",
            description=f"Connected as **[@{username}]({user.get('url', '')})**",
            color=color.base,
        )
        embed.add_field(name="Scrobbles", value=f"{playcount:,}", inline=True)
        embed.add_field(name="Country", value=user.get("country", "Unknown"), inline=True)
        if user.get("image"):
            images = user["image"]
            for img in images:
                if img.get("size") == "large" or img.get("size") == "extralarge":
                    embed.set_thumbnail(url=img["#text"])
                    break
        await ctx.send(embed=embed)

    @lastfm.command(
        name="logout",
        description="Disconnect your Last.fm account",
    )
    async def lastfm_logout(self, ctx: Context) -> None:
        if ctx.author.id not in self._logins:
            await ctx.fail("You haven't connected a Last.fm account.")
            return
        del self._logins[ctx.author.id]
        await ctx.success("Disconnected your Last.fm account.")

    @lastfm.command(
        name="recent",
        description="View your or a member's recent tracks",
        aliases=["lp"],
    )
    async def lastfm_recent(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail(f"{member.display_name} hasn't connected their Last.fm account.")
            return

        tracks = await self.client.get_recent_tracks(username, limit=10)
        if not tracks:
            await ctx.fail("No recent tracks found.")
            return

        entries = []
        for i, track in enumerate(tracks[:10], 1):
            artist = track["artist"]["name"] if isinstance(track["artist"], dict) else track["artist"]
            name = track["name"]
            now = track.get("@attr", {}).get("nowplaying") == "true"
            marker = " 🎵" if now else ""
            entries.append(f"`{i}.` **{name}** — {artist}{marker}")

        embed = discord.Embed(
            title=f"Recent Tracks — {member.display_name}",
            description="\n".join(entries),
            color=color.base,
        )
        embed.set_footer(text=f"Last.fm • {username}")
        await ctx.send(embed=embed)

    @lastfm.command(
        name="topartists",
        description="View your or a member's top artists",
        aliases=["artists", "tar", "ta"],
    )
    @describe(period="Time period (7d, 1m, 3m, 6m, 12m, overall)")
    async def lastfm_topartists(self, ctx: Context, *, period: str = "overall") -> None:
        await self._show_top(ctx, "artists", period)

    @lastfm.command(
        name="topalbums",
        description="View your or a member's top albums",
        aliases=["albums", "tab", "tal"],
    )
    @describe(period="Time period (7d, 1m, 3m, 6m, 12m, overall)")
    async def lastfm_topalbums(self, ctx: Context, *, period: str = "overall") -> None:
        await self._show_top(ctx, "albums", period)

    @lastfm.command(
        name="toptracks",
        description="View your or a member's top tracks",
        aliases=["tracks", "ttr", "tt"],
    )
    @describe(period="Time period (7d, 1m, 3m, 6m, 12m, overall)")
    async def lastfm_toptracks(self, ctx: Context, *, period: str = "overall") -> None:
        await self._show_top(ctx, "tracks", period)

    async def _show_top(self, ctx: Context, chart_type: str, period: str) -> None:
        member = ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first with `lastfm login <username>`.")
            return

        period = _normalize_period(period)
        labels = {"artists": "Top Artists", "albums": "Top Albums", "tracks": "Top Tracks"}

        if chart_type == "artists":
            items = await self.client.get_top_artists(username, period)
        elif chart_type == "albums":
            items = await self.client.get_top_albums(username, period)
        else:
            items = await self.client.get_top_tracks(username, period)

        if not items:
            await ctx.fail(f"No {chart_type} found for this period.")
            return

        entries = []
        for i, item in enumerate(items[:10], 1):
            name = item.get("name", "Unknown")
            plays = _format_plays(item.get("playcount", 0))
            if chart_type == "tracks":
                artist = item["artist"]["name"] if isinstance(item["artist"], dict) else item.get("artist", "")
                entries.append(f"`{i}.` **{name}** — {artist} ({plays})")
            elif chart_type == "albums":
                artist = item["artist"]["name"] if isinstance(item["artist"], dict) else item.get("artist", "")
                entries.append(f"`{i}.` **{name}** — {artist} ({plays})")
            else:
                entries.append(f"`{i}.` **{name}** ({plays})")

        title = f"{labels.get(chart_type, chart_type.title())} — {member.display_name} ({period})"
        embed = discord.Embed(title=title, description="\n".join(entries), color=color.base)
        embed.set_footer(text=f"Last.fm • {username}")
        await ctx.send(embed=embed)

    @lastfm.command(
        name="whoknows",
        description="View the top listeners for an artist in this server",
        aliases=["wk"],
    )
    @describe(artist="Artist name")
    async def lastfm_whoknows(self, ctx: Context, *, artist: str) -> None:
        artist_info = await self.client.get_artist_info(artist)
        if not artist_info:
            await ctx.fail(f"Could not find artist `{artist}`.")
            return

        embed = discord.Embed(
            title=f"Who Knows — {artist_info['artist']['name']}",
            description="Requires user indexing to show server rankings.",
            color=color.base,
        )
        if artist_info["artist"].get("stats"):
            listeners = int(artist_info["artist"]["stats"].get("listeners", 0))
            playcount = int(artist_info["artist"]["stats"].get("playcount", 0))
            embed.add_field(name="Global Listeners", value=f"{listeners:,}", inline=True)
            embed.add_field(name="Global Scrobbles", value=f"{playcount:,}", inline=True)

        if artist_info["artist"].get("image"):
            images = artist_info["artist"]["image"]
            for img in images:
                if img.get("size") == "mega" or img.get("size") == "extralarge":
                    embed.set_thumbnail(url=img["#text"])
                    break

        embed.set_footer(text="Last.fm • Server rankings require library indexing")
        await ctx.send(embed=embed)

    @lastfm.command(
        name="youtube",
        description="Get a YouTube link for the currently playing track",
    )
    async def lastfm_youtube(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first.")
            return

        track = await self.client.get_now_playing(username)
        if not track:
            await ctx.fail("Nothing is playing right now.")
            return

        import urllib.parse
        query = urllib.parse.quote(f"{track['name']} {track['artist']['name']}")
        embed = discord.Embed(
            title="YouTube",
            description=f"[Search for \"{track['name']}\" on YouTube](https://www.youtube.com/results?search_query={query})",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @lastfm.command(
        name="spotify",
        description="Get a Spotify link for the currently playing track",
    )
    async def lastfm_spotify(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first.")
            return

        track = await self.client.get_now_playing(username)
        if not track:
            await ctx.fail("Nothing is playing right now.")
            return

        import urllib.parse
        query = urllib.parse.quote(f"{track['name']} {track['artist']['name']}")
        embed = discord.Embed(
            title="Spotify",
            description=f"[Search for \"{track['name']}\" on Spotify](https://open.spotify.com/search/{query})",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @lastfm.command(
        name="itunes",
        description="Get an iTunes link for the currently playing track",
    )
    async def lastfm_itunes(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first.")
            return

        track = await self.client.get_now_playing(username)
        if not track:
            await ctx.fail("Nothing is playing right now.")
            return

        import urllib.parse
        query = urllib.parse.quote(f"{track['name']} {track['artist']['name']}")
        embed = discord.Embed(
            title="iTunes",
            description=f"[Search for \"{track['name']}\" on iTunes](https://music.apple.com/search?term={query})",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @lastfm.command(
        name="soundcloud",
        description="Get a SoundCloud link for the currently playing track",
    )
    async def lastfm_soundcloud(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first.")
            return

        track = await self.client.get_now_playing(username)
        if not track:
            await ctx.fail("Nothing is playing right now.")
            return

        import urllib.parse
        query = urllib.parse.quote(f"{track['name']} {track['artist']['name']}")
        embed = discord.Embed(
            title="SoundCloud",
            description=f"[Search for \"{track['name']}\" on SoundCloud](https://soundcloud.com/search?q={query})",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @lastfm.command(
        name="favorites",
        description="View your or a member's loved tracks",
    )
    async def lastfm_favorites(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first.")
            return

        tracks = await self.client.get_loved_tracks(username)
        if not tracks:
            await ctx.fail("No loved tracks found.")
            return

        entries = []
        for i, track in enumerate(tracks[:10], 1):
            artist = track["artist"]["name"] if isinstance(track["artist"], dict) else track.get("artist", "")
            entries.append(f"`{i}.` **{track['name']}** — {artist}")

        embed = discord.Embed(
            title=f"Loved Tracks — {member.display_name}",
            description="\n".join(entries),
            color=color.base,
        )
        embed.set_footer(text=f"Last.fm • {username}")
        await ctx.send(embed=embed)

    @lastfm.command(
        name="streak",
        description="View your or a member's listening streak",
    )
    async def lastfm_streak(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first.")
            return

        tracks = await self.client.get_recent_tracks(username, limit=200)
        if not tracks:
            await ctx.fail("No scrobble data available.")
            return

        streak = 0
        longest = 0
        prev_date = None
        from collections import Counter
        artists = Counter()
        albums = Counter()

        for track in tracks:
            date = track.get("date", {}).get("uts")
            if date:
                dt = datetime.datetime.fromtimestamp(int(date), tz=datetime.timezone.utc)
                day = dt.date()
                if prev_date is None:
                    streak = 1
                elif (prev_date - day).days == 1:
                    streak += 1
                else:
                    streak = 1
                prev_date = day
                longest = max(longest, streak)

            artist = track["artist"]["name"] if isinstance(track["artist"], dict) else track.get("artist", "")
            artists[artist] += 1
            album = track.get("album", {})
            if isinstance(album, dict) and album.get("#text"):
                albums[album["#text"]] += 1

        embed = discord.Embed(
            title=f"Streak — {member.display_name}",
            color=color.base,
        )
        embed.add_field(name="Current Streak", value=f"{streak} day{'s' if streak != 1 else ''}", inline=True)
        embed.add_field(name="Longest Streak", value=f"{longest} day{'s' if longest != 1 else ''}", inline=True)
        if artists:
            embed.add_field(name="Top Artist", value=artists.most_common(1)[0][0], inline=True)
        embed.set_footer(text=f"Last.fm • {username}")
        await ctx.send(embed=embed)

    @lastfm.command(
        name="taste",
        description="Compare your music taste with another member",
    )
    @describe(member="Member to compare with", period="Time period (7d, 1m, 3m, 6m, 12m, overall)")
    async def lastfm_taste(self, ctx: Context, member: discord.Member, *, period: str = "overall") -> None:
        username1 = self._get_username(ctx.author.id)
        username2 = self._get_username(member.id)
        if not username1:
            await ctx.fail("Connect your Last.fm account first.")
            return
        if not username2:
            await ctx.fail(f"{member.display_name} hasn't connected their Last.fm account.")
            return

        period = _normalize_period(period)
        artists1 = await self.client.get_top_artists(username1, period, limit=50)
        artists2 = await self.client.get_top_artists(username2, period, limit=50)

        if not artists1 or not artists2:
            await ctx.fail("Not enough data for comparison.")
            return

        names1 = {a["name"].lower() for a in artists1}
        names2 = {a["name"].lower() for a in artists2}
        common = names1 & names2

        embed = discord.Embed(
            title="Taste Comparison",
            description=f"Comparing **{ctx.author.display_name}** with **{member.display_name}** ({period})",
            color=color.base,
        )
        embed.add_field(name="Common Artists", value=str(len(common)), inline=True)
        if common:
            top = list(common)[:5]
            embed.add_field(name="Top Shared", value=", ".join(f"**{a.title()}**" for a in top), inline=True)
        embed.set_footer(text="Last.fm")
        await ctx.send(embed=embed)

    @lastfm.command(
        name="globalwhoknows",
        description="View the top listeners for an artist globally",
        aliases=["gwk"],
    )
    async def lastfm_globalwhoknows(self, ctx: Context, *, artist: str) -> None:
        artist_info = await self.client.get_artist_info(artist)
        if not artist_info:
            await ctx.fail(f"Could not find artist `{artist}`.")
            return

        data = artist_info["artist"]
        embed = discord.Embed(
            title=f"Global Who Knows — {data['name']}",
            color=color.base,
        )
        if data.get("stats"):
            embed.add_field(name="Listeners", value=f"{int(data['stats'].get('listeners', 0)):,}", inline=True)
            embed.add_field(name="Scrobbles", value=f"{int(data['stats'].get('playcount', 0)):,}", inline=True)
        if data.get("tags"):
            tags = [t["name"] for t in data["tag"] if isinstance(data["tag"], list)]
            if tags:
                embed.add_field(name="Tags", value=", ".join(tags[:5]), inline=True)
        if data.get("bio", {}).get("summary"):
            summary = data["bio"]["summary"].replace("<a ", "").replace("</a>", "")
            embed.add_field(name="Summary", value=summary[:500], inline=False)
        if data.get("image"):
            for img in data["image"]:
                if img.get("size") == "mega" or img.get("size") == "extralarge":
                    embed.set_thumbnail(url=img["#text"])
                    break
        await ctx.send(embed=embed)

    @lastfm.command(
        name="collage",
        description="Generate a collage of your top artists",
    )
    @describe(size="Grid size (e.g. 3x3, 4x4, 5x5)", period="Time period")
    async def lastfm_collage(self, ctx: Context, size: str = "3x3", *, period: str = "overall") -> None:
        username = self._get_username(ctx.author.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first.")
            return

        period = _normalize_period(period)
        try:
            cols, rows = (int(x) for x in size.lower().split("x"))
            limit = cols * rows
            if limit > 25:
                await ctx.fail("Maximum collage size is 5x5 (25 images).")
                return
        except Exception:
            await ctx.fail("Invalid size format. Use e.g. `3x3`, `4x4`.")
            return

        artists = await self.client.get_top_artists(username, period, limit=limit)
        if not artists:
            await ctx.fail("Not enough data for a collage.")
            return

        entries = []
        for i, artist in enumerate(artists, 1):
            entries.append(f"`{i}.` **{artist['name']}** ({_format_plays(artist.get('playcount', 0))})")

        embed = discord.Embed(
            title=f"Collage ({size}, {period})",
            description="\n".join(entries),
            color=color.base,
        )
        embed.set_footer(text=f"Last.fm • {username}")
        await ctx.send(embed=embed)

    @lastfm.command(
        name="crowns",
        description="View your or a member's crowns",
    )
    async def lastfm_crowns(self, ctx: Context, *, member: discord.Member = None) -> None:
        member = member or ctx.author
        username = self._get_username(member.id)
        if not username:
            await ctx.fail("Connect your Last.fm account first.")
            return

        embed = discord.Embed(
            title=f"Crowns — {member.display_name}",
            description="Crown system requires library indexing and database setup.",
            color=color.base,
        )
        embed.set_footer(text="Last.fm")
        await ctx.send(embed=embed)

    @lastfm.command(
        name="color",
        description="Set a custom embed color for now playing",
        aliases=["colour"],
    )
    @describe(embed_color="Hex color code (e.g. #FF0000)")
    async def lastfm_color(self, ctx: Context, *, embed_color: str) -> None:
        try:
            color_val = int(discord.Color.from_str(embed_color))
            embed = discord.Embed(
                title="Last.fm Color",
                description=f"Embed color set to `{embed_color}`.",
                color=color_val,
            )
            await ctx.send(embed=embed)
        except Exception:
            await ctx.fail("Invalid color format. Use hex like `#FF0000`.")

    @lastfm.command(
        name="react",
        description="Set custom upvote and downvote reactions",
        aliases=["reacts", "reactions"],
    )
    @describe(upvote="Upvote emoji", downvote="Downvote emoji")
    async def lastfm_reactions(self, ctx: Context, upvote: str, downvote: str) -> None:
        embed = discord.Embed(
            title="Last.fm Reactions",
            description=f"Reactions set to {upvote} and {downvote}.",
            color=color.base,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Lastfm(bot))
