from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import discord

from .api import LastFMApiClient


class LastFMLibraryStore:
    def __init__(self, bot: discord.Client, api: LastFMApiClient) -> None:
        self.bot = bot
        self.api = api
        self._tables_ready = False

    @staticmethod
    def _number_value(value: str | int | None) -> int:
        return LastFMApiClient._number_value(value)

    @staticmethod
    def _text_value(value: Any) -> str | None:
        return LastFMApiClient._text_value(value)

    @staticmethod
    def _key(value: str) -> str:
        return value.strip().lower()

    async def _ensure_tables(self) -> bool:
        db = getattr(self.bot, "db", None)
        pool = getattr(db, "pool", None)
        if not pool:
            return False
        if self._tables_ready:
            return True

        await pool.execute(
            """
            create table if not exists lastfm_library_profiles (
                user_id bigint primary key,
                username text not null,
                scrobble_count bigint not null default 0,
                artist_count bigint not null default 0,
                album_count bigint not null default 0,
                track_count bigint not null default 0,
                registered_at timestamptz,
                last_indexed_at timestamptz,
                updated_at timestamptz default now()
            )
            """
        )
        await pool.execute(
            """
            create table if not exists lastfm_library_artists (
                user_id bigint not null,
                username text not null,
                artist_key text not null,
                artist_name text not null,
                playcount bigint not null default 0,
                updated_at timestamptz default now(),
                primary key (user_id, artist_key)
            )
            """
        )
        await pool.execute(
            """
            create table if not exists lastfm_library_albums (
                user_id bigint not null,
                username text not null,
                artist_key text not null,
                artist_name text not null,
                album_key text not null,
                album_name text not null,
                playcount bigint not null default 0,
                updated_at timestamptz default now(),
                primary key (user_id, artist_key, album_key)
            )
            """
        )
        await pool.execute(
            """
            create table if not exists lastfm_library_tracks (
                user_id bigint not null,
                username text not null,
                artist_key text not null,
                artist_name text not null,
                track_key text not null,
                track_name text not null,
                playcount bigint not null default 0,
                updated_at timestamptz default now(),
                primary key (user_id, artist_key, track_key)
            )
            """
        )
        await pool.execute(
            """
            create index if not exists lastfm_library_profiles_last_indexed_idx
            on lastfm_library_profiles (last_indexed_at desc)
            """
        )
        await pool.execute(
            """
            create index if not exists lastfm_library_artists_artist_idx
            on lastfm_library_artists (artist_key, playcount desc)
            """
        )
        await pool.execute(
            """
            create index if not exists lastfm_library_albums_lookup_idx
            on lastfm_library_albums (artist_key, album_key, playcount desc)
            """
        )
        await pool.execute(
            """
            create index if not exists lastfm_library_tracks_lookup_idx
            on lastfm_library_tracks (artist_key, track_key, playcount desc)
            """
        )
        self._tables_ready = True
        return True

    async def _fetch_library_items(
        self,
        username: str,
        *,
        method: str,
        key: str,
        item_key: str,
        count: int,
    ) -> list[dict]:
        if count <= 0:
            return []

        pages = max(1, min(math.ceil(count / 1000), 10))
        semaphore = asyncio.Semaphore(4)

        async def fetch_page(page: int) -> list[dict]:
            async with semaphore:
                data = await self.api._request(
                    {
                        "method": method,
                        "user": username,
                        "period": "overall",
                        "limit": "1000",
                        "page": str(page),
                    },
                    use_cache=False,
                )
            if not data:
                return []
            payload = data.get(key, {}).get(item_key, [])
            if isinstance(payload, dict):
                return [payload]
            return payload if isinstance(payload, list) else []

        batches = await asyncio.gather(
            *(fetch_page(page) for page in range(1, pages + 1))
        )
        items: list[dict] = []
        for batch in batches:
            items.extend(batch)
        return items

    async def refresh_library(
        self,
        user_id: int,
        username: str,
        *,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, int]:
        if not await self._ensure_tables():
            raise RuntimeError("internal lastfm library storage unavailable")

        user_data = await self.api._lastfm_user_info(username, use_cache=False)
        if not user_data or "user" not in user_data:
            raise RuntimeError("internal lastfm upstream unavailable")

        user = user_data["user"]
        artist_count = self._number_value(user.get("artist_count"))
        album_count = self._number_value(user.get("album_count"))
        track_count = self._number_value(user.get("track_count"))

        if progress:
            await progress("Refreshing your Last.fm profile snapshot...")

        artists, albums, tracks = await asyncio.gather(
            self._fetch_library_items(
                username,
                method="user.getTopArtists",
                key="topartists",
                item_key="artist",
                count=artist_count,
            ),
            self._fetch_library_items(
                username,
                method="user.getTopAlbums",
                key="topalbums",
                item_key="album",
                count=album_count,
            ),
            self._fetch_library_items(
                username,
                method="user.getTopTracks",
                key="toptracks",
                item_key="track",
                count=track_count,
            ),
        )

        artist_records = [
            (
                user_id,
                username,
                self._key(artist_name),
                artist_name,
                self._number_value(item.get("playcount")),
                datetime.now(timezone.utc),
            )
            for item in artists
            if (artist_name := (self._text_value(item.get("name")) or "").strip())
        ]
        album_records = [
            (
                user_id,
                username,
                self._key(artist_name),
                artist_name,
                self._key(album_name),
                album_name,
                self._number_value(item.get("playcount")),
                datetime.now(timezone.utc),
            )
            for item in albums
            if (artist_name := (self._text_value(item.get("artist")) or "").strip())
            and (album_name := (self._text_value(item.get("name")) or "").strip())
        ]
        track_records = [
            (
                user_id,
                username,
                self._key(artist_name),
                artist_name,
                self._key(track_name),
                track_name,
                self._number_value(item.get("playcount")),
                datetime.now(timezone.utc),
            )
            for item in tracks
            if (artist_name := (self._text_value(item.get("artist")) or "").strip())
            and (track_name := (self._text_value(item.get("name")) or "").strip())
        ]

        registered_raw = None
        registered = user.get("registered")
        if isinstance(registered, dict):
            registered_raw = registered.get("unixtime")
        registered_at = None
        registered_ts = self._number_value(registered_raw)
        if registered_ts > 0:
            registered_at = datetime.fromtimestamp(registered_ts, tz=timezone.utc)
        indexed_at = datetime.now(timezone.utc)

        async with self.bot.db.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "delete from lastfm_library_artists where user_id=$1", user_id
                )
                await connection.execute(
                    "delete from lastfm_library_albums where user_id=$1", user_id
                )
                await connection.execute(
                    "delete from lastfm_library_tracks where user_id=$1", user_id
                )
                if artist_records:
                    await connection.copy_records_to_table(
                        "lastfm_library_artists",
                        columns=[
                            "user_id",
                            "username",
                            "artist_key",
                            "artist_name",
                            "playcount",
                            "updated_at",
                        ],
                        records=artist_records,
                    )
                if album_records:
                    await connection.copy_records_to_table(
                        "lastfm_library_albums",
                        columns=[
                            "user_id",
                            "username",
                            "artist_key",
                            "artist_name",
                            "album_key",
                            "album_name",
                            "playcount",
                            "updated_at",
                        ],
                        records=album_records,
                    )
                if track_records:
                    await connection.copy_records_to_table(
                        "lastfm_library_tracks",
                        columns=[
                            "user_id",
                            "username",
                            "artist_key",
                            "artist_name",
                            "track_key",
                            "track_name",
                            "playcount",
                            "updated_at",
                        ],
                        records=track_records,
                    )
                await connection.execute(
                    """
                    insert into lastfm_library_profiles (
                        user_id,
                        username,
                        scrobble_count,
                        artist_count,
                        album_count,
                        track_count,
                        registered_at,
                        last_indexed_at,
                        updated_at
                    )
                    values ($1, $2, $3, $4, $5, $6, $7, $8, now())
                    on conflict (user_id)
                    do update set
                        username = excluded.username,
                        scrobble_count = excluded.scrobble_count,
                        artist_count = excluded.artist_count,
                        album_count = excluded.album_count,
                        track_count = excluded.track_count,
                        registered_at = excluded.registered_at,
                        last_indexed_at = excluded.last_indexed_at,
                        updated_at = now()
                    """,
                    user_id,
                    username,
                    self._number_value(user.get("playcount")),
                    artist_count,
                    album_count,
                    track_count,
                    registered_at,
                    indexed_at,
                )

        return {
            "scrobbles": self._number_value(user.get("playcount")),
            "artists": len(artist_records),
            "albums": len(album_records),
            "tracks": len(track_records),
        }

    async def get_profile(self, user_id: int) -> dict | None:
        if not await self._ensure_tables():
            return None
        row = await self.bot.db.pool.fetchrow(
            """
            select user_id, username, scrobble_count, artist_count, album_count, track_count,
                   registered_at, last_indexed_at, updated_at
            from lastfm_library_profiles
            where user_id=$1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def get_playcount_rows(self, user_rows: list[dict]) -> list[tuple[int, str, int]]:
        if not user_rows or not await self._ensure_tables():
            return []
        user_ids = [int(row["user_id"]) for row in user_rows]
        rows = await self.bot.db.pool.fetch(
            """
            select profile.user_id, profile.username, profile.scrobble_count
            from lastfm_library_profiles as profile
            where profile.user_id = any($1::bigint[])
            order by profile.scrobble_count desc, profile.username asc
            """,
            user_ids,
        )
        return [
            (
                int(row["user_id"]),
                row["username"],
                self._number_value(row["scrobble_count"]),
            )
            for row in rows
        ]

    async def get_artist_rows(
        self,
        user_rows: list[dict],
        artist: str,
    ) -> list[tuple[str, int, int]]:
        if not user_rows or not await self._ensure_tables():
            return []
        user_ids = [int(row["user_id"]) for row in user_rows]
        rows = await self.bot.db.pool.fetch(
            """
            select artist.username, artist.playcount, artist.user_id
            from lastfm_library_artists as artist
            where artist.user_id = any($1::bigint[])
              and artist.artist_key = $2
            order by artist.playcount desc, artist.username asc
            """,
            user_ids,
            self._key(artist),
        )
        return [
            (row["username"], self._number_value(row["playcount"]), int(row["user_id"]))
            for row in rows
            if self._number_value(row["playcount"]) > 0
        ]

    async def get_track_rows(
        self,
        user_rows: list[dict],
        artist: str,
        track: str,
    ) -> list[tuple[str, int, int]]:
        if not user_rows or not await self._ensure_tables():
            return []
        user_ids = [int(row["user_id"]) for row in user_rows]
        rows = await self.bot.db.pool.fetch(
            """
            select track.username, track.playcount, track.user_id
            from lastfm_library_tracks as track
            where track.user_id = any($1::bigint[])
              and track.artist_key = $2
              and track.track_key = $3
            order by track.playcount desc, track.username asc
            """,
            user_ids,
            self._key(artist),
            self._key(track),
        )
        return [
            (row["username"], self._number_value(row["playcount"]), int(row["user_id"]))
            for row in rows
            if self._number_value(row["playcount"]) > 0
        ]

    async def get_album_rows(
        self,
        user_rows: list[dict],
        artist: str,
        album: str,
    ) -> list[tuple[str, int, int]]:
        if not user_rows or not await self._ensure_tables():
            return []
        user_ids = [int(row["user_id"]) for row in user_rows]
        rows = await self.bot.db.pool.fetch(
            """
            select album.username, album.playcount, album.user_id
            from lastfm_library_albums as album
            where album.user_id = any($1::bigint[])
              and album.artist_key = $2
              and album.album_key = $3
            order by album.playcount desc, album.username asc
            """,
            user_ids,
            self._key(artist),
            self._key(album),
        )
        return [
            (row["username"], self._number_value(row["playcount"]), int(row["user_id"]))
            for row in rows
            if self._number_value(row["playcount"]) > 0
        ]

    async def get_seed_crowns(
        self,
        user_rows: list[dict],
        *,
        minimum_plays: int,
    ) -> list[dict]:
        if not user_rows or not await self._ensure_tables():
            return []
        user_ids = [int(row["user_id"]) for row in user_rows]
        rows = await self.bot.db.pool.fetch(
            """
            select distinct on (artist_key) artist_name, playcount, user_id
            from lastfm_library_artists
            where user_id = any($1::bigint[])
              and playcount >= $2
            order by artist_key asc, playcount desc, user_id asc
            """,
            user_ids,
            max(1, int(minimum_plays)),
        )
        return [dict(row) for row in rows]

    async def get_random_artist(self, user_id: int) -> dict | None:
        if not await self._ensure_tables():
            return None
        row = await self.bot.db.pool.fetchrow(
            """
            select artist_name, playcount
            from lastfm_library_artists
            where user_id=$1
            order by random()
            limit 1
            """,
            user_id,
        )
        return dict(row) if row else None
