from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote_plus

import discord
from discord.ext import commands

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.values import color, emojis, music_enabled
from core.tools.aesthetic import aesthetic_embed, panel_embed

from .api import SpotifyUserAPI, redirect_uri

if TYPE_CHECKING:
    from core.vain import Vain

TOP_DURATIONS = {
    "week": "short_term",
    "month": "medium_term",
    "year": "long_term",
    "all": "long_term",
}


def _format_ms(ms: int) -> str:
    minutes, seconds = divmod(ms // 1000, 60)
    return f"{minutes}:{seconds:02d}"


def _track_line(index: int, track: dict) -> str:
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    return f"`{index}.` **{track['name']}** — {artists} ({_format_ms(track.get('duration_ms', 0))})"


class Spotify(Package):
    """Spotify search and playback controls."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self.api = SpotifyUserAPI(self.db)
        self._login_states: dict[int, str] = {}

    async def _require_linked(self, ctx: Context) -> bool:
        if await self.api.is_linked(ctx.author.id):
            return True
        await ctx.warn("Connect Spotify first with `spotify login`.")
        return False

    async def _user_action(self, ctx: Context, method: str, endpoint: str, **kwargs) -> bool:
        if not await self._require_linked(ctx):
            return False
        try:
            await self.api.user_request(ctx.author.id, method, endpoint, **kwargs)
        except RuntimeError as exc:
            await ctx.fail(str(exc))
            return False
        return True

    @group(
        name="spotify",
        description="Control your music on Spotify or search for a track",
        invoke_without_command=True,
        aliases=["sp"],
    )
    async def spotify(self, ctx: Context, *, track: str | None = None) -> None:
        """Control your music on Spotify through commands or search for a track."""
        if ctx.invoked_subcommand is not None:
            return
        if track is None:
            return await ctx.send_help(ctx.command)
        if await self.api.is_linked(ctx.author.id):
            return await self.spotify_play.callback(ctx, query=track)
        return await self._search_tracks(ctx, track)

    async def _search_tracks(self, ctx: Context, query: str) -> None:
        result = await self.api.client_search(query)
        if not result or not result.get("tracks", {}).get("items"):
            await ctx.warn(f"No results found for `{query}`.")
            return
        tracks = result["tracks"]["items"]
        entries = [_track_line(i, track) for i, track in enumerate(tracks[:5], 1)]
        embed = panel_embed(
            title=f"Spotify Search — {query}",
            color=color.base,
            lines=entries,
            footer="Use `spotify login` to control playback",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @spotify.command(name="login", description="Grant Vain access to your Spotify account")
    async def spotify_login(self, ctx: Context, *, code: str | None = None) -> None:
        if not self.api._client_configured():
            return await ctx.fail("Spotify API credentials are not configured.")

        if code is None:
            state = self.api.new_state()
            self._login_states[ctx.author.id] = state
            url = self.api.build_login_url(state=state)
            embed = panel_embed(
                title="Spotify Login",
                color=color.base,
                lines=[
                    "Authorize Vain to control your Spotify account.",
                    "",
                    f"**1.** [Click here to authorize]({url})",
                    f"**2.** Copy the full redirect URL or authorization code",
                    f"**3.** Run `{ctx.clean_prefix}spotify login <code>`",
                    "",
                    f"Redirect URI: `{redirect_uri()}`",
                ],
                timestamp=False,
            )
            return await ctx.send(embed=embed)

        try:
            payload = await self.api.exchange_code(code)
            await self.api.save_tokens(ctx.author.id, payload)
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        self._login_states.pop(ctx.author.id, None)
        await ctx.success("Spotify account linked.")

    @spotify.command(name="logout", description="Disconnect your Spotify from our servers")
    async def spotify_logout(self, ctx: Context) -> None:
        if not await self.api.is_linked(ctx.author.id):
            return await ctx.warn("You are not linked to Spotify.")
        await self.api.delete_tokens(ctx.author.id)
        await ctx.success("Disconnected your Spotify account.")

    @spotify.command(name="play", description="Immediately skip to the requested song")
    @describe(query="Track name or Spotify URI")
    async def spotify_play(self, ctx: Context, *, query: str) -> None:
        if not await self._require_linked(ctx):
            return
        body: dict = {}
        if query.startswith("spotify:") or "open.spotify.com" in query:
            track_id = query.split("/")[-1].split("?")[0] if "/" in query else query.split(":")[-1]
            body["uris"] = [query if query.startswith("spotify:") else f"spotify:track:{track_id}"]
        else:
            result = await self.api.client_search(query, limit=1)
            items = (result or {}).get("tracks", {}).get("items", [])
            if not items:
                return await ctx.warn(f"No track found for `{query}`.")
            body["uris"] = [items[0]["uri"]]
            query = items[0]["name"]
        try:
            await self.api.user_request(ctx.author.id, "PUT", "me/player/play", json=body)
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success(f"Playing **{query}** on Spotify.")

    @spotify.command(name="queue", description="Queue a song")
    @describe(query="Track name or Spotify URI")
    async def spotify_queue(self, ctx: Context, *, query: str) -> None:
        if not await self._require_linked(ctx):
            return
        uri = query
        if not query.startswith("spotify:"):
            if "open.spotify.com" in query:
                uri = f"spotify:track:{query.split('/')[-1].split('?')[0]}"
            else:
                result = await self.api.client_search(query, limit=1)
                items = (result or {}).get("tracks", {}).get("items", [])
                if not items:
                    return await ctx.warn(f"No track found for `{query}`.")
                uri = items[0]["uri"]
        try:
            await self.api.user_request(
                ctx.author.id,
                "POST",
                "me/player/queue",
                params={"uri": uri},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success("Queued track on Spotify.")

    @spotify.command(name="pause", description="Pause the current song")
    async def spotify_pause(self, ctx: Context) -> None:
        if await self._user_action(ctx, "PUT", "me/player/pause"):
            await ctx.success("Paused Spotify playback.")

    @spotify.command(name="resume", description="Resume the current song")
    async def spotify_resume(self, ctx: Context) -> None:
        if await self._user_action(ctx, "PUT", "me/player/play"):
            await ctx.success("Resumed Spotify playback.")

    @spotify.command(name="next", description="Skip to the next song")
    async def spotify_next(self, ctx: Context) -> None:
        if await self._user_action(ctx, "POST", "me/player/next"):
            await ctx.success("Skipped to the next track.")

    @spotify.command(name="previous", description="Skip to the previous song")
    async def spotify_previous(self, ctx: Context) -> None:
        if await self._user_action(ctx, "POST", "me/player/previous"):
            await ctx.success("Skipped to the previous track.")

    @spotify.command(name="shuffle", description="Toggle playback shuffle")
    @describe(option="on or off")
    async def spotify_shuffle(self, ctx: Context, option: str | None = None) -> None:
        if not await self._require_linked(ctx):
            return
        state = None
        if option is not None:
            lowered = option.lower()
            if lowered in {"on", "true", "enable", "yes"}:
                state = True
            elif lowered in {"off", "false", "disable", "no"}:
                state = False
            else:
                return await ctx.warn("Use `on` or `off`.")
        else:
            try:
                playback = await self.api.user_request(ctx.author.id, "GET", "me/player")
            except RuntimeError as exc:
                return await ctx.fail(str(exc))
            state = not bool((playback or {}).get("shuffle_state"))
        try:
            await self.api.user_request(
                ctx.author.id,
                "PUT",
                "me/player/shuffle",
                params={"state": str(state).lower()},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success(f"Shuffle **{'enabled' if state else 'disabled'}**.")

    @spotify.command(name="repeat", description="Repeat the current song")
    @describe(mode="off, track, or context")
    async def spotify_repeat(self, ctx: Context, mode: str | None = None) -> None:
        if not await self._require_linked(ctx):
            return
        mapping = {"off": "off", "track": "track", "song": "track", "context": "context", "queue": "context"}
        if mode is None:
            try:
                playback = await self.api.user_request(ctx.author.id, "GET", "me/player")
            except RuntimeError as exc:
                return await ctx.fail(str(exc))
            current = (playback or {}).get("repeat_state", "off")
            order = ["off", "context", "track"]
            mode = order[(order.index(current) + 1) % len(order)]
        else:
            mode = mapping.get(mode.lower())
            if mode is None:
                return await ctx.warn("Use `off`, `track`, or `context`.")
        try:
            await self.api.user_request(
                ctx.author.id,
                "PUT",
                "me/player/repeat",
                params={"state": mode},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success(f"Repeat mode set to **{mode}**.")

    @spotify.command(name="seek", description="Seek to position in current song")
    @describe(seconds="Position in seconds")
    async def spotify_seek(self, ctx: Context, seconds: int) -> None:
        if seconds < 0:
            return await ctx.warn("Seconds must be zero or greater.")
        if not await self._require_linked(ctx):
            return
        try:
            await self.api.user_request(
                ctx.author.id,
                "PUT",
                "me/player/seek",
                params={"position_ms": seconds * 1000},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success(f"Seeked to **{seconds}s**.")

    @spotify.command(name="volume", description="Adjust current player volume")
    @describe(percent="Volume from 0 to 100")
    async def spotify_volume(self, ctx: Context, percent: int) -> None:
        if percent < 0 or percent > 100:
            return await ctx.warn("Volume must be between **0** and **100**.")
        if not await self._require_linked(ctx):
            return
        try:
            await self.api.user_request(
                ctx.author.id,
                "PUT",
                "me/player/volume",
                params={"volume_percent": percent},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success(f"Volume set to **{percent}%**.")

    @spotify.command(name="like", description="Like your current playing song on Spotify")
    async def spotify_like(self, ctx: Context) -> None:
        if not await self._require_linked(ctx):
            return
        try:
            playback = await self.api.user_request(ctx.author.id, "GET", "me/player/currently-playing")
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        if not playback or not playback.get("item"):
            return await ctx.warn("Nothing is playing on Spotify.")
        track_id = playback["item"]["id"]
        try:
            await self.api.user_request(
                ctx.author.id,
                "PUT",
                f"me/tracks",
                params={"ids": track_id},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success(f"Liked **{playback['item']['name']}**.")

    @spotify.command(name="unlike", description="Unlike your current playing song on Spotify")
    async def spotify_unlike(self, ctx: Context) -> None:
        if not await self._require_linked(ctx):
            return
        try:
            playback = await self.api.user_request(ctx.author.id, "GET", "me/player/currently-playing")
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        if not playback or not playback.get("item"):
            return await ctx.warn("Nothing is playing on Spotify.")
        track_id = playback["item"]["id"]
        try:
            await self.api.user_request(
                ctx.author.id,
                "DELETE",
                "me/tracks",
                params={"ids": track_id},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success(f"Unliked **{playback['item']['name']}**.")

    @spotify.command(name="toptracks", description="Show top tracks for the specified time frame")
    @describe(duration="week, month, year, or all")
    async def spotify_toptracks(self, ctx: Context, duration: str = "month") -> None:
        if not await self._require_linked(ctx):
            return
        time_range = TOP_DURATIONS.get(duration.lower(), "medium_term")
        try:
            data = await self.api.user_request(
                ctx.author.id,
                "GET",
                "me/top/tracks",
                params={"time_range": time_range, "limit": 10},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        items = (data or {}).get("items", [])
        if not items:
            return await ctx.warn("No top tracks found.")
        lines = [_track_line(i, track) for i, track in enumerate(items, 1)]
        embed = panel_embed(
            title=f"Top Tracks — {duration}",
            color=color.base,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @spotify.command(name="topartists", description="Show top artists for the specified time frame")
    @describe(duration="week, month, year, or all")
    async def spotify_topartists(self, ctx: Context, duration: str = "month") -> None:
        if not await self._require_linked(ctx):
            return
        time_range = TOP_DURATIONS.get(duration.lower(), "medium_term")
        try:
            data = await self.api.user_request(
                ctx.author.id,
                "GET",
                "me/top/artists",
                params={"time_range": time_range, "limit": 10},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        items = (data or {}).get("items", [])
        if not items:
            return await ctx.warn("No top artists found.")
        lines = [f"`{i}.` **{artist['name']}**" for i, artist in enumerate(items, 1)]
        embed = panel_embed(
            title=f"Top Artists — {duration}",
            color=color.base,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @spotify.group(
        name="device",
        description="Change the device that youre listening to Spotify with",
        invoke_without_command=True,
    )
    async def spotify_device(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        await self.spotify_device_list(ctx)

    @spotify_device.command(name="list", description="List all current devices connected to your Spotify account")
    async def spotify_device_list(self, ctx: Context) -> None:
        if not await self._require_linked(ctx):
            return
        try:
            data = await self.api.user_request(ctx.author.id, "GET", "me/player/devices")
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        devices = (data or {}).get("devices", [])
        if not devices:
            return await ctx.warn("No active Spotify devices found.")
        lines = []
        for index, device in enumerate(devices, 1):
            active = " (active)" if device.get("is_active") else ""
            lines.append(f"`{index}.` **{device['name']}** — {device.get('type', 'device')}{active}")
        embed = panel_embed(title="Spotify Devices", color=color.base, lines=lines, timestamp=False)
        await ctx.send(embed=embed)

    @spotify_device.command(name="set", description="Switch to a device by position")
    @describe(position="Device number from device list")
    async def spotify_device_set(self, ctx: Context, position: int) -> None:
        if not await self._require_linked(ctx):
            return
        try:
            data = await self.api.user_request(ctx.author.id, "GET", "me/player/devices")
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        devices = (data or {}).get("devices", [])
        if position < 1 or position > len(devices):
            return await ctx.warn("Invalid device position.")
        device = devices[position - 1]
        try:
            await self.api.user_request(
                ctx.author.id,
                "PUT",
                "me/player",
                json={"device_ids": [device["id"]], "play": True},
            )
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        await ctx.success(f"Transferred playback to **{device['name']}**.")

    @spotify.command(name="vc", description="Play your current track in a voice channel")
    async def spotify_vc(self, ctx: Context) -> None:
        if not await self._require_linked(ctx):
            return
        try:
            playback = await self.api.user_request(ctx.author.id, "GET", "me/player/currently-playing")
        except RuntimeError as exc:
            return await ctx.fail(str(exc))
        if not playback or not playback.get("item"):
            return await ctx.warn("Nothing is playing on Spotify.")
        item = playback["item"]
        query = f"{item['name']} {' '.join(a['name'] for a in item.get('artists', []))}"
        if not music_enabled:
            return await ctx.warn("music is disabled")
        music = ctx.bot.get_cog("Music")
        if music is None:
            return await ctx.warn("music cog isn't loaded")
        await music.play.callback(ctx, query=query, next=False)

    @spotify.command(name="search", description="Search for a track on Spotify")
    @describe(query="Track name to search for")
    async def spotify_search(self, ctx: Context, *, query: str) -> None:
        await self._search_tracks(ctx, query)

    @spotify.command(name="track", description="Get details about a Spotify track")
    @describe(url_or_id="Spotify track URL or ID")
    async def spotify_track(self, ctx: Context, url_or_id: str) -> None:
        track_id = url_or_id.split("/")[-1].split("?")[0] if "/" in url_or_id else url_or_id
        track = await self.api.get_track(track_id)
        if not track:
            await ctx.warn("Could not find that track.")
            return
        artists = ", ".join(a["name"] for a in track["artists"])
        embed = panel_embed(
            title=track["name"],
            color=color.base,
            lines=[f"By **{artists}**", f"Album: {track['album']['name']}"],
            timestamp=False,
        )
        embed.add_field(name="Duration", value=_format_ms(track["duration_ms"]), inline=True)
        embed.add_field(name="Popularity", value=f"{track['popularity']}/100", inline=True)
        embed.add_field(name="Listen on Spotify", value=f"[Open]({track['external_urls']['spotify']})", inline=True)
        if track["album"]["images"]:
            embed.set_thumbnail(url=track["album"]["images"][0]["url"])
        await ctx.send(embed=embed)

    @spotify.command(name="album", description="Get details about a Spotify album")
    @describe(url_or_id="Spotify album URL or ID")
    async def spotify_album(self, ctx: Context, url_or_id: str) -> None:
        album_id = url_or_id.split("/")[-1].split("?")[0] if "/" in url_or_id else url_or_id
        album = await self.api.get_album(album_id)
        if not album:
            await ctx.warn("Could not find that album.")
            return
        artists = ", ".join(a["name"] for a in album["artists"])
        embed = panel_embed(
            title=album["name"],
            color=color.base,
            lines=[f"By **{artists}**"],
            timestamp=False,
        )
        embed.add_field(name="Tracks", value=str(album["total_tracks"]), inline=True)
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
        embed = panel_embed(
            title="Spotify album search",
            color=color.base,
            lines=["Open Spotify album results for your query."],
            author=ctx.author.display_name,
            author_icon=ctx.author.display_avatar.url,
            timestamp=False,
        )
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(style=discord.ButtonStyle.link, emoji="🟢", label="Spotify", url=url)
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
        embed = panel_embed(
            title="Spotify track search",
            color=color.base,
            lines=["Open Spotify track results for your query."],
            author=ctx.author.display_name,
            author_icon=ctx.author.display_avatar.url,
            timestamp=False,
        )
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(style=discord.ButtonStyle.link, emoji="🟢", label="Spotify", url=url)
        )
        await ctx.send(embed=embed, view=view)


async def setup(bot: Vain):
    await bot.add_cog(Spotify(bot))
