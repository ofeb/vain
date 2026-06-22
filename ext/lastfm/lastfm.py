from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bleed import Bleed


import asyncio
import base64
import contextlib
import io
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.package import Package

from .events import LastfmEvents
from core.managers.values import emojis, api as api_values, lastfm_color as lastfm_color_config, lastfm_callback
from core.tools.guild_members import collect_guild_members
from core.tools import embed as embed_builder
from .api import LastFMApiClient
from .constants import LASTFM_EMBED_FOOTER_ICON_URL
from .crowns import LastFMCrownStore
from .library import LastFMLibraryStore
from .ui import build_link_view, send_pages as _send_pages

LASTFM_AUTH = "https://www.last.fm/api/auth/"

_LASTFM_EMBED_REPLY_SUFFIX = re.compile(r"(?:^|\s)--reply\s*$", re.IGNORECASE)

PERIODS = {
    "overall": "overall",
    "all": "overall",
    "7d": "7day",
    "7day": "7day",
    "week": "7day",
    "1m": "1month",
    "1mo": "1month",
    "1month": "1month",
    "month": "1month",
    "3m": "3month",
    "3month": "3month",
    "6m": "6month",
    "6month": "6month",
    "12m": "12month",
    "12month": "12month",
    "year": "12month",
}

PERIOD_LABELS = {
    "overall": "overall",
    "7day": "7d",
    "1month": "1m",
    "3month": "3m",
    "6month": "6m",
    "12month": "12m",
}



_PLAYS_QUERY_USER_MENTION_PREFIX_RE = re.compile(r"^<@!?([0-9]{17,20})>\s*(.*)$", re.DOTALL)
_PLAYS_QUERY_USER_ID_PREFIX_RE = re.compile(r"^([0-9]{17,20})\s+(.+)$", re.DOTALL)


class Lastfm(LastfmEvents, Package):

    def __init__(self, bot: Bleed) -> None:
        super().__init__(bot)
        self._api = LastFMApiClient(bot, lastfm_color=self._lastfm_color)
        self._library = LastFMLibraryStore(bot, self._api)
        self._crowns = LastFMCrownStore(
            bot,
            self._api,
            self._library,
            top_artists_fetcher=self._api._top_artists,
        )

        self._link_view = build_link_view
        self._today_scrobble_count = self._api._today_scrobble_count
        self._guild_lastfm_candidates = self._crowns._guild_lastfm_candidates
        self._ensure_crowns_table = self._crowns._ensure_crowns_table
        self._upsert_crown = self._crowns._upsert_crown
        self._get_crown = self._crowns._get_crown
        self._list_crown_history = self._crowns._list_crown_history
        self._list_crowns = self._crowns._list_crowns
        self._list_user_crowns = self._crowns._list_user_crowns
        self._ensure_artwork_table = self._crowns._ensure_artwork_table
        self._get_album_artwork = self._crowns._get_album_artwork
        self._linked_playcount_rows = self._crowns._linked_playcount_rows
        self._fetch_artist_rows = self._crowns._fetch_artist_rows
        self._fetch_track_rows = self._crowns._fetch_track_rows
        self._fetch_album_rows = self._crowns._fetch_album_rows
        self._seed_crowns_from_top_artists = self._crowns._seed_crowns_from_top_artists
        self._format_duration = self._api._format_duration
        self._text_value = self._api._text_value
        self._request = self._api._request
        self._signed_request = self._api._signed_request
        self._signed_post_request = self._api._signed_post_request
        self._write_action_ok = self._api.write_action_ok
        self._api_error_message = self._api.api_error_message
        self._canonical_track_names_for_user = self._api.canonical_track_names_for_user
        self._spotify_access_token = self._api._spotify_access_token
        self._spotify_track_lookup = self._api._spotify_track_lookup
        self._artist_search = self._api._artist_search
        self._track_search = self._api._track_search
        self._album_search = self._api._album_search
        self._resolve_artist_name = self._api._resolve_artist_name
        self._resolve_track_identity = self._api._resolve_track_identity
        self._resolve_album_identity = self._api._resolve_album_identity
        self._session_key_for = self._api._session_key_for
        self._clean_query_url = self._api._clean_query_url
        self._truncate_text = self._api._truncate_text
        self._poll_lastfm_session = self._api._poll_lastfm_session
        self._get_linked_user = self._api._get_linked_user
        self._username_for = self._api._username_for
        self._lastfm_user_info = self._api._lastfm_user_info
        self._nowplaying = self._api._nowplaying
        self._artist_crown = self._crowns._artist_crown
        self._split_artist_track = self._api._split_artist_track
        self._split_artist_album = self._api._split_artist_album
        self._top_artists = self._api._top_artists
        self._refresh_library = self._library.refresh_library
        self._indexed_random_artist = self._library.get_random_artist

    def cog_unload(self) -> None:
        asyncio.create_task(self._api.close())

    def _lastfm_color(self) -> discord.Color:
        return discord.Color.from_str(lastfm_color_config.value)

    def _info_color(self) -> discord.Color:
        return self._lastfm_color()

    async def _resolve_color(self, user_id: int) -> discord.Color:
        if getattr(self.bot, "db", None):
            stored = await self.bot.db.get_lastfm_color(user_id)
            if stored:
                raw = stored.strip()
                if raw:
                    if not raw.startswith("#"):
                        raw = f"#{raw}"
                    with contextlib.suppress(ValueError):
                        return discord.Color.from_str(raw)
        return self._info_color()

    async def _resolve_mode(self, user_id: int) -> str:
        if getattr(self.bot, "db", None):
            stored = await self.bot.db.get_lastfm_mode(user_id)
            if stored:
                return stored.strip().lower()
        return "default"

    async def _lastfm_custom_embed_settings(self, user_id: int) -> tuple[str | None, bool]:
        """Supports older Database instances missing ``get_lastfm_custom_embed_settings``."""
        db = getattr(self.bot, "db", None)
        if not db:
            return None, False
        getter = getattr(db, "get_lastfm_custom_embed_settings", None)
        if getter is not None:
            return await getter(user_id)
        legacy = getattr(db, "get_lastfm_custom_embed", None)
        if legacy is not None:
            script = await legacy(user_id)
            return script, False
        return None, False

    @staticmethod
    def _format_number(value: str | int | None) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, int):
            return f"{value:,}"
        text = str(value).strip()
        if not text:
            return "n/a"
        cleaned = re.sub(r"[ ,]", "", text)
        if cleaned.isdigit():
            return f"{int(cleaned):,}"
        return text

    @classmethod
    def _number_value(cls, value: str | int | None) -> int:
        if value is None:
            return 0
        if isinstance(value, int):
            return max(0, value)
        text = str(value).strip()
        if not text:
            return 0
        cleaned = re.sub(r"[ ,]", "", text)
        if cleaned.isdigit():
            return int(cleaned)
        return 0

    @classmethod
    def _plays_text(cls, value: str | int | None) -> str:
        number = cls._number_value(value)
        word = "play" if number == 1 else "plays"
        return f"{cls._format_number(number)} {word}"

    @classmethod
    def _scrobbles_text(cls, value: str | int | None) -> str:
        number = cls._number_value(value)
        word = "scrobble" if number == 1 else "scrobbles"
        return f"{cls._format_number(number)} {word}"

    @classmethod
    def _listeners_text(cls, value: str | int | None) -> str:
        number = cls._number_value(value)
        word = "listener" if number == 1 else "listeners"
        return f"{cls._format_number(number)} {word}"

    @staticmethod
    def _lastfm_emoji() -> str:
        return emojis.lastfm

    @staticmethod
    def _set_lastfm_footer(
        embed: discord.Embed, text: str, *, icon_url: str | None = None
    ) -> None:
        embed.set_footer(
            text=text,
            icon_url=LASTFM_EMBED_FOOTER_ICON_URL if icon_url is None else icon_url,
        )

    @staticmethod
    def _lastfm_embed_description(body: str) -> str | None:
        stripped = body.strip()
        return stripped if stripped else None

    @staticmethod
    def _set_lastfm_user_author(embed: discord.Embed, user: discord.abc.User) -> None:
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

    @staticmethod
    def _set_lastfm_guild_author(
        embed: discord.Embed, guild: discord.Guild, fallback_user: discord.abc.User
    ) -> None:
        icon = guild.icon.url if guild.icon else fallback_user.display_avatar.url
        embed.set_author(name=guild.name, icon_url=icon)

    @staticmethod
    def _quote_block(*lines: str) -> str:
        return "\n".join(f"> {line}" for line in lines if line)

    @staticmethod
    def _line_block(*lines: str) -> str:
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _meta_line(*parts: str) -> str:
        return " • ".join(part for part in parts if part)

    @staticmethod
    def _lastfm_target_label(user: discord.abc.User) -> str:
        if isinstance(user, discord.Member):
            return user.display_name
        return user.global_name or user.name

    def _lastfm_plays_line(
        self,
        ctx: Context,
        target: discord.abc.User,
        *,
        count: str | int,
        name: str,
        url: str,
    ) -> str:
        if target.id == ctx.author.id:
            who = "You have"
        else:
            who = f"**{self._lastfm_target_label(target)}** has"
        return f"{who} **{self._plays_text(count)}** for [**{name}**]({url})"

    async def _user_from_id(self, ctx: Context, user_id: int) -> discord.User | None:
        if ctx.guild:
            member = ctx.guild.get_member(user_id)
            if member:
                return member
        cached = ctx.bot.get_user(user_id)
        if cached:
            return cached
        try:
            return await ctx.bot.fetch_user(user_id)
        except discord.HTTPException:
            return None

    async def _consume_optional_plays_query_target(
        self, ctx: Context, query: str
    ) -> tuple[discord.abc.User | None, str | None]:
        """Split ``mention/id + rest`` from plays-style queries.

        Returns ``(member_or_none, text_or_none)``. ``text`` is ``None`` only when a
        user prefix was present but could not be resolved (caller should stop).
        """
        stripped = query.strip()
        if not stripped:
            return None, ""

        m = _PLAYS_QUERY_USER_MENTION_PREFIX_RE.match(stripped)
        if m:
            uid = int(m.group(1))
            tail = m.group(2).strip()
            user = await self._user_from_id(ctx, uid)
            if user is None:
                await ctx.warn("I couldn't find that **user**.")
                return None, None
            return user, tail

        m = _PLAYS_QUERY_USER_ID_PREFIX_RE.match(stripped)
        if m:
            uid = int(m.group(1))
            tail = m.group(2).strip()
            user = await self._user_from_id(ctx, uid)
            if user is None:
                await ctx.warn("I couldn't find that **user**.")
                return None, None
            return user, tail

        return None, stripped

    async def _optional_mention_target_only(
        self, ctx: Context, query: str | None
    ) -> tuple[discord.abc.User | None, bool]:
        """Parse optional leading ``<@…>`` / user-id target only; remainder must be empty."""
        member, rest = await self._consume_optional_plays_query_target(ctx, (query or "").strip())
        if rest is None:
            return None, False
        if rest.strip():
            await ctx.warn(
                "Use only an optional **mention** or **numeric user ID** to pick someone else "
                "(plain names are treated as artist/track/album text, not Discord users)."
            )
            return None, False
        return member, True

    async def _member_and_optional_period_tail(
        self, ctx: Context, query: str
    ) -> tuple[discord.abc.User | None, str | None, bool]:
        """Leading mention/id, optional trailing **period** token (see ``PERIODS`` keys)."""
        member, rest = await self._consume_optional_plays_query_target(ctx, query.strip())
        if rest is None:
            return None, None, False
        tokens = rest.split()
        period_key: str | None = None
        if tokens:
            last = tokens[-1].strip().lower()
            if PERIODS.get(last) is not None:
                period_key = last
                tokens = tokens[:-1]
        if tokens:
            await ctx.warn(
                "Use a **mention** or **user ID** for someone else, then an optional "
                "**period** (`overall`, `7d`, `1m`, `3m`, `6m`, `12m`)."
            )
            return None, None, False
        return member, period_key, True

    @staticmethod
    def _user_url(username: str) -> str:
        return f"https://www.last.fm/user/{quote_plus(username)}"

    @staticmethod
    def _is_clear_token(value: str | None) -> bool:
        if value is None:
            return False
        return value.strip().lower() in {"off", "none", "clear", "reset", "remove", "disable"}

    @staticmethod
    def _artist_url(artist: str) -> str:
        return f"https://www.last.fm/music/{quote_plus(artist)}"

    @staticmethod
    def _album_url(artist: str, album: str) -> str:
        return f"https://www.last.fm/music/{quote_plus(artist)}/{quote_plus(album)}"

    @staticmethod
    def _track_url(artist: str, track: str) -> str:
        return f"https://www.last.fm/music/{quote_plus(artist)}/_/{quote_plus(track)}"

    def _period_param(self, period: str | None) -> str | None:
        if not period:
            return "overall"
        key = period.strip().lower()
        return PERIODS.get(key)

    @staticmethod
    def _taste_top_artist_names(rows: list[dict]) -> list[str]:
        names: list[str] = []
        for row in rows:
            name = row.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return names

    @staticmethod
    def _taste_shared_artist_names(comparison: dict) -> list[str]:
        result = comparison.get("result") or {}
        artists_block = result.get("artists") or {}
        raw = artists_block.get("artist", [])
        if isinstance(raw, dict):
            raw = [raw]
        elif not isinstance(raw, list):
            raw = []
        names: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                n = item.get("name")
                if isinstance(n, str) and n.strip():
                    names.append(n.strip())
        return names

    @staticmethod
    def _strip_lastfm_embed_reply_flag(raw: str | None) -> tuple[str | None, bool]:
        if raw is None:
            return None, False
        text = raw.rstrip()
        if not text:
            return raw, False
        match = _LASTFM_EMBED_REPLY_SUFFIX.search(text)
        if not match:
            return raw, False
        stripped = text[: match.start()].rstrip()
        return stripped, True

    async def _send_lastfm_np_custom_embed(
        self,
        ctx: Context,
        parsed: embed_builder.ParsedEmbedScript,
        *,
        np_reply: bool,
    ) -> discord.Message:
        kwargs = parsed.to_send_kwargs()
        ref = None
        if ctx.interaction and ctx.interaction.message:
            ref = ctx.interaction.message
        elif ctx.message:
            ref = ctx.message
        use_reply = bool(np_reply and ref is not None)
        if use_reply:
            kwargs["reference"] = ref
            kwargs["mention_author"] = False
        return await ctx.send(**kwargs)

    async def _respond_lastfm_track_write(
        self,
        ctx: Context,
        data: dict | None,
        artist_name: str,
        track_name: str,
        *,
        past_label: str,
        username: str,
    ) -> None:
        if self._write_action_ok(data):
            msg = f"Successfully **{past_label}** **{track_name}** by **{artist_name}**."
            user_payload = None
            with contextlib.suppress(Exception):
                user_payload = await self._lastfm_user_info(username, use_cache=False)
            user_block = user_payload.get("user") if isinstance(user_payload, dict) else None
            if isinstance(user_block, dict):
                playcount = user_block.get("playcount")
                if playcount is not None and str(playcount).strip():
                    msg += f"\n**Total scrobbles**: `{self._format_number(playcount)}`"
            await ctx.success(msg)
            return
        err = self._api_error_message(data)
        if err:
            await ctx.warn(self._truncate_text(err, 500))
            return
        await ctx.warn(
            "Last.fm did not confirm that action. Try again or check your **connection** and **link**."
        )

    async def _render_lastfm_script(
        self,
        ctx: Context,
        username: str,
        track: dict,
        target: discord.abc.User | None,
        script: str,
    ) -> str:
        tokens = set(re.findall(r"\{([a-zA-Z0-9_.]+)\}", script))
        func_tokens = re.findall(r"\{(lower|proper)\(([^}]+)\)\}", script)
        tokens.update(token.strip() for _, token in func_tokens if token.strip())

        track_name = track.get("name", "Unknown track")
        artist_name = track.get("artist", {}).get("#text") or "Unknown artist"
        album_name = track.get("album", {}).get("#text") or "Unknown album"
        track_url = track.get("url", "https://www.last.fm")
        track_images = track.get("image", [])
        lastfm_image = track_images[-1].get("#text") if track_images else "n/a"

        user_info = None
        if tokens & {"user.plays", "user.avatar", "user.url", "user.name"}:
            data = await self._lastfm_user_info(username)
            user_info = data.get("user", {}) if data else {}

        track_info = None
        if tokens & {"track.plays", "album.url", "album.cover", "artist.url"}:
            data = await self._request(
                {"method": "track.getInfo", "artist": artist_name, "track": track_name, "username": username}
            )
            track_info = data.get("track", {}) if data else {}

        artist_info = None
        if tokens & {"artist.plays", "artist.url"}:
            data = await self._request(
                {"method": "artist.getInfo", "artist": artist_name, "username": username}
            )
            artist_info = data.get("artist", {}) if data else {}

        album_info = None
        if tokens & {"album.url", "album.cover"} and not track_info:
            data = await self._request(
                {"method": "album.getInfo", "artist": artist_name, "album": album_name, "username": username}
            )
            album_info = data.get("album", {}) if data else {}

        spotify_data = {}
        if tokens & {"track.spotify_url", "track.release_date", "track.duration", "artist.image"}:
            spotify_data = await self._spotify_track_lookup(
                artist_name,
                track_name,
                need_artist_image="artist.image" in tokens,
            )

        crown = ""
        if "user.artist_crown" in tokens:
            crown = await self._artist_crown(ctx, artist_name, target.id if target else ctx.author.id)

        artist_url = "n/a"
        if artist_info:
            artist_url = artist_info.get("url", "n/a")
        if track_info and track_info.get("artist"):
            artist_url = track_info["artist"].get("url", artist_url)

        album_url = "n/a"
        album_cover = "n/a"
        if track_info and track_info.get("album"):
            album_url = track_info["album"].get("url", "n/a")
            images = track_info["album"].get("image", [])
            album_cover = images[-1].get("#text") if images else album_cover
        if album_info:
            album_url = album_info.get("url", album_url)
            images = album_info.get("image", [])
            if images:
                album_cover = images[-1].get("#text") or album_cover
        if album_cover == "n/a":
            album_cover = lastfm_image or "n/a"

        user_avatar = "n/a"
        if user_info:
            images = user_info.get("image", [])
            if images:
                user_avatar = images[-1].get("#text") or "n/a"
        mapping = {
            "user.name": user_info.get("name", username) if user_info else username,
            "user.avatar": user_avatar,
            "user.plays": self._format_number((user_info.get("playcount") if user_info else "n/a") or "n/a"),
            "user.artist_crown": crown,
            "user.url": user_info.get("url", "n/a") if user_info else "n/a",
            "author": f"{ctx.author.name}#{ctx.author.discriminator}",
            "author.name": ctx.author.name,
            "author.nickname": (ctx.author.nick if isinstance(ctx.author, discord.Member) else None) or "n/a",
            "author.discriminator": ctx.author.discriminator,
            "album.name": album_name,
            "album.url": album_url,
            "album.cover": album_cover,
            "track.name": track_name,
            "track.url": track_url,
            "track.spotify_url": spotify_data.get("spotify_url", "n/a"),
            "track.release_date": spotify_data.get("release_date", "n/a"),
            "track.duration": spotify_data.get("duration", "n/a"),
            "track.plays": self._format_number((track_info.get("userplaycount") if track_info else "n/a") or "n/a"),
            "artist.name": artist_name,
            "artist.plays": self._format_number(
                (artist_info.get("stats", {}).get("userplaycount") if artist_info else "n/a") or "n/a"
            ),
            "artist.url": artist_url,
            "artist.image": spotify_data.get("artist_image", "n/a"),
        }

        def resolve_token(token: str) -> str:
            value = mapping.get(token, f"{{{token}}}")
            return str(value)

        def replace_func(match: re.Match[str]) -> str:
            func = match.group(1)
            inner = match.group(2).strip()
            value = resolve_token(inner)
            if func == "lower":
                return value.lower()
            if func == "proper":
                return self._format_number(value)
            return value

        rendered = re.sub(r"\{(lower|proper)\(([^}]+)\)\}", replace_func, script)
        for key, value in mapping.items():
            rendered = rendered.replace(f"{{{key}}}", str(value))
        return rendered

    def _list_pages(
        self,
        title: str,
        lines: list[str],
        author: discord.abc.User,
        *,
        footer_prefix: str | None = None,
        color: discord.Color | None = None,
    ) -> list[discord.Embed]:
        per_page = 10
        pages: list[discord.Embed] = []
        total = len(lines)
        total_pages = max(1, (total + per_page - 1) // per_page)
        for index in range(total_pages):
            chunk = lines[index * per_page : (index + 1) * per_page]
            embed = discord.Embed(
                title=title,
                description=self._lastfm_embed_description("\n".join(chunk)),
                color=color or self._info_color(),
            )
            self._set_lastfm_user_author(embed, author)
            footer = f"Page {index + 1}/{total_pages} • {total} entries"
            if footer_prefix:
                footer = f"{footer_prefix} • {footer}"
            self._set_lastfm_footer(embed, footer)
            pages.append(embed)
        return pages

    async def _send_list(
        self,
        ctx: Context,
        title: str,
        lines: list[str],
        *,
        footer_prefix: str | None = None,
        color: discord.Color | None = None,
    ) -> None:
        pages = self._list_pages(title, lines, ctx.author, footer_prefix=footer_prefix, color=color)
        await _send_pages(ctx, pages)

    async def _fetch_top_fans(self, method: str, params: dict[str, str]) -> list[dict]:
        data = await self._request({"method": method, **params, "limit": "200"})
        if not data:
            return []
        key = "topfans"
        if method == "album.getTopFans":
            key = "topfans"
        fans = data.get(key, {}).get("user", [])
        return fans if isinstance(fans, list) else [fans]

    @commands.group(name="lastfm", aliases=["lf", "fm"], invoke_without_command=True)
    async def lastfm(self, ctx: Context) -> discord.Message:
        """
        Integrate your Last.fm account with bored and view your scrobble stats
        """
        return await self.lastfm_now(ctx)

    @lastfm.command(name="login")
    async def lastfm_login(self, ctx: Context, username: str) -> None:
        """
        Link your Last.fm username to bored
        """
        username = username.strip().lstrip("@")
        if not username:
            await ctx.warn("Provide your **Last.fm username**.")
            return
        if not getattr(self.bot, "db", None):
            await ctx.warn("Last.fm is not configured on this bot.")
            return
        data = await self._request({"method": "user.getInfo", "user": username})
        user_data = data.get("user") if data else None
        if not user_data:
            await ctx.warn(f"Could not find Last.fm user **{username}**.")
            return
        actual = self._text_value(user_data.get("name")) or username
        await self.bot.db.set_lastfm_user(ctx.author.id, actual, None)
        await ctx.success(f"Linked your account to **[{actual}](https://www.last.fm/user/{quote_plus(actual)})**.")

    @lastfm.command(name="logout")
    async def lastfm_logout(self, ctx: Context) -> None:
        """
        Remove your Last.fm account with bored
        """
        if not getattr(self.bot, "db", None):
            await ctx.warn("Last.fm is not configured on this bot.")
            return
        data = await self.bot.db.get_lastfm_user(ctx.author.id)
        if not data:
            await ctx.warn(
                f"You do not have a **Last.fm** account linked yet. "
                f"You can link it with `{ctx.clean_prefix}lastfm login`."
            )
            return
        await self.bot.db.remove_lastfm_user(ctx.author.id)
        await ctx.success("Successfully **removed** your Last.fm account.")

    @lastfm.command(name="whois")
    async def lastfm_whois(self, ctx: Context, *, query: str | None = None) -> None:
        """
        View Last.fm profile information
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        target = member or ctx.author
        username = await self._username_for(ctx, member)
        if not username:
            return
        data = await self._lastfm_user_info(username)
        if not data or "user" not in data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        user = data["user"]
        profile_url = user.get("url") or f"https://www.last.fm/user/{quote_plus(username)}"
        real_name = user.get("realname") or "N/A"
        country = user.get("country") or "N/A"
        age = user.get("age") or "N/A"
        total_scrobbles_value = self._number_value(user.get("playcount"))
        playcount = self._format_number(total_scrobbles_value)
        artist_count_value = self._number_value(user.get("artist_count"))
        album_count_value = self._number_value(user.get("album_count"))
        track_count_value = self._number_value(user.get("track_count"))
        artist_count = self._format_number(artist_count_value)
        album_count = self._format_number(album_count_value)
        track_count = self._format_number(track_count_value)
        playlists = self._format_number(user.get("playlists"))
        subscriber = "Yes" if str(user.get("subscriber", "0")) == "1" else "No"
        registered_raw = user.get("registered")
        registered_unix = None
        if isinstance(registered_raw, dict):
            registered_unix = self._number_value(registered_raw.get("unixtime"))
        elif isinstance(registered_raw, str):
            registered_unix = self._number_value(registered_raw)
        joined_value = "N/A"
        days_since_join = None
        if registered_unix and registered_unix > 0:
            joined_value = f"<t:{registered_unix}:D> - <t:{registered_unix}:R>"
            joined_dt = datetime.fromtimestamp(registered_unix, tz=timezone.utc)
            days_since_join = max(1, (datetime.now(tz=timezone.utc) - joined_dt).days)

        avg_scrobbles_per_day = None
        if days_since_join and total_scrobbles_value > 0:
            avg_scrobbles_per_day = round(total_scrobbles_value / days_since_join, 1)

        avg_albums_per_artist = None
        avg_tracks_per_artist = None
        if artist_count_value > 0:
            if album_count_value > 0:
                avg_albums_per_artist = round(album_count_value / artist_count_value, 1)
            if track_count_value > 0:
                avg_tracks_per_artist = round(track_count_value / artist_count_value, 1)

        top10_share = None
        top_artists_data = await self._request(
            {"method": "user.getTopArtists", "user": username, "period": "overall", "limit": "10"}
        )
        if top_artists_data:
            top_artists = top_artists_data.get("topartists", {}).get("artist", [])
            if isinstance(top_artists, dict):
                top_artists = [top_artists]
            top10_total = 0
            for artist in top_artists:
                top10_total += self._number_value(artist.get("playcount"))
            if total_scrobbles_value > 0 and top10_total > 0:
                top10_share = round((top10_total / total_scrobbles_value) * 100, 1)

        most_active_day = None
        recent_data = await self._request({"method": "user.getRecentTracks", "user": username, "limit": "200"})
        if recent_data:
            tracks = recent_data.get("recenttracks", {}).get("track", [])
            if isinstance(tracks, dict):
                tracks = [tracks]
            day_counts: dict[str, int] = {}
            for track in tracks:
                ts = track.get("date", {}).get("uts")
                if not ts:
                    continue
                ts_value = self._number_value(ts)
                if ts_value <= 0:
                    continue
                weekday = datetime.fromtimestamp(ts_value, tz=timezone.utc).strftime("%A")
                day_counts[weekday] = day_counts.get(weekday, 0) + 1
            if day_counts:
                most_active_day = max(day_counts.items(), key=lambda item: item[1])[0]

        metric_lines = []
        if avg_scrobbles_per_day is not None:
            metric_lines.append(f"Average of **{avg_scrobbles_per_day}** scrobbles per day")
        if avg_albums_per_artist is not None and avg_tracks_per_artist is not None:
            metric_lines.append(
                f"Average of **{avg_albums_per_artist}** albums and **{avg_tracks_per_artist}** tracks per artist"
            )
        if top10_share is not None:
            metric_lines.append(f"Top **10** artists make up **{top10_share}%** of scrobbles")
        if most_active_day:
            metric_lines.append(f"Most active day of the week is **{most_active_day}**")

        color = await self._resolve_color(target.id)
        insights = self._quote_block(*metric_lines) if metric_lines else "> No additional insights available."
        embed = discord.Embed(
            title=user.get("name", username),
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"**Scrobbles**: {playcount}",
                    f"**Joined**: {joined_value}",
                    f"**Subscriber**: {subscriber}",
                )
            ),
            url=profile_url,
            color=color,
        )
        embed.add_field(
            name="Library",
            value=self._quote_block(
                f"**Tracks**: {track_count}",
                f"**Albums**: {album_count}",
                f"**Artists**: {artist_count}",
            ),
            inline=True,
        )
        embed.add_field(
            name="Account",
            value=self._quote_block(
                f"**Name**: {real_name}",
                f"**Country**: {country}",
                f"**Age**: {age}",
                f"**Playlists**: {playlists}",
            ),
            inline=True,
        )
        embed.add_field(name="Insights", value=insights, inline=False)
        self._set_lastfm_user_author(embed, target)
        self._set_lastfm_footer(embed, self._meta_line("Last.fm profile", username))
        image = user.get("image", [])
        if image:
            embed.set_thumbnail(url=image[-1].get("#text") or image[0].get("#text"))
        else:
            embed.set_thumbnail(url=target.display_avatar.url)
        view = self._link_view(
            (self._lastfm_emoji(), "Profile", profile_url),
            ("📚", "Library", f"https://www.last.fm/user/{quote_plus(username)}/library"),
            ("❤️", "Loved", f"https://www.last.fm/user/{quote_plus(username)}/loved"),
        )
        return await ctx.send(embed=embed, view=view)

    @lastfm.command(name="now", aliases=["np", "nowplaying"])
    async def lastfm_now(self, ctx: Context, *, query: str | None = None) -> None:
        """
        Shows your current song playing from Last.fm
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        track = await self._nowplaying(username)
        if not track:
            await ctx.info(f"{ctx.author.mention}: No **songs** are playing right now.")
            return
        total_scrobbles = None
        user_info = await self._lastfm_user_info(username)
        if user_info and "user" in user_info:
            total_scrobbles = user_info["user"].get("playcount")
        target_user = member or ctx.author
        mode = await self._resolve_mode(target_user.id)
        color = await self._resolve_color(target_user.id)
        if mode == "custom":
            if not getattr(self.bot, "db", None):
                return
            script, np_reply = await self._lastfm_custom_embed_settings(target_user.id)
            if not script:
                await ctx.warn(
                    f"You do not have a **custom embed** set yet. "
                    f"You can set it with `{ctx.clean_prefix}lastfm embed (script)`."
                )
                return
            if not embed_builder.is_embed_script(script):
                await ctx.warn("Your custom embed must be an embed script. Use `lastfm embed {embed}$v...`.")
                return
            rendered = await self._render_lastfm_script(ctx, username, track, member, script)
            parsed = await embed_builder.parse_embed_script(rendered, ctx)
            if not parsed.content and not parsed.embed and not parsed.embeds:
                await ctx.warn("Your custom embed did not render any content.")
                return
            if parsed.embed and (parsed.embed.color is None or parsed.embed.color.value == 0):
                parsed.embed.color = color
            if parsed.embeds:
                for item in parsed.embeds:
                    if item.color is None or item.color.value == 0:
                        item.color = color
            await self._send_lastfm_np_custom_embed(ctx, parsed, np_reply=np_reply)
            return
        track_name = track.get("name", "Unknown track")
        artist = track.get("artist", {}).get("#text") or "Unknown artist"
        album = track.get("album", {}).get("#text") or "Unknown album"
        url = track.get("url", "https://www.last.fm")
        if mode == "minimal":
            embed = discord.Embed(
                description=(
                    f"**{track_name}** - [{artist}](https://www.last.fm/music/{quote_plus(artist)})\n"
                    f"Album: {album}"
                ),
                color=color,
            )
        elif mode == "compact":
            embed = discord.Embed(
                description=(
                    f"**Track:** [{track_name}]({url})\n"
                    f"**Artist:** [{artist}](https://www.last.fm/music/{quote_plus(artist)})\n"
                    f"**Album:** {album}"
                ),
                color=color,
            )
        else:
            embed = discord.Embed(
                color=color,
            )
            embed.add_field(name="**Track**", value=f"[{track_name}]({url})", inline=True)
            embed.add_field(
                name="**Artist**",
                value=f"[{artist}](https://www.last.fm/music/{quote_plus(artist)})",
                inline=True,
            )
            footer_bits = [f"Album: {album}"]
            if total_scrobbles:
                footer_bits.append(f"Total Scrobbles: {self._format_number(total_scrobbles)}")
            self._set_lastfm_footer(embed, " - ".join(footer_bits))
        if total_scrobbles and mode in {"minimal", "compact"}:
            self._set_lastfm_footer(embed, f"{self._format_number(total_scrobbles)} total scrobbles")
        embed.set_author(
            name=f"Last.fm: {username}",
            url=f"https://www.last.fm/user/{username}",
            icon_url=target_user.display_avatar.url,
        )
        image = track.get("image", [])
        if image:
            embed.set_thumbnail(url=image[-1].get("#text") or image[0].get("#text"))
        message = await ctx.send(embed=embed)
        if getattr(self.bot, "db", None):
            reactions = await self.bot.db.get_lastfm_guild_reactions(ctx.guild.id) if ctx.guild else None
            if not reactions:
                reactions = await self.bot.db.get_lastfm_reactions(target_user.id)
            if reactions:
                for emoji in (reactions.get("upvote"), reactions.get("downvote")):
                    if emoji:
                        with contextlib.suppress(discord.HTTPException):
                            await message.add_reaction(emoji)

    @commands.command(name="nowplaying", aliases=["np"])
    async def nowplaying(self, ctx: Context, *, query: str | None = None) -> None:
        """
        Shows your current song playing from Last.fm
        """
        await self.lastfm_now(ctx, query=query)

    @lastfm.command(name="recent", aliases=["recenttracks", "recents", "r", "rc"])
    async def lastfm_recent(self, ctx: Context, *, query: str | None = None) -> None:
        """
        View your recent tracks
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        data = await self._request({"method": "user.getRecentTracks", "user": username, "limit": "50"})
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        tracks = data.get("recenttracks", {}).get("track", [])
        if not tracks:
            await ctx.info(f"{ctx.author.mention}: No **recent tracks** were found.")
            return
        lines = []
        for index, track in enumerate(tracks[:50], start=1):
            name = track.get("name", "Unknown track")
            artist = track.get("artist", {}).get("#text") or "Unknown artist"
            url = track.get("url", "https://www.last.fm")
            lines.append(f"`{index:02d}` **[{name}]({url})** - {artist}")
        await self._send_list(ctx, f"{username}'s recent tracks", lines)

    @lastfm.command(name="recentfor")
    async def lastfm_recentfor(self, ctx: Context, *, artist: str) -> None:
        """
        View your recent tracks for an artist
        """
        username = await self._username_for(ctx, None)
        if not username:
            return
        data = await self._request({"method": "user.getRecentTracks", "user": username, "limit": "100"})
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        tracks = data.get("recenttracks", {}).get("track", [])
        matches = [
            track
            for track in tracks
            if (track.get("artist", {}).get("#text") or "").lower() == artist.lower()
        ]
        if not matches:
            await ctx.info(f"{ctx.author.mention}: No **recent tracks** were found for `{artist}`.")
            return
        lines = []
        for index, track in enumerate(matches[:50], start=1):
            name = track.get("name", "Unknown track")
            url = track.get("url", "https://www.last.fm")
            lines.append(f"`{index:02d}` **[{name}]({url})**")
        await self._send_list(ctx, f"{username}'s recent tracks for {artist}", lines)

    @lastfm.command(name="topartists", aliases=["al", "as", "ta", "artistlist", "artists", "artistslist"])
    async def lastfm_topartists(
        self,
        ctx: Context,
        *,
        query: str | None = None,
    ) -> None:
        """
        View your most listened to artists
        """
        member, period_key, ok = await self._member_and_optional_period_tail(ctx, query or "")
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        period_param = self._period_param(period_key)
        if not period_param:
            await ctx.warn("Invalid **period**. Use: overall, 7d, 1m, 3m, 6m, 12m.")
            return
        data = await self._request(
            {"method": "user.getTopArtists", "user": username, "period": period_param, "limit": "50"}
        )
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        artists = data.get("topartists", {}).get("artist", [])
        if not artists:
            await ctx.info(f"{ctx.author.mention}: No **artists** were found.")
            return
        lines = []
        for index, artist in enumerate(artists[:50], start=1):
            name = artist.get("name", "Unknown artist")
            url = artist.get("url", "https://www.last.fm")
            plays = artist.get("playcount", "0")
            lines.append(f"`{index:02d}` **[{name}]({url})** ({self._plays_text(plays)})")
        await self._send_list(ctx, f"{username}'s top artists", lines)

    @lastfm.command(name="toptracks", aliases=["tt", "tl", "tracklist", "tracks", "trackslist", "ttracks"])
    async def lastfm_toptracks(
        self,
        ctx: Context,
        *,
        query: str | None = None,
    ) -> None:
        """
        View your most listened to tracks
        """
        member, period_key, ok = await self._member_and_optional_period_tail(ctx, query or "")
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        period_param = self._period_param(period_key)
        if not period_param:
            await ctx.warn("Invalid **period**. Use: overall, 7d, 1m, 3m, 6m, 12m.")
            return
        data = await self._request(
            {"method": "user.getTopTracks", "user": username, "period": period_param, "limit": "50"}
        )
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        tracks = data.get("toptracks", {}).get("track", [])
        if not tracks:
            await ctx.info(f"{ctx.author.mention}: No **tracks** were found.")
            return
        lines = []
        for index, track in enumerate(tracks[:50], start=1):
            name = track.get("name", "Unknown track")
            artist = track.get("artist", {}).get("name") or "Unknown artist"
            url = track.get("url", "https://www.last.fm")
            plays = track.get("playcount", "0")
            lines.append(f"`{index:02d}` **[{name}]({url})** - {artist} ({self._plays_text(plays)})")
        await self._send_list(ctx, f"{username}'s top tracks", lines)

    @lastfm.command(name="topalbums", aliases=["abl", "abs", "tab", "albumlist", "albums", "albumslist", "talbum"])
    async def lastfm_topalbums(
        self,
        ctx: Context,
        *,
        query: str | None = None,
    ) -> None:
        """
        View your most listened to albums
        """
        member, period_key, ok = await self._member_and_optional_period_tail(ctx, query or "")
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        period_param = self._period_param(period_key)
        if not period_param:
            await ctx.warn("Invalid **period**. Use: overall, 7d, 1m, 3m, 6m, 12m.")
            return
        data = await self._request(
            {"method": "user.getTopAlbums", "user": username, "period": period_param, "limit": "50"}
        )
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        albums = data.get("topalbums", {}).get("album", [])
        if not albums:
            await ctx.info(f"{ctx.author.mention}: No **albums** were found.")
            return
        lines = []
        for index, album in enumerate(albums[:50], start=1):
            name = album.get("name", "Unknown album")
            artist = album.get("artist", {}).get("name") or "Unknown artist"
            url = album.get("url", "https://www.last.fm")
            plays = album.get("playcount", "0")
            lines.append(f"`{index:02d}` **[{name}]({url})** - {artist} ({self._plays_text(plays)})")
        await self._send_list(ctx, f"{username}'s top albums", lines)

    @lastfm.command(name="toptentracks")
    async def lastfm_toptentracks(
        self,
        ctx: Context,
        *,
        artist: str,
    ) -> None:
        """
        View your top ten tracks for an artist
        """
        member, artist_query = await self._consume_optional_plays_query_target(ctx, artist)
        if artist_query is None:
            return
        if not artist_query:
            await ctx.warn("Provide an **artist** name.")
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        data = await self._request(
            {"method": "user.getTopTracks", "user": username, "limit": "100"}
        )
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        tracks = data.get("toptracks", {}).get("track", [])
        filtered = [
            track
            for track in tracks
            if (track.get("artist", {}).get("name") or "").lower() == artist_query.lower()
        ]
        if not filtered:
            await ctx.info(f"{ctx.author.mention}: No **tracks** were found for `{artist_query}`.")
            return
        lines = []
        for index, track in enumerate(filtered[:10], start=1):
            name = track.get("name", "Unknown track")
            url = track.get("url", "https://www.last.fm")
            plays = track.get("playcount", "0")
            lines.append(f"`{index:02d}` **[{name}]({url})** ({self._plays_text(plays)})")
        await self._send_list(ctx, f"{username}'s top tracks for {artist_query}", lines)

    @lastfm.command(name="toptenalbums")
    async def lastfm_toptenalbums(
        self,
        ctx: Context,
        *,
        artist: str,
    ) -> None:
        """
        View your top ten albums for an artist
        """
        member, artist_query = await self._consume_optional_plays_query_target(ctx, artist)
        if artist_query is None:
            return
        if not artist_query:
            await ctx.warn("Provide an **artist** name.")
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        data = await self._request(
            {"method": "user.getTopAlbums", "user": username, "limit": "100"}
        )
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        albums = data.get("topalbums", {}).get("album", [])
        filtered = [
            album
            for album in albums
            if (album.get("artist", {}).get("name") or "").lower() == artist_query.lower()
        ]
        if not filtered:
            await ctx.info(f"{ctx.author.mention}: No **albums** were found for `{artist_query}`.")
            return
        lines = []
        for index, album in enumerate(filtered[:10], start=1):
            name = album.get("name", "Unknown album")
            url = album.get("url", "https://www.last.fm")
            plays = album.get("playcount", "0")
            lines.append(f"`{index:02d}` **[{name}]({url})** ({self._plays_text(plays)})")
        await self._send_list(ctx, f"{username}'s top albums for {artist_query}", lines)

    @lastfm.command(name="favorites", aliases=["loved", "lovedtracks", "lt"])
    async def lastfm_favorites(self, ctx: Context, *, query: str | None = None) -> None:
        """
        View yours or a member's liked tracks
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        data = await self._request({"method": "user.getLovedTracks", "user": username, "limit": "50"})
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        tracks = data.get("lovedtracks", {}).get("track", [])
        if not tracks:
            await ctx.info(f"{ctx.author.mention}: No **liked tracks** were found.")
            return
        lines = []
        for index, track in enumerate(tracks[:50], start=1):
            name = track.get("name", "Unknown track")
            artist = track.get("artist", {}).get("name") or "Unknown artist"
            url = track.get("url", "https://www.last.fm")
            lines.append(f"`{index:02d}` **[{name}]({url})** - {artist}")
        await self._send_list(ctx, f"{username}'s liked tracks", lines)

    @lastfm.command(name="artist", aliases=["a", "ai", "artistinfo"])
    async def lastfm_artist(
        self,
        ctx: Context,
        *,
        artist: str | None = None,
    ) -> None:
        """
        View artist information for the current artist or a search query
        """
        member, artist_query = await self._consume_optional_plays_query_target(ctx, (artist or "").strip())
        if artist_query is None:
            return
        artist_kw = artist_query if artist_query else None
        username = await self._username_for(ctx, member)
        if not username:
            return
        artist_name = await self._resolve_artist_name(username, artist_kw)
        if not artist_name:
            await ctx.info(f"{ctx.author.mention}: No **artist** could be resolved right now.")
            return
        if artist_kw and artist_kw.strip():
            match = await self._artist_search(artist_name)
            if match:
                matched_name = self._text_value(match.get("name"))
                if matched_name:
                    artist_name = matched_name.strip()
        data = await self._request(
            {"method": "artist.getInfo", "artist": artist_name, "username": username, "autocorrect": "1"}
        )
        if not data or "artist" not in data:
            await ctx.warn("No **results** were found for that artist.")
            return
        artist_data = data["artist"]
        stats = artist_data.get("stats", {})
        tags = artist_data.get("tags", {}).get("tag", [])
        if isinstance(tags, dict):
            tags = [tags]
        tag_names = [tag.get("name") for tag in tags if tag.get("name")]
        similar = artist_data.get("similar", {}).get("artist", [])
        if isinstance(similar, dict):
            similar = [similar]
        similar_names = [item.get("name") for item in similar if item.get("name")]
        summary = self._truncate_text(
            re.sub(r"<[^>]+>", "", artist_data.get("bio", {}).get("summary", "")).replace("Read more on Last.fm", "").strip(),
            limit=260,
        )
        target = member or ctx.author
        color = await self._resolve_color(target.id)
        embed = discord.Embed(
            title=artist_data.get("name", artist_name),
            url=artist_data.get("url") or f"https://www.last.fm/music/{quote_plus(artist_name)}",
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"**Your plays**: {self._plays_text(stats.get('userplaycount'))}",
                    f"**Listeners**: {self._listeners_text(stats.get('listeners'))}",
                    f"**Global plays**: {self._plays_text(stats.get('playcount'))}",
                )
            ),
            color=color,
        )
        if tag_names:
            embed.add_field(
                name="Genres",
                value=", ".join(tag_names[:8]),
                inline=False,
            )
        if similar_names:
            embed.add_field(
                name="Similar Artists",
                value=", ".join(similar_names[:6]),
                inline=False,
            )
        if summary:
            embed.add_field(name="About", value=summary, inline=False)
        image = artist_data.get("image", [])
        if image:
            embed.set_thumbnail(url=image[-1].get("#text") or image[0].get("#text"))
        self._set_lastfm_user_author(embed, target)
        self._set_lastfm_footer(embed, self._meta_line("Artist profile", username))
        view = self._link_view((self._lastfm_emoji(), "Artist", self._clean_query_url(artist_data.get("url"))))
        await ctx.send(embed=embed, view=view)

    @lastfm.command(name="album", aliases=["ab"])
    async def lastfm_album(
        self,
        ctx: Context,
        *,
        album: str | None = None,
    ) -> None:
        """
        View album information for the current album or a search query
        """
        member, album_query = await self._consume_optional_plays_query_target(ctx, (album or "").strip())
        if album_query is None:
            return
        album_kw = album_query if album_query else None
        username = await self._username_for(ctx, member)
        if not username:
            return
        resolved = await self._resolve_album_identity(username, album_kw)
        if not resolved:
            await ctx.info(f"{ctx.author.mention}: No **album** could be resolved right now.")
            return
        artist_name, album_name = resolved
        data = await self._request(
            {
                "method": "album.getInfo",
                "artist": artist_name,
                "album": album_name,
                "username": username,
                "autocorrect": "1",
            }
        )
        if not data or "album" not in data:
            await ctx.warn("No **results** were found for that album.")
            return
        album_data = data["album"]
        tracks = album_data.get("tracks", {}).get("track", [])
        if isinstance(tracks, dict):
            tracks = [tracks]
        tags = album_data.get("tags", {}).get("tag", [])
        if isinstance(tags, dict):
            tags = [tags]
        summary = self._truncate_text(
            re.sub(r"<[^>]+>", "", album_data.get("wiki", {}).get("summary", "")).replace("Read more on Last.fm", "").strip(),
            limit=260,
        )
        target = member or ctx.author
        color = await self._resolve_color(target.id)
        track_count = self._format_number(len(tracks)) if tracks else "n/a"
        embed = discord.Embed(
            title=album_data.get("name", album_name),
            url=album_data.get("url") or f"https://www.last.fm/music/{quote_plus(artist_name)}/{quote_plus(album_name)}",
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"**Artist**: {album_data.get('artist', artist_name)}",
                    f"**Your plays**: {self._plays_text(album_data.get('userplaycount'))}",
                    f"**Listeners**: {self._listeners_text(album_data.get('listeners'))}",
                    f"**Global plays**: {self._plays_text(album_data.get('playcount'))}",
                )
            ),
            color=color,
        )
        tag_names = [tag.get("name") for tag in tags if tag.get("name")]
        embed.add_field(
            name="Details",
            value=self._quote_block(
                f"**Track count**: {track_count}",
                f"**Top tags**: {', '.join(tag_names[:5]) if tag_names else 'n/a'}",
            ),
            inline=False,
        )
        if tag_names:
            embed.add_field(name="Genres", value=", ".join(tag_names[:8]), inline=False)
        if summary:
            embed.add_field(name="About", value=summary, inline=False)
        artwork = await self._get_album_artwork((member or ctx.author).id, artist_name, album_name)
        if artwork:
            embed.set_thumbnail(url=artwork)
        else:
            images = album_data.get("image", [])
            if images:
                embed.set_thumbnail(url=images[-1].get("#text") or images[0].get("#text"))
        self._set_lastfm_user_author(embed, target)
        self._set_lastfm_footer(embed, self._meta_line("Album profile", username))
        view = self._link_view((self._lastfm_emoji(), "Album", self._clean_query_url(album_data.get("url"))))
        await ctx.send(embed=embed, view=view)

    @lastfm.command(name="track", aliases=["tr", "ti", "ts", "trackinfo"])
    async def lastfm_track(
        self,
        ctx: Context,
        *,
        track: str | None = None,
    ) -> None:
        """
        View track information for the current track or a search query
        """
        member, track_query = await self._consume_optional_plays_query_target(ctx, (track or "").strip())
        if track_query is None:
            return
        track_kw = track_query if track_query else None
        username = await self._username_for(ctx, member)
        if not username:
            return
        resolved = await self._resolve_track_identity(username, track_kw)
        if not resolved:
            await ctx.info(f"{ctx.author.mention}: No **track** could be resolved right now.")
            return
        artist_name, track_name = resolved
        data = await self._request(
            {
                "method": "track.getInfo",
                "artist": artist_name,
                "track": track_name,
                "username": username,
                "autocorrect": "1",
            }
        )
        if not data or "track" not in data:
            await ctx.warn("No **results** were found for that track.")
            return
        track_data = data["track"]
        album_data = track_data.get("album", {})
        top_tags = track_data.get("toptags", {}).get("tag", [])
        if isinstance(top_tags, dict):
            top_tags = [top_tags]
        duration_value = self._format_duration(self._number_value(track_data.get("duration")))
        target = member or ctx.author
        color = await self._resolve_color(target.id)
        embed = discord.Embed(
            title=track_data.get("name", track_name),
            url=track_data.get("url") or f"https://www.last.fm/music/{quote_plus(artist_name)}/_/{quote_plus(track_name)}",
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"**Artist**: {track_data.get('artist', {}).get('name') or artist_name}",
                    f"**Album**: {album_data.get('title') or 'Unknown album'}",
                    f"**Your plays**: {self._plays_text(track_data.get('userplaycount'))}",
                    f"**Listeners**: {self._listeners_text(track_data.get('listeners'))}",
                    f"**Global plays**: {self._plays_text(track_data.get('playcount'))}",
                )
            ),
            color=color,
        )
        tag_names = [tag.get("name") for tag in top_tags if tag.get("name")]
        embed.add_field(
            name="Details",
            value=self._quote_block(
                f"**Duration**: {duration_value}",
                f"**Top tags**: {', '.join(tag_names[:5]) if tag_names else 'n/a'}",
            ),
            inline=False,
        )
        if tag_names:
            embed.add_field(name="Genres", value=", ".join(tag_names[:8]), inline=False)
        images = album_data.get("image", [])
        if images:
            embed.set_thumbnail(url=images[-1].get("#text") or images[0].get("#text"))
        self._set_lastfm_user_author(embed, target)
        self._set_lastfm_footer(embed, self._meta_line("Track profile", username))
        spotify = await self._spotify_track_lookup(artist_name, track_name)
        view = self._link_view(
            (self._lastfm_emoji(), "Track", self._clean_query_url(track_data.get("url"))),
            ("🟢", "Spotify", self._clean_query_url(spotify.get("spotify_url"))),
        )
        await ctx.send(embed=embed, view=view)

    @lastfm.command(name="cover", aliases=["abc", "abco", "co", "albumcover"])
    async def lastfm_cover(
        self,
        ctx: Context,
        *,
        album: str | None = None,
    ) -> None:
        """
        View the album cover for the current album or a search query
        """
        member, album_query = await self._consume_optional_plays_query_target(ctx, (album or "").strip())
        if album_query is None:
            return
        album_kw = album_query if album_query else None
        username = await self._username_for(ctx, member)
        if not username:
            return
        resolved = await self._resolve_album_identity(username, album_kw)
        if not resolved:
            await ctx.info(f"{ctx.author.mention}: No **album** could be resolved right now.")
            return
        artist_name, album_name = resolved
        data = await self._request(
            {
                "method": "album.getInfo",
                "artist": artist_name,
                "album": album_name,
                "username": username,
                "autocorrect": "1",
            }
        )
        if not data or "album" not in data:
            await ctx.warn("No **results** were found for that album.")
            return
        album_data = data["album"]
        artwork = await self._get_album_artwork((member or ctx.author).id, artist_name, album_name)
        if not artwork:
            images = album_data.get("image", [])
            if images:
                artwork = images[-1].get("#text") or images[0].get("#text")
        if not artwork:
            await ctx.warn("No **cover artwork** was found for that album.")
            return
        target = member or ctx.author
        color = await self._resolve_color(target.id)
        embed = discord.Embed(
            title=f"{album_data.get('name', album_name)} cover",
            url=album_data.get("url") or f"https://www.last.fm/music/{quote_plus(artist_name)}/{quote_plus(album_name)}",
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"**Artist**: {album_data.get('artist', artist_name)}",
                    f"**Artwork source**: {'Custom override' if await self._get_album_artwork((member or ctx.author).id, artist_name, album_name) else 'Last.fm'}",
                )
            ),
            color=color,
        )
        embed.set_image(url=artwork)
        self._set_lastfm_user_author(embed, target)
        self._set_lastfm_footer(embed, self._meta_line("Album artwork", username))
        view = self._link_view((self._lastfm_emoji(), "Album", self._clean_query_url(album_data.get("url"))))
        await ctx.send(embed=embed, view=view)

    @lastfm.command(name="count", aliases=["scrobbles"])
    async def lastfm_count(self, ctx: Context, *, query: str | None = None) -> None:
        """
        View your total Last.fm scrobbles
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        target = member or ctx.author
        username = await self._username_for(ctx, target)
        if not username:
            return
        data = await self._lastfm_user_info(username)
        if not data or "user" not in data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        total_scrobbles = self._format_number(data["user"].get("playcount", "0"))
        today_scrobbles = self._format_number(await self._today_scrobble_count(username))
        await ctx.send(
            f"**{target.display_name}** has **{total_scrobbles}** scrobbles (**{today_scrobbles}** today)"
        )

    @lastfm.command(name="streak")
    async def lastfm_streak(self, ctx: Context, *, query: str | None = None) -> None:
        """
        View your current listening streak
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        data = await self._request({"method": "user.getRecentTracks", "user": username, "limit": "200"})
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        tracks = data.get("recenttracks", {}).get("track", [])
        if not tracks:
            await ctx.info(f"{ctx.author.mention}: No **scrobbles** were found.")
            return
        dates = []
        last_ts = None
        for track in tracks:
            ts = track.get("date", {}).get("uts")
            if ts:
                ts_int = int(ts)
                dates.append(datetime.fromtimestamp(ts_int, tz=timezone.utc).date())
                if last_ts is None:
                    last_ts = ts_int
        if not dates:
            await ctx.info(f"{ctx.author.mention}: No **scrobbles** were found.")
            return
        dates_sorted = sorted(set(dates), reverse=True)
        streak = 1
        for index in range(1, len(dates_sorted)):
            if (dates_sorted[index - 1] - dates_sorted[index]).days == 1:
                streak += 1
            else:
                break
        target = member or ctx.author
        color = await self._resolve_color(target.id)
        embed = discord.Embed(
            title=f"{username}'s listening streak",
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"**Current streak**: {self._format_number(streak)} day(s)",
                    f"**Last scrobble**: <t:{last_ts}:R>" if last_ts else None,
                )
            ),
            color=color,
        )
        self._set_lastfm_user_author(embed, target)
        self._set_lastfm_footer(embed, self._meta_line("Recent listening", username))
        await ctx.send(embed=embed)

    @lastfm.command(name="crown")
    @commands.guild_only()
    async def lastfm_crown(self, ctx: Context, *, artist: str | None = None) -> None:
        """
        View current crown holder and recent crown history for an artist
        """
        if not ctx.guild or not getattr(self.bot, "db", None):
            await ctx.warn("Run this command in a **server** to view crowns.")
            return
        if not artist:
            username = await self._username_for(ctx, None)
            if not username:
                return
            track = await self._nowplaying(username)
            if not track:
                await ctx.info(f"{ctx.author.mention}: No **track** is playing right now.")
                return
            artist = track.get("artist", {}).get("#text") or ""
            if not artist:
                await ctx.warn("Unable to resolve the **current artist**.")
                return

        crown = await self._get_crown(ctx.guild.id, artist)
        if not crown:
            await ctx.info(f"{ctx.author.mention}: No **crown** was found for `{artist}`.")
            return

        linked_rows = await self.bot.db.get_lastfm_users()
        linked_by_id = {int(row["user_id"]): row.get("lastfm_username", "") for row in linked_rows}
        owner_id = int(crown["user_id"])
        owner_member = ctx.guild.get_member(owner_id)
        owner_display = owner_member.mention if owner_member else f"**{linked_by_id.get(owner_id) or owner_id}**"
        plays = self._plays_text(crown.get("playcount"))
        claimed_at = crown.get("claimed_at")
        claimed_text = "n/a"
        if claimed_at:
            claimed_text = f"<t:{int(claimed_at.timestamp())}:R>"

        color = await self._resolve_color(owner_id if owner_member else ctx.author.id)
        embed = discord.Embed(
            title=f"👑 Crown for {crown.get('artist_name', artist)}",
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"**Current holder**: {owner_display}",
                    f"**Plays**: {plays}",
                    f"**Claimed**: {claimed_text}",
                )
            ),
            color=color,
            url=f"https://www.last.fm/music/{quote_plus(crown.get('artist_name', artist))}",
        )
        history_rows = await self._list_crown_history(ctx.guild.id, crown.get("artist_name", artist), limit=10)
        steals = [row for row in history_rows if row.get("previous_user_id") is not None]
        if steals:
            lines = []
            for row in steals[:10]:
                prev_id = int(row["previous_user_id"])
                new_id = int(row["new_user_id"])
                prev_member = ctx.guild.get_member(prev_id)
                new_member = ctx.guild.get_member(new_id)
                prev_name = prev_member.mention if prev_member else f"**{linked_by_id.get(prev_id) or prev_id}**"
                new_name = new_member.mention if new_member else f"**{linked_by_id.get(new_id) or new_id}**"
                changed_at = row.get("changed_at")
                changed_text = "now"
                if changed_at:
                    changed_text = f"<t:{int(changed_at.timestamp())}:R>"
                lines.append(f"> {new_name} stole from {prev_name} ({changed_text})")
            embed.add_field(name="Recent steals", value="\n".join(lines), inline=False)
        self._set_lastfm_guild_author(embed, ctx.guild, ctx.author)
        self._set_lastfm_footer(embed, "Run whoknows on this artist to refresh crown ownership")
        await ctx.send(embed=embed)

    @lastfm.command(name="crowns")
    async def lastfm_crowns(self, ctx: Context, *, query: str | None = None) -> None:
        """
        View a list of your crowns
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        if not ctx.guild or not getattr(self.bot, "db", None):
            await ctx.warn("Run this command in a **server** to view crowns.")
            return
        target = member or ctx.author
        crowns = await self._list_user_crowns(ctx.guild.id, target.id)
        if not crowns:
            await self._seed_crowns_from_top_artists(ctx.guild)
            crowns = await self._list_user_crowns(ctx.guild.id, target.id)
        if not crowns:
            await ctx.info(f"{ctx.author.mention}: No **crowns** were found.")
            return
        lines = []
        for index, crown in enumerate(crowns, start=1):
            artist_name = crown.get("artist_name", "Unknown artist")
            artist_url = f"https://www.last.fm/music/{quote_plus(artist_name)}"
            plays = self._plays_text(crown.get("playcount", 0))
            claimed_at = crown.get("claimed_at")
            claimed_text = ""
            if claimed_at:
                claimed_unix = int(claimed_at.timestamp())
                claimed_text = f" - Claimed <t:{claimed_unix}:R>"
            lines.append(f"`{index:02d}` **[{artist_name}]({artist_url})** - `{plays}`{claimed_text}")
        await self._send_list(ctx, f"{target.display_name}'s crowns", lines)

    @lastfm.command(name="mostcrowns")
    async def lastfm_mostcrowns(self, ctx: Context) -> None:
        """
        View a list of members with the most crowns
        """
        if not ctx.guild or not getattr(self.bot, "db", None):
            await ctx.warn("Run this command in a **server** to view crowns.")
            return
        crowns = await self._list_crowns(ctx.guild.id)
        if not crowns:
            await self._seed_crowns_from_top_artists(ctx.guild)
            crowns = await self._list_crowns(ctx.guild.id)
        if not crowns:
            await ctx.info(f"{ctx.author.mention}: No **crowns** were found.")
            return
        counts: dict[int, int] = {}
        for crown in crowns:
            owner_id = int(crown["user_id"])
            counts[owner_id] = counts.get(owner_id, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        lines = []
        for index, (user_id, count) in enumerate(ranked, start=1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"Unknown user#{user_id}"
            crown_word = "crown" if count == 1 else "crowns"
            lines.append(f"`{index:02d}` **{name}** - `{self._format_number(count)} {crown_word}`")
        await self._send_list(ctx, "Most crowns", lines)

    @lastfm.command(name="score")
    async def lastfm_score(self, ctx: Context, *, query: str | None = None) -> None:
        """
        View your Last.fm score and statistics
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        data = await self._lastfm_user_info(username)
        if not data or "user" not in data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        user = data["user"]
        embed = discord.Embed(
            title=f"{username}'s Last.fm score",
            description=(
                f"**Scrobbles**: {self._format_number(user.get('playcount', '0'))}\n"
                f"**Artists**: {self._format_number(user.get('artist_count', '0'))}\n"
                f"**Albums**: {self._format_number(user.get('album_count', '0'))}\n"
                f"**Tracks**: {self._format_number(user.get('track_count', '0'))}"
            ),
            color=self._info_color(),
        )
        self._set_lastfm_footer(embed, f"{ctx.author.display_name} - Last.fm")
        await ctx.send(embed=embed)

    @lastfm.command(name="plays", aliases=["artistplays", "ap"])
    async def lastfm_plays(self, ctx: Context, *, artist: str) -> None:
        """
        Check how many plays you have for an artist.

        Prefix with a mention or user ID to query someone else's plays.
        """
        member, artist_query = await self._consume_optional_plays_query_target(ctx, artist)
        if artist_query is None:
            return
        if not artist_query:
            await ctx.warn("Provide an **artist** to look up.")
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        artist_name = await self._resolve_artist_name(username, artist_query)
        if not artist_name:
            await ctx.warn("No **results** were found for that artist.")
            return
        data = await self._request(
            {"method": "artist.getInfo", "artist": artist_name, "username": username, "autocorrect": "1"}
        )
        if not data or "artist" not in data:
            await ctx.warn("No **results** were found for that artist.")
            return
        count = data["artist"].get("stats", {}).get("userplaycount", "0")
        display_name = data["artist"].get("name", artist_name)
        line = self._lastfm_plays_line(
            ctx,
            member or ctx.author,
            count=count,
            name=display_name,
            url=self._artist_url(display_name),
        )
        await ctx.lastfm(line)

    @lastfm.command(name="playstrack", aliases=["trackplays", "tp", "trackplay", "tplays", "trackp"])
    async def lastfm_playstrack(self, ctx: Context, *, track: str) -> None:
        """
        Check how many plays you have for a specific track.

        Prefix with a mention or user ID to query someone else's plays.
        """
        member, track_query = await self._consume_optional_plays_query_target(ctx, track)
        if track_query is None:
            return
        if not track_query:
            await ctx.warn("Provide a **track** to look up.")
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        resolved = await self._resolve_track_identity(username, track_query)
        if not resolved:
            await ctx.warn("No **results** were found for that track.")
            return
        artist, title = resolved
        data = await self._request(
            {"method": "track.getInfo", "artist": artist, "track": title, "username": username, "autocorrect": "1"}
        )
        if not data or "track" not in data:
            await ctx.warn("No **results** were found for that track.")
            return
        track_block = data["track"]
        count = track_block.get("userplaycount", "0")
        track_name = track_block.get("name", title)
        artist_raw = track_block.get("artist")
        if isinstance(artist_raw, dict):
            link_artist = artist_raw.get("name") or artist
        else:
            link_artist = str(artist_raw).strip() if artist_raw else artist
        line = self._lastfm_plays_line(
            ctx,
            member or ctx.author,
            count=count,
            name=track_name,
            url=self._track_url(link_artist, track_name),
        )
        await ctx.lastfm(line)

    @lastfm.command(name="playsalbum", aliases=["albumplays", "abp", "albumplay", "abplays", "albump"])
    async def lastfm_playsalbum(self, ctx: Context, *, album: str) -> None:
        """
        Check how many plays you have for an album.

        Prefix with a mention or user ID to query someone else's plays.
        """
        member, album_query = await self._consume_optional_plays_query_target(ctx, album)
        if album_query is None:
            return
        if not album_query:
            await ctx.warn("Provide an **album** to look up.")
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        resolved = await self._resolve_album_identity(username, album_query)
        if not resolved:
            await ctx.warn("No **results** were found for that album.")
            return
        artist, title = resolved
        data = await self._request(
            {"method": "album.getInfo", "artist": artist, "album": title, "username": username, "autocorrect": "1"}
        )
        if not data or "album" not in data:
            await ctx.warn("No **results** were found for that album.")
            return
        album_block = data["album"]
        count = album_block.get("userplaycount", "0")
        album_name = album_block.get("name", title)
        artist_raw = album_block.get("artist")
        if isinstance(artist_raw, dict):
            link_artist = artist_raw.get("name") or artist
        else:
            link_artist = str(artist_raw).strip() if artist_raw else artist
        line = self._lastfm_plays_line(
            ctx,
            member or ctx.author,
            count=count,
            name=album_name,
            url=self._album_url(link_artist, album_name),
        )
        await ctx.lastfm(line)

    @lastfm.command(name="playsall")
    async def lastfm_playsall(self, ctx: Context, *, album: str) -> None:
        """
        Check how many plays you have for every song on an album.

        Prefix with a mention or user ID to query someone else's plays.
        """
        member, album_query = await self._consume_optional_plays_query_target(ctx, album)
        if album_query is None:
            return
        if not album_query:
            await ctx.warn("Provide an **album** to look up.")
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        resolved = await self._resolve_album_identity(username, album_query)
        if not resolved:
            await ctx.warn("No **results** were found for that album.")
            return
        artist, title = resolved
        data = await self._request(
            {"method": "album.getInfo", "artist": artist, "album": title, "username": username, "autocorrect": "1"}
        )
        if not data or "album" not in data:
            await ctx.warn("No **results** were found for that album.")
            return
        tracks = data["album"].get("tracks", {}).get("track", [])
        if not tracks:
            await ctx.warn("No **tracks** were found for that album.")
            return
        lines = []
        for index, item in enumerate(tracks[:10], start=1):
            name = item.get("name", "Unknown track")
            info = await self._request(
                {"method": "track.getInfo", "artist": artist, "track": name, "username": username}
            )
            plays = "0"
            if info and "track" in info:
                plays = info["track"].get("userplaycount", "0")
            lines.append(
                f"`{index:02d}` **[{name}](https://www.last.fm/music/{quote_plus(artist)}/_/{quote_plus(name)})** ({self._plays_text(plays)})"
            )
        await self._send_list(ctx, f"{username}'s track plays for album {title}", lines, footer_prefix="Tracklist from Last.fm")

    @lastfm.command(name="love", aliases=["l", "heart", "favorite", "affection", "appreciation"])
    async def lastfm_love(self, ctx: Context, *, track: str | None = None) -> None:
        """
        Love the current track or a searched track on Last.fm
        """
        username = await self._username_for(ctx, None)
        if not username:
            return
        session_key = await self._session_key_for(ctx.author.id)
        if not session_key:
            await ctx.warn(
                f"You need to reconnect your **Last.fm** account first. "
                f"You can link it with `{ctx.clean_prefix}lastfm login`."
            )
            return
        resolved = await self._resolve_track_identity(username, track)
        if not resolved:
            await ctx.warn("No **results** were found for that track.")
            return
        artist_name, track_name = resolved
        artist_name, track_name = await self._canonical_track_names_for_user(
            username, artist_name, track_name
        )
        data = await self._signed_post_request(
            {
                "method": "track.love",
                "artist": artist_name,
                "track": track_name,
                "sk": session_key,
            }
        )
        await self._respond_lastfm_track_write(
            ctx, data, artist_name, track_name, past_label="loved", username=username
        )

    @lastfm.command(name="unlove", aliases=["ul", "unheart", "hate"])
    async def lastfm_unlove(self, ctx: Context, *, track: str | None = None) -> None:
        """
        Remove the current track or a searched track from your Last.fm loved tracks
        """
        username = await self._username_for(ctx, None)
        if not username:
            return
        session_key = await self._session_key_for(ctx.author.id)
        if not session_key:
            await ctx.warn(
                f"You need to reconnect your **Last.fm** account first. "
                f"You can link it with `{ctx.clean_prefix}lastfm login`."
            )
            return
        resolved = await self._resolve_track_identity(username, track)
        if not resolved:
            await ctx.warn("No **results** were found for that track.")
            return
        artist_name, track_name = resolved
        artist_name, track_name = await self._canonical_track_names_for_user(
            username, artist_name, track_name
        )
        data = await self._signed_post_request(
            {
                "method": "track.unlove",
                "artist": artist_name,
                "track": track_name,
                "sk": session_key,
            }
        )
        await self._respond_lastfm_track_write(
            ctx, data, artist_name, track_name, past_label="unloved", username=username
        )

    @lastfm.command(name="scrobble", aliases=["sb"])
    async def lastfm_scrobble(self, ctx: Context, *, track: str | None = None) -> None:
        """
        Scrobble the current track or a searched track on Last.fm
        """
        username = await self._username_for(ctx, None)
        if not username:
            return
        session_key = await self._session_key_for(ctx.author.id)
        if not session_key:
            await ctx.warn(
                f"You need to reconnect your **Last.fm** account first. "
                f"You can link it with `{ctx.clean_prefix}lastfm login`."
            )
            return
        resolved = await self._resolve_track_identity(username, track)
        if not resolved:
            await ctx.warn("No **results** were found for that track.")
            return
        artist_name, track_name = resolved
        artist_name, track_name = await self._canonical_track_names_for_user(
            username, artist_name, track_name
        )
        data = await self._signed_post_request(
            {
                "method": "track.scrobble",
                "artist": artist_name,
                "track": track_name,
                "timestamp": str(int(time.time()) - 1),
                "sk": session_key,
            }
        )
        await self._respond_lastfm_track_write(
            ctx, data, artist_name, track_name, past_label="scrobbled", username=username
        )

    @lastfm.command(name="taste")
    async def lastfm_taste(
        self,
        ctx: Context,
        *,
        query: str | None = None,
    ) -> None:
        """
        Compare your music taste between you and someone else
        """
        member, period_key, ok = await self._member_and_optional_period_tail(ctx, query or "")
        if not ok:
            return
        target = member or ctx.author
        user1 = await self._username_for(ctx, ctx.author)
        if not user1:
            return
        user2 = await self._username_for(ctx, target)
        if not user2:
            return
        if user1.strip().lower() == user2.strip().lower():
            await ctx.warn("Pick someone else, you **can't** compare taste with **your own** Last.fm.")
            return
        period_param = self._period_param(period_key)
        if not period_param:
            await ctx.warn("Invalid **period**. Use: overall, 7d, 1m, 3m, 6m, 12m.")
            return
        min_artists = 3
        if period_param == "overall":
            data = await self._request(
                {
                    "method": "tasteometer.compare",
                    "type1": "user",
                    "type2": "user",
                    "value1": user1,
                    "value2": user2,
                    "limit": "5",
                }
            )
        else:
            rows1 = await self._top_artists(user1, limit=50, period=period_param)
            rows2 = await self._top_artists(user2, limit=50, period=period_param)
            names1 = self._taste_top_artist_names(rows1)
            names2 = self._taste_top_artist_names(rows2)
            if len(names1) < min_artists or len(names2) < min_artists:
                await ctx.warn(
                    f"Both users need at least **{min_artists}** top artists in that "
                    "**period** for a taste comparison (Last.fm)."
                )
                return
            data = await self._request(
                {
                    "method": "tasteometer.compare",
                    "type1": "artists",
                    "type2": "artists",
                    "value1": ",".join(names1),
                    "value2": ",".join(names2),
                    "limit": "5",
                }
            )
        err = self._api_error_message(data)
        if err:
            await ctx.warn(self._truncate_text(err, 500))
            return
        if not data or "comparison" not in data:
            await ctx.warn("Last.fm did not return a **comparison**. Try again later.")
            return
        cmp_block = data["comparison"]
        score = cmp_block.get("result", {}).get("score", "0")
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            score_f = 0.0
        names = self._taste_shared_artist_names(cmp_block)
        period_note = PERIOD_LABELS.get(period_param, period_param)
        description = f"**Compatibility** ({period_note}): {score_f * 100:.2f}%"
        if names:
            description += "\n**Shared artists**: " + ", ".join(names[:5])
        embed = discord.Embed(
            title=f"{ctx.author.display_name} vs {target.display_name}",
            description=description,
            color=self._info_color(),
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @lastfm.command(name="milestone")
    async def lastfm_milestone(self, ctx: Context, number: int) -> None:
        """
        See what track your given number scrobble was.
        """
        if number <= 0:
            await ctx.warn("Milestone must be a **positive** number.")
            return
        username = await self._username_for(ctx, None)
        if not username:
            return
        data = await self._request(
            {"method": "user.getRecentTracks", "user": username, "limit": "200", "page": "1"}
        )
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        total = int(data.get("recenttracks", {}).get("@attr", {}).get("total", 0))
        if total <= 0 or number > total:
            await ctx.warn(f"That milestone is beyond your **{self._format_number(total)}** scrobbles.")
            return
        limit = 200
        page = max(1, (number + limit - 1) // limit)
        data = await self._request(
            {"method": "user.getRecentTracks", "user": username, "limit": str(limit), "page": str(page)}
        )
        if not data:
            raise RuntimeError("internal lastfm upstream unavailable")
            return
        tracks = data.get("recenttracks", {}).get("track", [])
        index = (number - 1) % limit
        track = tracks[index] if index < len(tracks) else None
        if not track:
            await ctx.warn("No **track** could be found for that milestone.")
            return
        name = track.get("name", "Unknown track")
        artist = track.get("artist", {}).get("#text") or "Unknown artist"
        url = track.get("url", "https://www.last.fm")
        embed = discord.Embed(
            title=f"Milestone #{number}",
            description=f"**{name}** - {artist}",
            color=self._info_color(),
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        image = track.get("image", [])
        if image:
            embed.set_thumbnail(url=image[-1].get("#text") or image[0].get("#text"))
        view = self._link_view((self._lastfm_emoji(), "Track", url))
        await ctx.send(embed=embed, view=view)

    @lastfm.group(name="hide", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def lastfm_hide(self, ctx: Context, member: discord.User) -> None:
        """
        Hide users from appearing on whoknows commands
        """
        if not getattr(self.bot, "db", None):
            return
        hidden_ids = set(await self.bot.db.list_lastfm_hidden(ctx.guild.id))
        if member.id in hidden_ids:
            await self.bot.db.remove_lastfm_hidden(ctx.guild.id, member.id)
            await ctx.success(f"Removed {member.mention} from **hidden Last.fm members**.")
            return
        await self.bot.db.set_lastfm_hidden(ctx.guild.id, member.id)
        await ctx.success(f"Hidden {member.mention} from **Last.fm whoknows** results.")

    @lastfm_hide.command(name="list")
    async def lastfm_hide_list(self, ctx: Context) -> None:
        """
        View the list of all hidden members
        """
        if not ctx.guild or not getattr(self.bot, "db", None):
            return
        hidden_ids = await self.bot.db.list_lastfm_hidden(ctx.guild.id)
        if not hidden_ids:
            await ctx.info(f"{ctx.author.mention}: No **hidden members** are set.")
            return
        lines = []
        for index, user_id in enumerate(hidden_ids, start=1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"Unknown user#{user_id}"
            lines.append(f"`{index:02d}` **{name}**")
        await self._send_list(ctx, "Hidden Last.fm members", lines)

    @lastfm.command(name="whoknows", aliases=["w", "wk", "thosewhoknow"])
    @commands.guild_only()
    async def lastfm_whoknows(self, ctx: Context, *, artist: str | None = None) -> None:
        """
        View the top listeners for an artist in a guild
        """
        if not getattr(self.bot, "db", None):
            return
        if not artist:
            username = await self._username_for(ctx, None)
            if not username:
                return
            track = await self._nowplaying(username)
            if not track:
                await ctx.info(f"{ctx.author.mention}: No **track** is playing right now.")
                return
            artist = track.get("artist", {}).get("#text") or ""
            if not artist:
                await ctx.warn("Unable to resolve the **current artist**.")
                return
        candidates = await self._guild_lastfm_candidates(ctx.guild)
        if not candidates:
            await ctx.warn("No linked **Last.fm** users are in this server.")
            return
        rows = await self._fetch_artist_rows(candidates, artist)
        if not rows:
            await ctx.info(f"{ctx.author.mention}: No **plays** were found for `{artist}`.")
            return
        _, top_plays, top_user_id = rows[0]
        min_crown_plays = self._number_value(os.getenv("LASTFM_CROWN_MIN_PLAYS", "5"))
        if top_plays >= max(1, min_crown_plays):
            await self._upsert_crown(ctx.guild.id, artist, top_user_id, top_plays)
        lines = []
        for index, (username, plays, user_id) in enumerate(rows[:50], start=1):
            member = ctx.guild.get_member(int(user_id))
            display = member.display_name if member else username
            lines.append(
                f"`{index:02d}` **[{display}](https://www.last.fm/user/{quote_plus(username)})** - `{self._plays_text(plays)}`"
            )
        await self._send_list(ctx, f"Top listeners for artist {artist}", lines)

    @lastfm.command(name="globalwhoknows", aliases=["gw", "gwk", "globalwk"])
    async def lastfm_globalwhoknows(self, ctx: Context, *, artist: str) -> None:
        """
        View the top listeners for an artist globally
        """
        if not getattr(self.bot, "db", None):
            return
        users = await self.bot.db.get_lastfm_users()
        if not users:
            await ctx.warn("No linked **Last.fm** users were found.")
            return
        semaphore = asyncio.Semaphore(5)

        async def fetch(user: dict) -> tuple[str, int]:
            async with semaphore:
                data = await self._request(
                    {"method": "artist.getInfo", "artist": artist, "username": user["lastfm_username"]}
                )
            plays = 0
            if data and "artist" in data:
                plays = int(data["artist"].get("stats", {}).get("userplaycount", 0))
            return user["lastfm_username"], plays

        results = await asyncio.gather(*(fetch(user) for user in users))
        rows = sorted([r for r in results if r[1] > 0], key=lambda r: r[1], reverse=True)
        if not rows:
            await ctx.info(f"{ctx.author.mention}: No **plays** were found for `{artist}`.")
            return
        lines = []
        for index, (username, plays) in enumerate(rows[:50], start=1):
            lines.append(
                f"`{index:02d}` **[{username}](https://www.last.fm/user/{quote_plus(username)})** - `{self._plays_text(plays)}`"
            )
        await self._send_list(ctx, f"Global top listeners for {artist}", lines)

    @lastfm.command(name="wktrack", aliases=["wt", "wkt", "wktr", "wtr"])
    @commands.guild_only()
    async def lastfm_wktrack(self, ctx: Context, *, track: str | None = None) -> None:
        """
        View the top listeners for a specific song by an artist
        """
        if not getattr(self.bot, "db", None):
            return
        username = await self._username_for(ctx, None)
        if not username:
            return
        resolved = await self._resolve_track_identity(username, track)
        if not resolved:
            await ctx.warn("Unable to resolve the **track**.")
            return
        artist, title = resolved
        candidates = await self._guild_lastfm_candidates(ctx.guild)
        rows = await self._fetch_track_rows(candidates, artist, title)
        if not rows:
            await ctx.info(f"{ctx.author.mention}: No **listeners** were found.")
            return
        lines = [
            f"`{index:02d}` **[{name}](https://www.last.fm/user/{quote_plus(name)})** - `{self._plays_text(plays)}`"
            for index, (name, plays, _) in enumerate(rows[:50], start=1)
        ]
        await self._send_list(ctx, f"Top listeners for track {title}", lines)

    @lastfm.command(name="wkalbum", aliases=["wa", "wka", "wkab", "wab", "wkal"])
    @commands.guild_only()
    async def lastfm_wkalbum(self, ctx: Context, *, album: str | None = None) -> None:
        """
        View the top listeners for an album by an artist
        """
        if not getattr(self.bot, "db", None):
            return
        username = await self._username_for(ctx, None)
        if not username:
            return
        resolved = await self._resolve_album_identity(username, album)
        if not resolved:
            await ctx.warn("Unable to resolve the **album**.")
            return
        artist, title = resolved
        candidates = await self._guild_lastfm_candidates(ctx.guild)
        rows = await self._fetch_album_rows(candidates, artist, title)
        if not rows:
            await ctx.info(f"{ctx.author.mention}: No **listeners** were found.")
            return
        lines = [
            f"`{index:02d}` **[{name}](https://www.last.fm/user/{quote_plus(name)})** - `{self._plays_text(plays)}`"
            for index, (name, plays, _) in enumerate(rows[:50], start=1)
        ]
        await self._send_list(ctx, f"Top listeners for album {title}", lines)

    @lastfm.command(name="globalwktrack")
    async def lastfm_globalwktrack(self, ctx: Context, *, track: str | None = None) -> None:
        """
        View the top listeners for a track globally
        """
        username = await self._username_for(ctx, None)
        if not username:
            return
        resolved = await self._resolve_track_identity(username, track)
        if not resolved:
            await ctx.warn("Unable to resolve the **track**.")
            return
        artist, title = resolved
        if not getattr(self.bot, "db", None):
            return
        rows = await self._fetch_track_rows(await self.bot.db.get_lastfm_users(), artist, title)
        if not rows:
            await ctx.info(f"{ctx.author.mention}: No **listeners** were found.")
            return
        lines = [
            f"`{index:02d}` **[{name}](https://www.last.fm/user/{quote_plus(name)})** - `{self._plays_text(plays)}`"
            for index, (name, plays, _) in enumerate(rows[:50], start=1)
        ]
        await self._send_list(ctx, f"Global top listeners for track {title}", lines)

    @lastfm.command(name="globalwkalbum")
    async def lastfm_globalwkalbum(self, ctx: Context, *, album: str | None = None) -> None:
        """
        View the top listeners for an album globally
        """
        username = await self._username_for(ctx, None)
        if not username:
            return
        resolved = await self._resolve_album_identity(username, album)
        if not resolved:
            await ctx.warn("Unable to resolve the **album**.")
            return
        artist, title = resolved
        if not getattr(self.bot, "db", None):
            return
        rows = await self._fetch_album_rows(await self.bot.db.get_lastfm_users(), artist, title)
        if not rows:
            await ctx.info(f"{ctx.author.mention}: No **listeners** were found.")
            return
        lines = [
            f"`{index:02d}` **[{name}](https://www.last.fm/user/{quote_plus(name)})** - `{self._plays_text(plays)}`"
            for index, (name, plays, _) in enumerate(rows[:50], start=1)
        ]
        await self._send_list(ctx, f"Global top listeners for album {title}", lines)

    @lastfm.command(name="overview")
    async def lastfm_overview(
        self,
        ctx: Context,
        *,
        query: str | None = None,
    ) -> None:
        """
        See a listening overview for yourself or a mentioned member
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        target = member or ctx.author
        if ctx.guild and member and not ctx.guild.get_member(member.id):
            await ctx.warn("That user must be a **member of this server**.")
            return
        username = await self._username_for(ctx, target)
        if not username:
            return
        user_data = await self._lastfm_user_info(username)
        if not user_data or "user" not in user_data:
            raise RuntimeError("internal lastfm upstream unavailable")
        recent_data = await self._request({"method": "user.getRecentTracks", "user": username, "limit": "200"})
        if not recent_data:
            raise RuntimeError("internal lastfm upstream unavailable")
        tracks = recent_data.get("recenttracks", {}).get("track", [])
        if isinstance(tracks, dict):
            tracks = [tracks]
        if not tracks:
            await ctx.info(f"{ctx.author.mention}: No **recent tracks** were found.")
            return
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        today_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_cutoff = int(today_start.timestamp())
        week_cutoff = now_ts - (7 * 24 * 60 * 60)

        today_scrobbles = 0
        week_scrobbles = 0
        unique_artists: set[str] = set()
        unique_albums: set[tuple[str, str]] = set()
        unique_tracks: set[tuple[str, str]] = set()
        artist_counts: dict[str, int] = {}
        dates: list[datetime.date] = []
        last_ts = None

        for track in tracks:
            artist_name = (track.get("artist", {}).get("#text") or "").strip()
            track_name = (track.get("name") or "").strip()
            album_name = (track.get("album", {}).get("#text") or "").strip()
            ts_raw = track.get("date", {}).get("uts")
            ts_value = self._number_value(ts_raw) if ts_raw else 0
            if ts_value > 0:
                if last_ts is None:
                    last_ts = ts_value
                if ts_value >= today_cutoff:
                    today_scrobbles += 1
                if ts_value >= week_cutoff:
                    week_scrobbles += 1
                dates.append(datetime.fromtimestamp(ts_value, tz=timezone.utc).date())
            if artist_name:
                unique_artists.add(artist_name.lower())
                artist_counts[artist_name] = artist_counts.get(artist_name, 0) + 1
            if artist_name and album_name:
                unique_albums.add((artist_name.lower(), album_name.lower()))
            if artist_name and track_name:
                unique_tracks.add((artist_name.lower(), track_name.lower()))

        streak = 0
        if dates:
            dates_sorted = sorted(set(dates), reverse=True)
            streak = 1
            for index in range(1, len(dates_sorted)):
                if (dates_sorted[index - 1] - dates_sorted[index]).days == 1:
                    streak += 1
                else:
                    break

        favorite_artist = None
        favorite_artist_plays = 0
        if artist_counts:
            favorite_artist, favorite_artist_plays = max(
                artist_counts.items(),
                key=lambda item: item[1],
            )

        user = user_data["user"]
        color = await self._resolve_color(target.id)
        total_scrobbles = self._format_number(user.get("playcount"))
        last_line = f"<t:{last_ts}:R>" if last_ts else "n/a"
        sample_count = len(tracks)
        embed = discord.Embed(
            title=f"{target.display_name}'s Last.fm overview",
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"**Total scrobbles**: {total_scrobbles}",
                    f"**Today**: {self._format_number(today_scrobbles)}",
                    f"**Last 7 days**: {self._format_number(week_scrobbles)}",
                    f"**Current streak**: {self._format_number(streak)} day(s)",
                    f"**Last scrobble**: {last_line}",
                )
            ),
            color=color,
            url=self._user_url(username),
        )
        embed.add_field(
            name="Recent Sample",
            value=self._quote_block(
                f"**Tracks**: {self._format_number(sample_count)}",
                f"**Artists**: {self._format_number(len(unique_artists))}",
                f"**Albums**: {self._format_number(len(unique_albums))}",
                f"**Unique tracks**: {self._format_number(len(unique_tracks))}",
            ),
            inline=True,
        )
        embed.add_field(
            name="Patterns",
            value=self._quote_block(
                f"**Top artist**: {favorite_artist or 'n/a'}",
                f"**Plays in sample**: {self._format_number(favorite_artist_plays)}",
            ),
            inline=True,
        )
        self._set_lastfm_user_author(embed, target)
        self._set_lastfm_footer(embed, self._meta_line("Last.fm overview", username))
        view = self._link_view(
            (self._lastfm_emoji(), "Profile", self._user_url(username)),
            ("📚", "Library", f"{self._user_url(username)}/library"),
        )
        await ctx.send(embed=embed, view=view)

    @lastfm.command(name="playing")
    @commands.guild_only()
    async def lastfm_playing(self, ctx: Context) -> None:
        """
        See what song everyone is listening to in a server
        """
        if not getattr(self.bot, "db", None):
            return
        users = await self.bot.db.get_lastfm_users()
        members = await collect_guild_members(ctx.guild)
        guild_members = {member.id: member for member in members}
        linked = [u for u in users if u["user_id"] in guild_members]
        if not linked:
            await ctx.warn("No linked **Last.fm** users are in this server.")
            return
        linked_map = {user["lastfm_username"]: user["user_id"] for user in linked}
        semaphore = asyncio.Semaphore(5)

        async def fetch(user: dict) -> tuple[str, str | None, str | None]:
            async with semaphore:
                track = await self._nowplaying(user["lastfm_username"])
            if not track:
                return user["lastfm_username"], None, None
            name = track.get("name")
            artist = track.get("artist", {}).get("#text")
            return user["lastfm_username"], name, artist

        results = await asyncio.gather(*(fetch(user) for user in linked))
        lines = []
        for index, (username, name, artist) in enumerate(results, start=1):
            if not name or not artist:
                continue
            member = guild_members.get(linked_map.get(username))
            display = member.display_name if member else username
            lines.append(f"`{index:02d}` **{display}** - {name} ({artist})")
        if not lines:
            await ctx.info(f"{ctx.author.mention}: No **listening activity** was found.")
            return
        await self._send_list(ctx, "Now playing in this server", lines)

    @lastfm.command(name="recommendation")
    async def lastfm_recommendation(self, ctx: Context, *, query: str | None = None) -> None:
        """
        Recommends a random artist from your library
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        target = member or ctx.author
        username = await self._username_for(ctx, member)
        if not username:
            return
        pick = await self._indexed_random_artist(target.id)
        if pick:
            name = pick.get("artist_name", "Unknown artist")
            url = f"https://www.last.fm/music/{quote_plus(name)}"
            playcount = self._number_value(pick.get("playcount"))
        else:
            data = await self._request({"method": "user.getTopArtists", "user": username, "limit": "100"})
            if not data:
                raise RuntimeError("internal lastfm upstream unavailable")
            artists = data.get("topartists", {}).get("artist", [])
            if not artists:
                await ctx.info(f"{ctx.author.mention}: No **artists** were found.")
                return
            pick = random.choice(artists)
            name = pick.get("name", "Unknown artist")
            url = pick.get("url", "https://www.last.fm")
            playcount = self._number_value(pick.get("playcount"))
        color = await self._resolve_color(target.id)
        embed = discord.Embed(
            title="Last.fm recommendation",
            description=self._lastfm_embed_description(
                self._quote_block(
                    f"Try **{name}** next.",
                    f"**Your plays**: {self._plays_text(playcount)}" if playcount > 0 else None,
                )
            ),
            color=color,
        )
        self._set_lastfm_user_author(embed, target)
        self._set_lastfm_footer(embed, self._meta_line("Random pick from your library", username))
        view = self._link_view((self._lastfm_emoji(), "Artist", url))
        await ctx.send(embed=embed, view=view)

    @lastfm.group(name="customcommand", invoke_without_command=True)
    @commands.guild_only()
    async def lastfm_customcommand(self, ctx: Context, *, substring: str | None = None) -> None:
        """
        Set your own custom Now Playing command
        """
        if not getattr(self.bot, "db", None):
            return
        current = await self.bot.db.get_lastfm_custom_command(ctx.guild.id, ctx.author.id)
        if not substring:
            if not current:
                await ctx.info(
                    f"{ctx.author.mention}: You do not have a **custom now playing command** yet. "
                    f"Set one with `{ctx.clean_prefix}lastfm customcommand (trigger)`."
                )
                return
            visibility = "public" if current.get("public") else "private"
            await ctx.info(
                f"{ctx.author.mention}: Your **custom now playing command** is currently "
                f"`{current.get('command')}` ({visibility}). Use `off` to clear it."
            )
            return
        if self._is_clear_token(substring):
            await self.bot.db.remove_lastfm_custom_command(ctx.guild.id, ctx.author.id)
            await ctx.success("Cleared your **custom now playing command**.")
            return
        await self.bot.db.set_lastfm_custom_command(ctx.guild.id, ctx.author.id, substring)
        await ctx.success(f"Set your **custom now playing command** to `{substring}`.")

    @lastfm_customcommand.command(name="public")
    @commands.has_guild_permissions(manage_guild=True)
    async def lastfm_customcommand_public(self, ctx: Context, *, substring: str | None = None) -> None:
        """
        Toggle public flag for a custom command
        """
        if not getattr(self.bot, "db", None):
            return
        if not substring:
            current = await self.bot.db.get_lastfm_custom_command(ctx.guild.id, ctx.author.id)
            if not current or not current.get("public"):
                await ctx.info(
                    f"{ctx.author.mention}: You do not have a **public custom now playing command** yet. "
                    f"Set one with `{ctx.clean_prefix}lastfm customcommand public (trigger)`."
                )
                return
            await ctx.info(
                f"{ctx.author.mention}: Your **public custom now playing command** is currently "
                f"`{current.get('command')}`."
            )
            return
        await self.bot.db.set_lastfm_custom_command(ctx.guild.id, ctx.author.id, substring)
        await self.bot.db.set_lastfm_custom_public(ctx.guild.id, ctx.author.id, True)
        await ctx.success(f"Set your **public custom now playing command** to `{substring}`.")

    @lastfm_customcommand.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def lastfm_customcommand_list(self, ctx: Context) -> None:
        """
        View list of custom commands for NP
        """
        if not getattr(self.bot, "db", None):
            return
        rows = await self.bot.db.list_lastfm_custom_commands(ctx.guild.id)
        if not rows:
            await ctx.info(f"{ctx.author.mention}: No **custom commands** are set.")
            return
        lines = []
        for index, row in enumerate(rows, start=1):
            member = ctx.guild.get_member(row["user_id"])
            name = member.display_name if member else f"User {row['user_id']}"
            visibility = "public" if row.get("public") else "private"
            lines.append(f"`{index:02d}` **{name}** - `{row['command']}` • {visibility}")
        await self._send_list(ctx, "Custom Now Playing commands", lines)

    @lastfm_customcommand.command(name="remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def lastfm_customcommand_remove(self, ctx: Context, member: discord.User) -> None:
        """
        Remove a custom command for a member
        """
        if not getattr(self.bot, "db", None):
            return
        await self.bot.db.remove_lastfm_custom_command(ctx.guild.id, member.id)
        await ctx.success(f"Removed {member.mention}'s **custom now playing command**.")

    @lastfm_customcommand.command(name="reset")
    @commands.has_guild_permissions(manage_guild=True)
    async def lastfm_customcommand_reset(self, ctx: Context) -> None:
        """
        Resets all custom commands
        """
        if not getattr(self.bot, "db", None):
            return
        await self.bot.db.reset_lastfm_custom_commands(ctx.guild.id)
        await ctx.success("Reset **all custom now playing commands**.")

    @lastfm_customcommand.command(name="cleanup")
    @commands.has_guild_permissions(administrator=True)
    async def lastfm_customcommand_cleanup(self, ctx: Context) -> None:
        """
        Clean up custom commands from absent members
        """
        if not getattr(self.bot, "db", None):
            return
        rows = await self.bot.db.list_lastfm_custom_commands(ctx.guild.id)
        removed = 0
        for row in rows:
            if not ctx.guild.get_member(row["user_id"]):
                await self.bot.db.remove_lastfm_custom_command(ctx.guild.id, row["user_id"])
                removed += 1
        await ctx.success(f"Successfully **removed** {removed} custom commands.")

    @lastfm_customcommand.group(name="blacklist", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def lastfm_customcommand_blacklist(self, ctx: Context, member: discord.User) -> None:
        """
        Blacklist users from custom Now Playing commands
        """
        if not getattr(self.bot, "db", None):
            return
        ids = set(await self.bot.db.list_lastfm_blacklist(ctx.guild.id))
        if member.id in ids:
            await self.bot.db.remove_lastfm_blacklist(ctx.guild.id, member.id)
            await ctx.success(f"Successfully **removed** {member.mention} from the custom command blacklist.")
            return
        await self.bot.db.set_lastfm_blacklist(ctx.guild.id, member.id)
        await ctx.success(f"Successfully **blacklisted** {member.mention}.")

    @lastfm_customcommand_blacklist.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def lastfm_customcommand_blacklist_list(self, ctx: Context) -> None:
        """
        View list of blacklisted custom command users for NP
        """
        if not getattr(self.bot, "db", None):
            return
        ids = await self.bot.db.list_lastfm_blacklist(ctx.guild.id)
        if not ids:
            await ctx.info(f"{ctx.author.mention}: No **blacklisted users** are set.")
            return
        lines = []
        for index, user_id in enumerate(ids, start=1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            lines.append(f"`{index:02d}` **{name}**")
        await self._send_list(ctx, "Blacklisted custom command users", lines)

    @lastfm.command(name="customreactions")
    async def lastfm_customreactions(
        self,
        ctx: Context,
        upvote: str | None = None,
        downvote: str | None = None,
    ) -> None:
        """
        Set personal upvote and downvote reaction for Now Playing
        """
        if not getattr(self.bot, "db", None):
            return
        current = await self.bot.db.get_lastfm_reactions(ctx.author.id)
        if not upvote and not downvote:
            if not current or not current.get("upvote") or not current.get("downvote"):
                await ctx.info(
                    f"{ctx.author.mention}: Personal **Last.fm reactions** are currently disabled. "
                    "Set them with `lastfm customreactions (upvote) (downvote)`."
                )
                return
            await ctx.info(
                f"{ctx.author.mention}: Personal **Last.fm reactions** are currently "
                f"`{current.get('upvote')}` and `{current.get('downvote')}`. "
                "Use `off` to disable them."
            )
            return
        if self._is_clear_token(upvote):
            await self.bot.db.set_lastfm_reactions(ctx.author.id, None, None)
            await ctx.success("Disabled your **personal Last.fm reactions**.")
            return
        if not upvote or not downvote:
            await ctx.warn("Please provide both reaction emojis or use `off`.")
            return
        await self.bot.db.set_lastfm_reactions(ctx.author.id, upvote, downvote)
        await ctx.success(
            f"Set your **personal Last.fm reactions** to `{upvote}` and `{downvote}`."
        )

    @lastfm.command(name="react")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def lastfm_react(
        self,
        ctx: Context,
        upvote: str | None = None,
        downvote: str | None = None,
    ) -> None:
        """
        Set server upvote and downvote reaction for Now Playing
        """
        if not getattr(self.bot, "db", None):
            return
        current = await self.bot.db.get_lastfm_guild_reactions(ctx.guild.id)
        if not upvote and not downvote:
            if not current or not current.get("upvote") or not current.get("downvote"):
                await ctx.info(
                    f"{ctx.author.mention}: **Server Last.fm reactions** are currently disabled. "
                    "Set them with `lastfm react (upvote) (downvote)`."
                )
                return
            await ctx.info(
                f"{ctx.author.mention}: **Server Last.fm reactions** are currently "
                f"`{current.get('upvote')}` and `{current.get('downvote')}`. "
                "Use `off` to disable them."
            )
            return
        if self._is_clear_token(upvote):
            await self.bot.db.set_lastfm_guild_reactions(ctx.guild.id, None, None)
            await ctx.success("Disabled **server Last.fm reactions**.")
            return
        if not upvote or not downvote:
            await ctx.warn("Please provide both reaction emojis or use `off`.")
            return
        await self.bot.db.set_lastfm_guild_reactions(ctx.guild.id, upvote, downvote)
        await ctx.success(
            f"Set **server Last.fm reactions** to `{upvote}` and `{downvote}`."
        )

    @lastfm.command(name="soundcloud")
    async def lastfm_soundcloud(self, ctx: Context, *, query: str | None = None) -> None:
        """
        Gives Soundcloud link for the current song playing
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        track = await self._nowplaying(username)
        if not track:
            await ctx.info(f"{ctx.author.mention}: No **track** is playing right now.")
            return
        name = track.get("name", "")
        artist = track.get("artist", {}).get("#text") or ""
        query = quote_plus(f"{artist} {name}")
        url = f"https://soundcloud.com/search?q={query}"
        embed = discord.Embed(
            title="SoundCloud",
            description="Search this current track on SoundCloud.",
            color=self._info_color(),
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        view = self._link_view(("☁️", "SoundCloud", url))
        await ctx.send(embed=embed, view=view)

    @lastfm.command(name="spotify")
    async def lastfm_spotify(self, ctx: Context, *, query: str | None = None) -> None:
        """
        Gives Spotify link for the current song playing
        """
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        track = await self._nowplaying(username)
        if not track:
            await ctx.info(f"{ctx.author.mention}: No **track** is playing right now.")
            return
        name = track.get("name", "")
        artist = track.get("artist", {}).get("#text") or ""
        query = quote_plus(f"{artist} {name}")
        url = f"https://open.spotify.com/search/{query}"
        embed = discord.Embed(
            title="Spotify",
            description="Search this current track on Spotify.",
            color=self._info_color(),
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        view = self._link_view(("🟢", "Spotify", url))
        await ctx.send(embed=embed, view=view)

    @lastfm.command(name="lyrics")
    async def lastfm_lyrics(self, ctx: Context, *, query: str | None = None) -> None:
        """
        Gets lyrics for the current song or a search query
        """
        if query:
            lyrics_command = self.bot.get_command("lyrics")
            if lyrics_command:
                await ctx.invoke(lyrics_command, query=query)
                return
            await self._send_lyrics(ctx, query)
            return
        member, ok = await self._optional_mention_target_only(ctx, query)
        if not ok:
            return
        username = await self._username_for(ctx, member)
        if not username:
            return
        track = await self._nowplaying(username)
        if not track:
            await ctx.info(f"{ctx.author.mention}: No **track** is playing right now.")
            return
        name = track.get("name", "")
        artist = track.get("artist", {}).get("#text") or ""
        search = f"{artist} {name}".strip()
        lyrics_command = self.bot.get_command("lyrics")
        if lyrics_command:
            await ctx.invoke(lyrics_command, query=search)
            return
        await self._send_lyrics(ctx, search)

    async def _send_lyrics(self, ctx: Context, query: str) -> None:
        artist, _, title = query.partition(" - ")
        if not title.strip():
            parts = query.rsplit(" ", 1)
            if len(parts) == 2:
                artist, title = parts[0], parts[1]
            else:
                artist, title = query, query
        url = f"https://api.lyrics.ovh/v1/{quote_plus(artist.strip())}/{quote_plus(title.strip())}"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                await ctx.warn("Could not find lyrics for that track.")
                return
            data = await resp.json()
        lyrics = data.get("lyrics")
        if not lyrics:
            await ctx.warn("Could not find lyrics for that track.")
            return
        embed = discord.Embed(
            title=f"{title.strip()} — {artist.strip()}",
            description=lyrics[:4000],
            color=self._lastfm_color(),
        )
        await ctx.send(embed=embed)
    @lastfm.command(name="update")
    async def lastfm_update(self, ctx: Context, *, parameters: str | None = None) -> None:
        """
        Update your Last.fm library
        """
        linked = await self._get_linked_user(ctx, None)
        if not linked:
            return
        username = linked["lastfm_username"]
        async with ctx.typing():
            summary = await self._refresh_library(int(linked["user_id"]), username)
            today_scrobbles = self._format_number(
                await self._today_scrobble_count(username, use_cache=False)
            )
        await ctx.success(
            "Updated your **Last.fm library** "
            f"(`{self._format_number(summary['artists'])}` artists, "
            f"`{self._format_number(summary['albums'])}` albums, "
            f"`{self._format_number(summary['tracks'])}` tracks) "
            f"with **{self._format_number(summary['scrobbles'])}** total scrobbles "
            f"and **{today_scrobbles}** today."
        )

    @lastfm.command(name="color")
    async def lastfm_color(self, ctx: Context, *, hexc: str | None = None) -> None:
        """
        Set embed color for Last.fm commands
        """
        if not getattr(self.bot, "db", None):
            return
        current = await self.bot.db.get_lastfm_color(ctx.author.id)
        if not hexc:
            if not current:
                await ctx.info(
                    f"{ctx.author.mention}: Your **Last.fm color** is using the default theme. "
                    "Set one with `lastfm color #c1272d`."
                )
                return
            await ctx.info(
                f"{ctx.author.mention}: Your **Last.fm color** is currently `#{current}`. "
                "Use `lastfm color off` to clear it."
            )
            return
        if self._is_clear_token(hexc):
            await self.bot.db.set_lastfm_color(ctx.author.id, None)
            await ctx.success("Cleared your **Last.fm color** override.")
            return
        value = hexc.strip().lstrip("#")
        if len(value) != 6 or any(char not in "0123456789abcdefABCDEF" for char in value):
            await ctx.warn("Please provide a valid **hex** color like `#c1272d`.")
            return
        await self.bot.db.set_lastfm_color(ctx.author.id, value)
        await ctx.success(f"Set your **Last.fm color** to `#{value}`.")

    @lastfm.command(name="mode")
    async def lastfm_mode(self, ctx: Context, *, mode: str | None = None) -> None:
        """
        Use a different embed mode for Now Playing
        """
        if not getattr(self.bot, "db", None):
            return
        current = await self._resolve_mode(ctx.author.id)
        if not mode:
            await ctx.info(
                f"{ctx.author.mention}: Your **Last.fm mode** is currently `{current}`. "
                "Choose from `default`, `compact`, `minimal`, or `custom`."
            )
            return
        if self._is_clear_token(mode):
            await self.bot.db.set_lastfm_mode(ctx.author.id, "default")
            await ctx.success("Reset your **Last.fm mode** to `default`.")
            return
        value = mode.strip().lower()
        allowed = {"default", "compact", "minimal", "custom"}
        if value not in allowed:
            await ctx.info(
                f"{ctx.author.mention}: Your **Last.fm mode** is currently `{current}`. "
                "Choose from `default`, `compact`, `minimal`, or `custom`."
            )
            return
        if value == "custom":
            script = await self.bot.db.get_lastfm_custom_embed(ctx.author.id)
            if not script:
                await ctx.warn(
                    f"Set a **custom embed** first with `{ctx.clean_prefix}lastfm embed (script)` "
                    "before switching to `custom` mode."
                )
                return
        await self.bot.db.set_lastfm_mode(ctx.author.id, value)
        await ctx.success(f"Set your **Last.fm mode** to `{value}`.")

    @lastfm.command(name="embed", aliases=["customembed"])
    async def lastfm_embed(self, ctx: Context, *, script: str | None = None) -> None:
        """
        Set a custom embed script for Now Playing.
        Append ``--reply`` so Now Playing (prefix or slash, when a reply target exists)
        sends as a reply to your trigger message.
        """
        if not getattr(self.bot, "db", None):
            return
        if not script:
            current = await self.bot.db.get_lastfm_custom_embed(ctx.author.id)
            if not current:
                await ctx.info(
                    f"{ctx.author.mention}: You do not have a **custom Last.fm embed** yet. "
                    f"Set one with `{ctx.clean_prefix}lastfm embed {{embed}}...`."
                )
                return
            await ctx.info(
                f"{ctx.author.mention}: You already have a **custom Last.fm embed** saved. "
                f"Use `{ctx.clean_prefix}lastfm mode custom` to enable it, or `lastfm embed off` to clear it."
            )
            return
        script, np_reply_flag = self._strip_lastfm_embed_reply_flag(script)
        lowered = script.strip().lower()
        if self._is_clear_token(lowered):
            await self.bot.db.set_lastfm_custom_embed(ctx.author.id, None)
            current_mode = await self._resolve_mode(ctx.author.id)
            if current_mode == "custom":
                await self.bot.db.set_lastfm_mode(ctx.author.id, "default")
                await ctx.success(
                    "Cleared your **custom Last.fm embed** and reset your mode to `default`."
                )
                return
            await ctx.success("Cleared your **custom Last.fm embed**.")
            return
        if not embed_builder.is_embed_script(script):
            await ctx.warn("Please provide a valid **embed script**.")
            return
        await self.bot.db.set_lastfm_custom_embed(
            ctx.author.id, script, np_reply=np_reply_flag
        )
        mode = await self._resolve_mode(ctx.author.id)
        suffix = " It is now live." if mode == "custom" else " Use `lastfm mode custom` to enable it."
        reply_note = " **Reply** to your NP command is on." if np_reply_flag else ""
        await ctx.success(f"Saved your **custom Last.fm embed**.{suffix}{reply_note}")

    @lastfm.command(name="collage")
    async def lastfm_collage(
        self,
        ctx: Context,
        *,
        query: str | None = None,
    ) -> None:
        """
        View a collage of your most listened to albums
        """
        member, tail = await self._consume_optional_plays_query_target(ctx, (query or "").strip())
        if tail is None:
            return
        tokens = tail.split()
        period_input = None
        if tokens:
            last = tokens[-1].strip().lower()
            if PERIODS.get(last) is not None:
                period_input = last
                tokens = tokens[:-1]
        grid_part = " ".join(tokens).strip()
        grid_input = grid_part.lower() if grid_part else None

        username = await self._username_for(ctx, member)
        if not username:
            return
        target = member or ctx.author
        if grid_input and not period_input and self._period_param(grid_input):
            period_input = grid_input
            grid_input = None

        grid_size = 3
        if grid_input:
            value = grid_input.replace(" ", "")
            if "x" in value:
                left, right, *rest = value.split("x")
                if rest or not left.isdigit() or left != right:
                    await ctx.warn("Please provide a valid **grid size** like `3x3`.")
                    return
                grid_size = int(left)
            elif value.isdigit():
                grid_size = int(value)
            else:
                await ctx.warn("Please provide a valid **grid size** like `3x3`.")
                return
            if not 1 <= grid_size <= 10:
                await ctx.warn("Grid sizes must be between **1x1** and **10x10**.")
                return

        period_param = self._period_param(period_input)
        if not period_param:
            await ctx.warn("Unknown period. Try `overall`, `7d`, `1m`, `3m`, `6m`, or `12m`.")
            return

        timeout = aiohttp.ClientTimeout(total=30)
        payload = {
            "theme": "grid",
            "options": {
                "user": username,
                "period": period_param,
                "top": "albums",
                "size": grid_size,
                "names": False,
                "playcount": False,
                "story": False,
            },
        }
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        "https://generator.musicorumapp.com/generate",
                        json=payload,
                    ) as response:
                        if response.status != 200:
                            raise RuntimeError("internal collage generator unavailable")
                        data = await response.json()
            except aiohttp.ClientError:
                raise RuntimeError("internal collage generator request failed")

        encoded = data.get("base64")
        if not encoded:
            raise RuntimeError("internal collage generator returned empty image")
        if "," in encoded:
            encoded = encoded.split(",", 1)[1]
        try:
            image_bytes = base64.b64decode(encoded)
        except (ValueError, TypeError):
            raise RuntimeError("internal collage generator returned invalid image")

        period_label = PERIOD_LABELS.get(period_param, period_param)
        embed = discord.Embed(
            title=f"{username}'s {period_label} album collage",
            color=self._info_color(),
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed.set_image(url="attachment://collage.png")
        await ctx.send(
            embed=embed,
            file=discord.File(io.BytesIO(image_bytes), filename="collage.png"),
        )

    @lastfm.command(name="scoreboard")
    async def lastfm_scoreboard(self, ctx: Context) -> None:
        """
        View the Last.fm server scoreboard
        """
        if not ctx.guild:
            await ctx.warn("Run this command in a **server** to view the scoreboard.")
            return
        if not getattr(self.bot, "db", None):
            return
        linked = await self.bot.db.get_lastfm_users()
        members = await collect_guild_members(ctx.guild)
        guild_members = {member.id: member for member in members}
        rows = [row for row in linked if int(row["user_id"]) in guild_members]
        if not rows:
            await ctx.info(f"{ctx.author.mention}: No **linked** Last.fm users were found in this server.")
            return
        ranked = await self._linked_playcount_rows(rows)
        lines = []
        for index, (user_id, username, plays) in enumerate(ranked[:50], start=1):
            member = guild_members.get(user_id)
            display = member.mention if member else f"**{username}**"
            lines.append(
                f"`{index:02d}` {display} - `{self._format_number(plays)} scrobbles`"
            )
        await self._send_list(ctx, f"{ctx.guild.name} Last.fm scoreboard", lines)

    @lastfm.command(name="globalboard")
    async def lastfm_globalboard(self, ctx: Context) -> None:
        """
        View the Last.fm globalboard
        """
        if not getattr(self.bot, "db", None):
            return
        linked = await self.bot.db.get_lastfm_users()
        if not linked:
            await ctx.info(f"{ctx.author.mention}: No **linked** Last.fm users were found.")
            return
        ranked = await self._linked_playcount_rows(linked)
        lines = [
            f"`{index:02d}` **[{username}](https://www.last.fm/user/{quote_plus(username)})** - "
            f"`{self._format_number(plays)} scrobbles`"
            for index, (_, username, plays) in enumerate(ranked[:50], start=1)
        ]
        await self._send_list(ctx, "Global Last.fm scoreboard", lines)

    @lastfm.command(name="customcommandcleanup")
    async def lastfm_customcommand_cleanup_legacy(self, ctx: Context) -> None:
        """
        Clean up custom commands from absent members
        """
        await self.lastfm_customcommand_cleanup(ctx)
async def setup(bot: Bleed) -> None:
    await bot.add_cog(Lastfm(bot))
