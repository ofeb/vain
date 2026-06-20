from __future__ import annotations

import asyncio
import base64
import contextlib
import copy
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp
import discord

from core.discord.ctx import Context
from core.managers.values import api as api_values

from .constants import LASTFM_EMBED_FOOTER_ICON_URL

LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"


class LastFMApiClient:
    def __init__(
        self,
        bot: discord.Client,
        *,
        lastfm_color,
    ) -> None:
        self.bot = bot
        self._lastfm_color = lastfm_color
        self._spotify_token: str | None = None
        self._spotify_token_expires = 0.0
        self._cache: dict[str, tuple[float, Any]] = {}
        self._session: aiohttp.ClientSession | None = None

    @staticmethod
    def _text_value(value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("#text", "name", "key", "token"):
                text = value.get(key)
                if isinstance(text, str):
                    return text
            return None
        if isinstance(value, str):
            return value
        return None

    @staticmethod
    def _number_value(value: str | int | None) -> int:
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

    @staticmethod
    def _format_duration(ms: int | None) -> str:
        if not ms:
            return "n/a"
        total = max(0, int(ms) // 1000)
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _clean_query_url(url: str | None) -> str | None:
        if not url:
            return None
        return url if url.startswith("http") else None

    @staticmethod
    def _truncate_text(value: str | None, limit: int = 300) -> str:
        text = (value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "..."

    def _cache_key(self, namespace: str, params: dict[str, Any]) -> str:
        parts = [f"{key}={params[key]}" for key in sorted(params)]
        return f"{namespace}|" + "|".join(parts)

    def _cache_ttl(self, params: dict[str, Any]) -> int:
        method = str(params.get("method") or "")
        if method == "user.getInfo":
            return 45
        if method == "user.getRecentTracks":
            if str(params.get("limit")) == "1":
                return 15
            if params.get("from") is not None:
                return 30
            return 0
        if method in {"artist.getInfo", "track.getInfo", "album.getInfo"}:
            return 30
        if method.endswith(".search"):
            return 300
        return 0

    def _get_cached(self, key: str) -> Any | None:
        cached = self._cache.get(key)
        if not cached:
            return None
        expires_at, data = cached
        if time.time() >= expires_at:
            self._cache.pop(key, None)
            return None
        return copy.deepcopy(data)

    def _set_cached(self, key: str, ttl: int, data: Any) -> None:
        if ttl <= 0:
            return
        self._cache[key] = (time.time() + ttl, copy.deepcopy(data))
        if len(self._cache) > 256:
            oldest = min(self._cache.items(), key=lambda item: item[1][0])[0]
            self._cache.pop(oldest, None)

    def _clear_lastfm_cache(self) -> None:
        self._cache.clear()

    def _api_key(self) -> str | None:
        value = api_values.lastfm.key
        return value.strip() if value and value.strip() else None

    def _api_secret(self) -> str | None:
        value = api_values.lastfm.secret
        return value.strip() if value and value.strip() else None

    def _lastfm_sig(self, params: dict[str, str]) -> str | None:
        secret = self._api_secret()
        if not secret:
            return None
        parts = "".join(f"{key}{value}" for key, value in sorted(params.items()))
        return hashlib.md5(f"{parts}{secret}".encode("utf-8")).hexdigest()

    async def _http_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        timeout = aiohttp.ClientTimeout(total=12)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _request(
        self,
        params: dict[str, Any],
        *,
        use_cache: bool = True,
    ) -> dict | None:
        api_key = self._api_key()
        if not api_key:
            return None
        payload = {"api_key": api_key, "format": "json", **params}
        ttl = self._cache_ttl(params)
        cache_key = self._cache_key("lastfm", payload)
        if use_cache and ttl > 0:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

        try:
            session = await self._http_session()
            async with session.get(LASTFM_BASE, params=payload) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

        if use_cache and ttl > 0 and data and "error" not in data:
            self._set_cached(cache_key, ttl, data)
        return data

    async def _signed_request(self, params: dict[str, str]) -> dict | None:
        api_key = self._api_key()
        if not api_key:
            return None
        sig_params = {"api_key": api_key, **params}
        sig = self._lastfm_sig(sig_params)
        if not sig:
            return None
        payload = {**sig_params, "api_sig": sig}
        return await self._request(payload)

    async def _signed_post_request(self, params: dict[str, str]) -> dict | None:
        api_key = self._api_key()
        if not api_key:
            return None
        sig_params = {"api_key": api_key, **params}
        sig = self._lastfm_sig(sig_params)
        if not sig:
            return None
        payload = {**sig_params, "api_sig": sig, "format": "json"}
        try:
            session = await self._http_session()
            async with session.post(LASTFM_BASE, data=payload) as resp:
                if resp.status != 200:
                    return None
                try:
                    data = await resp.json(content_type=None)
                except (json.JSONDecodeError, aiohttp.ContentTypeError, UnicodeDecodeError):
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None
        if data and isinstance(data, dict) and "error" not in data:
            self._clear_lastfm_cache()
        return data if isinstance(data, dict) else None

    @staticmethod
    def write_action_ok(payload: dict | None) -> bool:
        if not isinstance(payload, dict) or not payload:
            return False
        if payload.get("error") is not None:
            return False
        lfm = payload.get("lfm")
        if isinstance(lfm, dict):
            return str(lfm.get("status", "")).lower() == "ok"
        return True

    @staticmethod
    def api_error_message(payload: dict | None) -> str | None:
        if not isinstance(payload, dict) or payload.get("error") is None:
            return None
        msg = payload.get("message")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
        code = payload.get("error")
        return f"Last.fm error ({code})."

    async def canonical_track_names_for_user(
        self,
        username: str,
        artist: str,
        track: str,
    ) -> tuple[str, str]:
        artist = artist.strip()
        track = track.strip()
        data = await self._request(
            {
                "method": "track.getInfo",
                "artist": artist,
                "track": track,
                "username": username,
                "autocorrect": "1",
            },
            use_cache=False,
        )
        if not data or "track" not in data:
            return artist, track
        payload = data["track"]
        candidate_artist = self._text_value(payload.get("artist"))
        if not candidate_artist and isinstance(payload.get("artist"), dict):
            candidate_artist = payload["artist"].get("name")
        candidate_track = payload.get("name")
        if isinstance(candidate_track, dict):
            candidate_track = self._text_value(candidate_track)
        final_artist = (
            candidate_artist.strip()
            if isinstance(candidate_artist, str) and candidate_artist.strip()
            else artist
        )
        final_track = (
            candidate_track.strip()
            if isinstance(candidate_track, str) and candidate_track.strip()
            else track
        )
        return final_artist, final_track

    async def _spotify_access_token(self) -> str | None:
        now = time.time()
        if self._spotify_token and now < self._spotify_token_expires - 30:
            return self._spotify_token

        client_id = api_values.spotify_client_id
        client_secret = api_values.spotify_client_secret
        if not client_id or not client_secret:
            return None

        auth = f"{client_id}:{client_secret}".encode("utf-8")
        headers = {
            "Authorization": f"Basic {base64.b64encode(auth).decode('ascii')}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            session = await self._http_session()
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

        token = data.get("access_token")
        expires_in = data.get("expires_in", 0)
        if not token:
            return None

        self._spotify_token = token
        self._spotify_token_expires = now + int(expires_in or 0)
        return token

    async def _spotify_track_lookup(
        self,
        artist: str,
        track: str,
        *,
        need_artist_image: bool = False,
    ) -> dict[str, str]:
        token = await self._spotify_access_token()
        if not token:
            return {}

        headers = {"Authorization": f"Bearer {token}"}
        query = f"{artist} {track}".strip()
        if not query:
            return {}

        try:
            session = await self._http_session()
            async with session.get(
                "https://api.spotify.com/v1/search",
                headers=headers,
                params={"q": query, "type": "track", "limit": "1"},
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()

            tracks = data.get("tracks", {}).get("items", [])
            if not tracks:
                return {}

            track_data = tracks[0]
            album = track_data.get("album", {})
            artist_data = (track_data.get("artists") or [{}])[0]
            result = {
                "spotify_url": track_data.get("external_urls", {}).get("spotify", "n/a"),
                "release_date": album.get("release_date", "n/a"),
                "duration": self._format_duration(track_data.get("duration_ms")),
            }
            if need_artist_image and artist_data.get("id"):
                async with session.get(
                    f"https://api.spotify.com/v1/artists/{artist_data['id']}",
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        artist_payload = await resp.json()
                        images = artist_payload.get("images", [])
                        if images:
                            result["artist_image"] = images[0].get("url", "n/a")
            return result
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return {}

    async def _artist_search(self, query: str, *, use_cache: bool = True) -> dict | None:
        data = await self._request(
            {"method": "artist.search", "artist": query, "limit": "1"},
            use_cache=use_cache,
        )
        if not data:
            return None
        matches = data.get("results", {}).get("artistmatches", {}).get("artist", [])
        if isinstance(matches, dict):
            return matches
        return matches[0] if matches else None

    async def _track_search(self, query: str, *, use_cache: bool = True) -> dict | None:
        data = await self._request(
            {"method": "track.search", "track": query, "limit": "1"},
            use_cache=use_cache,
        )
        if not data:
            return None
        matches = data.get("results", {}).get("trackmatches", {}).get("track", [])
        if isinstance(matches, dict):
            return matches
        return matches[0] if matches else None

    async def _album_search(self, query: str, *, use_cache: bool = True) -> dict | None:
        data = await self._request(
            {"method": "album.search", "album": query, "limit": "1"},
            use_cache=use_cache,
        )
        if not data:
            return None
        matches = data.get("results", {}).get("albummatches", {}).get("album", [])
        if isinstance(matches, dict):
            return matches
        return matches[0] if matches else None

    def _split_artist_track(self, value: str) -> tuple[str, str] | None:
        if " - " in value:
            artist, track = value.split(" - ", 1)
        elif " — " in value:
            artist, track = value.split(" — ", 1)
        elif "|" in value:
            artist, track = value.split("|", 1)
        else:
            return None
        artist = artist.strip()
        track = track.strip()
        if not artist or not track:
            return None
        return artist, track

    def _split_artist_album(self, value: str) -> tuple[str, str] | None:
        return self._split_artist_track(value)

    async def _resolve_artist_name(self, username: str, artist: str | None) -> str | None:
        if artist and artist.strip():
            return artist.strip()
        track = await self._nowplaying(username)
        if not track:
            return None
        artist_name = self._text_value(track.get("artist")) or track.get("artist", {}).get("#text")
        return artist_name.strip() if artist_name else None

    async def _resolve_track_identity(
        self,
        username: str,
        query: str | None,
    ) -> tuple[str, str] | None:
        if query and query.strip():
            parsed = self._split_artist_track(query)
            if parsed:
                return parsed
            match = await self._track_search(query.strip())
            if not match:
                return None
            artist_name = self._text_value(match.get("artist"))
            track_name = self._text_value(match.get("name"))
            if artist_name and track_name:
                return artist_name.strip(), track_name.strip()
            return None

        current = await self._nowplaying(username)
        if not current:
            return None
        artist_name = current.get("artist", {}).get("#text") or self._text_value(current.get("artist"))
        track_name = current.get("name")
        if not artist_name or not track_name:
            return None
        return artist_name.strip(), track_name.strip()

    async def _resolve_album_identity(
        self,
        username: str,
        query: str | None,
    ) -> tuple[str, str] | None:
        if query and query.strip():
            parsed = self._split_artist_album(query)
            if parsed:
                return parsed
            match = await self._album_search(query.strip())
            if not match:
                return None
            artist_name = self._text_value(match.get("artist"))
            album_name = self._text_value(match.get("name"))
            if artist_name and album_name:
                return artist_name.strip(), album_name.strip()
            return None

        current = await self._nowplaying(username)
        if not current:
            return None
        artist_name = current.get("artist", {}).get("#text") or self._text_value(current.get("artist"))
        album_name = current.get("album", {}).get("#text") or self._text_value(current.get("album"))
        if not artist_name or not album_name:
            return None
        return artist_name.strip(), album_name.strip()

    async def _session_key_for(self, user_id: int) -> str | None:
        if not getattr(self.bot, "db", None):
            return None
        data = await self.bot.db.get_lastfm_user(user_id)
        session_key = self._text_value(data.get("session_key")) if data else None
        return session_key or None

    async def _poll_lastfm_session(self, token: str, user_id: int) -> None:
        if not getattr(self.bot, "db", None):
            return
        start = asyncio.get_running_loop().time()
        timeout = 120.0
        while asyncio.get_running_loop().time() - start < timeout:
            data = await self._signed_request(
                {"method": "auth.getSession", "token": token}
            )
            if data and "session" in data:
                session = data.get("session", {})
                username = self._text_value(session.get("name"))
                session_key = self._text_value(session.get("key"))
                if username and session_key:
                    await self.bot.db.set_lastfm_user(user_id, username, session_key)
                    await self.bot.db.mark_lastfm_login_used(token)
                    with contextlib.suppress(discord.HTTPException):
                        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                        if user:
                            embed = discord.Embed(
                                description=(
                                    f"Your **Last.fm** account has been linked as `{username}`."
                                ),
                                color=self._lastfm_color(),
                            )
                            embed.set_footer(
                                text="Last.fm",
                                icon_url=LASTFM_EMBED_FOOTER_ICON_URL,
                            )
                            await user.send(embed=embed)
                    return
            await asyncio.sleep(4)

    async def _get_linked_user(
        self,
        ctx: Context,
        member: discord.abc.User | None,
    ) -> dict | None:
        target = member or ctx.author
        if not getattr(self.bot, "db", None):
            return None
        data = await self.bot.db.get_lastfm_user(target.id)
        if data:
            return data
        if target.id == ctx.author.id:
            message = (
                "You do not have a **Last.fm** account linked yet. "
                f"You can link it with `{ctx.clean_prefix}lastfm login`."
            )
        else:
            message = f"{target} does not have a **Last.fm** account linked yet."
        await ctx.warn(message)
        return None

    async def _username_for(
        self,
        ctx: Context,
        member: discord.abc.User | None,
    ) -> str | None:
        data = await self._get_linked_user(ctx, member)
        if not data:
            return None
        return data.get("lastfm_username")

    async def _lastfm_user_info(
        self,
        username: str,
        *,
        use_cache: bool = True,
    ) -> dict | None:
        return await self._request(
            {"method": "user.getInfo", "user": username},
            use_cache=use_cache,
        )

    async def _nowplaying(
        self,
        username: str,
        *,
        use_cache: bool = True,
    ) -> dict | None:
        data = await self._request(
            {"method": "user.getRecentTracks", "user": username, "limit": "1"},
            use_cache=use_cache,
        )
        if not data:
            return None
        tracks = data.get("recenttracks", {}).get("track", [])
        if not tracks:
            return None
        return tracks[0]

    async def _today_scrobble_count(
        self,
        username: str,
        *,
        use_cache: bool = True,
    ) -> int:
        start_utc = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        data = await self._request(
            {
                "method": "user.getRecentTracks",
                "user": username,
                "from": str(int(start_utc.timestamp())),
                "limit": "1",
                "page": "1",
            },
            use_cache=use_cache,
        )
        if not data:
            return 0
        total = data.get("recenttracks", {}).get("@attr", {}).get("total")
        return self._number_value(total)

    async def _top_artists(
        self,
        username: str,
        *,
        limit: int = 50,
        period: str = "overall",
    ) -> list[dict]:
        data = await self._request(
            {
                "method": "user.getTopArtists",
                "user": username,
                "period": period,
                "limit": str(limit),
            }
        )
        artists = data.get("topartists", {}).get("artist", []) if data else []
        if isinstance(artists, dict):
            return [artists]
        return artists
