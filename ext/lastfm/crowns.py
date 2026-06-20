from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from typing import Any, Awaitable, Callable

import discord

from core.discord.ctx import Context
from core.managers.values import lastfm_crown
from core.tools.guild_members import collect_guild_members

from .api import LastFMApiClient
from .library import LastFMLibraryStore


class LastFMCrownStore:
    def __init__(
        self,
        bot: discord.Client,
        api: LastFMApiClient,
        library: LastFMLibraryStore,
        *,
        top_artists_fetcher: Callable[[str], Awaitable[list[dict]]],
    ) -> None:
        self.bot = bot
        self.api = api
        self.library = library
        self._top_artists_fetcher = top_artists_fetcher
        self._crowns_table_ready = False

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
    def _text_value(value: Any) -> str | None:
        return LastFMApiClient._text_value(value)

    @staticmethod
    def _aggregate_listener_leaderboard_rows(
        rows: list[tuple[str, int, int]],
    ) -> list[tuple[str, int, int]]:
        if not rows:
            return []
        by_uid: dict[int, tuple[str, int]] = {}
        for username, plays, uid in rows:
            uname = (username or "").strip()
            if not uname or plays <= 0:
                continue
            uid = int(uid)
            prev = by_uid.get(uid)
            if prev is None:
                by_uid[uid] = (uname, plays)
            else:
                prev_name, prev_plays = prev
                if plays > prev_plays or (
                    plays == prev_plays and uname.lower() < prev_name.lower()
                ):
                    by_uid[uid] = (uname, plays)

        keyed: defaultdict[str, list[tuple[str, int, int]]] = defaultdict(list)
        for uid, (uname, plays) in by_uid.items():
            keyed[uname.lower()].append((uname, plays, uid))

        aggregated: list[tuple[str, int, int]] = []
        for buckets in keyed.values():
            best_plays = max(plays for _, plays, _ in buckets)
            contenders = [(name, plays, uid) for name, plays, uid in buckets if plays == best_plays]
            chosen_name = sorted(contenders, key=lambda item: (item[0].lower(), item[0]))[0][0]
            canon_uid = min(item[2] for item in contenders)
            aggregated.append((chosen_name, best_plays, canon_uid))

        aggregated.sort(key=lambda row: (-row[1], row[0].lower()))
        return aggregated

    async def _guild_lastfm_candidates(self, guild: discord.Guild) -> list[dict]:
        if not getattr(self.bot, "db", None):
            return []
        users = await self.bot.db.get_lastfm_users()
        members = await collect_guild_members(guild)
        guild_members = {member.id for member in members}
        hidden = set(await self.bot.db.list_lastfm_hidden(guild.id))
        return [
            user
            for user in users
            if user["user_id"] in guild_members and user["user_id"] not in hidden
        ]

    async def _ensure_crowns_table(self) -> bool:
        db = getattr(self.bot, "db", None)
        pool = getattr(db, "pool", None)
        if not pool:
            return False
        if self._crowns_table_ready:
            return True

        await pool.execute(
            """
            create table if not exists lastfm_crowns (
                guild_id bigint not null,
                artist_key text not null,
                artist_name text not null,
                user_id bigint not null,
                playcount bigint not null default 0,
                claimed_at timestamptz default now(),
                updated_at timestamptz default now(),
                primary key (guild_id, artist_key)
            )
            """
        )
        await pool.execute(
            """
            create table if not exists lastfm_crown_history (
                id bigserial primary key,
                guild_id bigint not null,
                artist_key text not null,
                artist_name text not null,
                previous_user_id bigint,
                previous_playcount bigint,
                new_user_id bigint not null,
                new_playcount bigint not null,
                changed_at timestamptz default now()
            )
            """
        )
        self._crowns_table_ready = True
        return True

    async def _upsert_crown(
        self,
        guild_id: int,
        artist_name: str,
        user_id: int,
        playcount: int,
    ) -> None:
        if not await self._ensure_crowns_table():
            return
        artist_key = artist_name.strip().lower()
        if not artist_key:
            return

        existing = await self.bot.db.pool.fetchrow(
            """
            select user_id, playcount
            from lastfm_crowns
            where guild_id=$1 and artist_key=$2
            """,
            guild_id,
            artist_key,
        )
        await self.bot.db.pool.execute(
            """
            insert into lastfm_crowns (guild_id, artist_key, artist_name, user_id, playcount)
            values ($1, $2, $3, $4, $5)
            on conflict (guild_id, artist_key)
            do update set
                artist_name = excluded.artist_name,
                user_id = excluded.user_id,
                playcount = excluded.playcount,
                claimed_at = case
                    when lastfm_crowns.user_id <> excluded.user_id then now()
                    else lastfm_crowns.claimed_at
                end,
                updated_at = now()
            """,
            guild_id,
            artist_key,
            artist_name,
            user_id,
            max(0, int(playcount)),
        )

        existing_user_id = int(existing["user_id"]) if existing else None
        existing_playcount = self._number_value(existing["playcount"]) if existing else None
        if existing_user_id is None or existing_user_id != user_id:
            await self.bot.db.pool.execute(
                """
                insert into lastfm_crown_history (
                    guild_id, artist_key, artist_name,
                    previous_user_id, previous_playcount,
                    new_user_id, new_playcount
                )
                values ($1, $2, $3, $4, $5, $6, $7)
                """,
                guild_id,
                artist_key,
                artist_name,
                existing_user_id,
                existing_playcount,
                user_id,
                max(0, int(playcount)),
            )

    async def _get_crown(self, guild_id: int, artist_name: str) -> dict | None:
        if not await self._ensure_crowns_table():
            return None
        artist_key = artist_name.strip().lower()
        if not artist_key:
            return None
        row = await self.bot.db.pool.fetchrow(
            """
            select guild_id, artist_name, user_id, playcount, claimed_at, updated_at
            from lastfm_crowns
            where guild_id=$1 and artist_key=$2
            """,
            guild_id,
            artist_key,
        )
        return dict(row) if row else None

    async def _list_crown_history(
        self,
        guild_id: int,
        artist_name: str,
        limit: int = 10,
    ) -> list[dict]:
        if not await self._ensure_crowns_table():
            return []
        artist_key = artist_name.strip().lower()
        if not artist_key:
            return []
        rows = await self.bot.db.pool.fetch(
            """
            select previous_user_id, previous_playcount, new_user_id, new_playcount, changed_at
            from lastfm_crown_history
            where guild_id=$1 and artist_key=$2
            order by changed_at desc
            limit $3
            """,
            guild_id,
            artist_key,
            max(1, min(limit, 50)),
        )
        return [dict(row) for row in rows]

    async def _list_crowns(self, guild_id: int) -> list[dict]:
        if not await self._ensure_crowns_table():
            return []
        rows = await self.bot.db.pool.fetch(
            """
            select guild_id, artist_name, user_id, playcount, claimed_at, updated_at
            from lastfm_crowns
            where guild_id=$1
            order by playcount desc, updated_at desc
            """,
            guild_id,
        )
        return [dict(row) for row in rows]

    async def _list_user_crowns(self, guild_id: int, user_id: int) -> list[dict]:
        if not await self._ensure_crowns_table():
            return []
        rows = await self.bot.db.pool.fetch(
            """
            select guild_id, artist_name, user_id, playcount, claimed_at, updated_at
            from lastfm_crowns
            where guild_id=$1 and user_id=$2
            order by playcount desc, updated_at desc
            """,
            guild_id,
            user_id,
        )
        return [dict(row) for row in rows]

    async def _ensure_artwork_table(self) -> bool:
        db = getattr(self.bot, "db", None)
        pool = getattr(db, "pool", None)
        if not pool:
            return False
        await pool.execute(
            """
            create table if not exists lastfm_album_artwork (
                user_id bigint not null,
                artist_key text not null,
                album_key text not null,
                artist_name text not null,
                album_name text not null,
                image_url text not null,
                created_at timestamptz default now(),
                updated_at timestamptz default now(),
                primary key (user_id, artist_key, album_key)
            )
            """
        )
        return True

    async def _set_album_artwork(
        self,
        user_id: int,
        artist_name: str,
        album_name: str,
        image_url: str,
    ) -> None:
        if not await self._ensure_artwork_table():
            raise RuntimeError("internal lastfm artwork storage unavailable")
        artist_key = artist_name.strip().lower()
        album_key = album_name.strip().lower()
        await self.bot.db.pool.execute(
            """
            insert into lastfm_album_artwork (
                user_id, artist_key, album_key, artist_name, album_name, image_url
            )
            values ($1, $2, $3, $4, $5, $6)
            on conflict (user_id, artist_key, album_key)
            do update set
                artist_name = excluded.artist_name,
                album_name = excluded.album_name,
                image_url = excluded.image_url,
                updated_at = now()
            """,
            user_id,
            artist_key,
            album_key,
            artist_name,
            album_name,
            image_url,
        )

    async def _get_album_artwork(
        self,
        user_id: int,
        artist_name: str,
        album_name: str,
    ) -> str | None:
        if not await self._ensure_artwork_table():
            return None
        artist_key = artist_name.strip().lower()
        album_key = album_name.strip().lower()
        if not artist_key or not album_key:
            return None
        row = await self.bot.db.pool.fetchrow(
            """
            select image_url
            from lastfm_album_artwork
            where user_id=$1 and artist_key=$2 and album_key=$3
            """,
            user_id,
            artist_key,
            album_key,
        )
        return row["image_url"] if row else None

    async def _linked_playcount_rows(
        self,
        user_rows: list[dict],
    ) -> list[tuple[int, str, int]]:
        indexed = await self.library.get_playcount_rows(user_rows)
        indexed_ids = {user_id for user_id, _, _ in indexed}
        missing_rows = [row for row in user_rows if int(row["user_id"]) not in indexed_ids]

        if not missing_rows:
            return indexed

        semaphore = asyncio.Semaphore(6)

        async def fetch(row: dict) -> tuple[int, str, int]:
            user_id = int(row["user_id"])
            username = row["lastfm_username"]
            async with semaphore:
                data = await self.api._lastfm_user_info(username)
            plays = 0
            if data and "user" in data:
                plays = self._number_value(data["user"].get("playcount"))
            return user_id, username, plays

        live_rows = await asyncio.gather(*(fetch(row) for row in missing_rows))
        combined = indexed + live_rows
        return sorted(combined, key=lambda entry: entry[2], reverse=True)

    async def _fetch_artist_rows(
        self,
        candidates: list[dict],
        artist: str,
    ) -> list[tuple[str, int, int]]:
        indexed = await self.library.get_artist_rows(candidates, artist)
        indexed_ids = {user_id for _, _, user_id in indexed}
        missing = [user for user in candidates if int(user["user_id"]) not in indexed_ids]
        if not missing:
            return self._aggregate_listener_leaderboard_rows(list(indexed))

        semaphore = asyncio.Semaphore(6)

        async def fetch(user: dict) -> tuple[str, int, int]:
            async with semaphore:
                data = await self.api._request(
                    {
                        "method": "artist.getInfo",
                        "artist": artist,
                        "username": user["lastfm_username"],
                    }
                )
            plays = 0
            if data and "artist" in data:
                plays = self._number_value(data["artist"].get("stats", {}).get("userplaycount"))
            return user["lastfm_username"], plays, int(user["user_id"])

        results = await asyncio.gather(*(fetch(user) for user in missing))
        return self._aggregate_listener_leaderboard_rows(
            [row for row in indexed + results if row[1] > 0],
        )

    async def _fetch_track_rows(
        self,
        candidates: list[dict],
        artist: str,
        track: str,
    ) -> list[tuple[str, int, int]]:
        indexed = await self.library.get_track_rows(candidates, artist, track)
        indexed_ids = {user_id for _, _, user_id in indexed}
        missing = [user for user in candidates if int(user["user_id"]) not in indexed_ids]
        if not missing:
            return self._aggregate_listener_leaderboard_rows(list(indexed))

        semaphore = asyncio.Semaphore(6)

        async def fetch(user: dict) -> tuple[str, int, int]:
            async with semaphore:
                data = await self.api._request(
                    {
                        "method": "track.getInfo",
                        "artist": artist,
                        "track": track,
                        "username": user["lastfm_username"],
                    }
                )
            plays = 0
            if data and "track" in data:
                plays = self._number_value(data["track"].get("userplaycount"))
            return user["lastfm_username"], plays, int(user["user_id"])

        results = await asyncio.gather(*(fetch(user) for user in missing))
        return self._aggregate_listener_leaderboard_rows(
            [row for row in indexed + results if row[1] > 0],
        )

    async def _fetch_album_rows(
        self,
        candidates: list[dict],
        artist: str,
        album: str,
    ) -> list[tuple[str, int, int]]:
        indexed = await self.library.get_album_rows(candidates, artist, album)
        indexed_ids = {user_id for _, _, user_id in indexed}
        missing = [user for user in candidates if int(user["user_id"]) not in indexed_ids]
        if not missing:
            return self._aggregate_listener_leaderboard_rows(list(indexed))

        semaphore = asyncio.Semaphore(6)

        async def fetch(user: dict) -> tuple[str, int, int]:
            async with semaphore:
                data = await self.api._request(
                    {
                        "method": "album.getInfo",
                        "artist": artist,
                        "album": album,
                        "username": user["lastfm_username"],
                    }
                )
            plays = 0
            if data and "album" in data:
                plays = self._number_value(data["album"].get("userplaycount"))
            return user["lastfm_username"], plays, int(user["user_id"])

        results = await asyncio.gather(*(fetch(user) for user in missing))
        return self._aggregate_listener_leaderboard_rows(
            [row for row in indexed + results if row[1] > 0],
        )

    async def _seed_crowns_from_top_artists(self, guild: discord.Guild) -> None:
        candidates = await self._guild_lastfm_candidates(guild)
        if not candidates:
            return

        min_crown_plays = lastfm_crown.min_plays
        min_required = max(1, min_crown_plays)

        stored_crowns = await self.library.get_seed_crowns(
            candidates,
            minimum_plays=min_required,
        )
        if stored_crowns:
            for row in stored_crowns:
                await self._upsert_crown(
                    guild.id,
                    row["artist_name"],
                    int(row["user_id"]),
                    self._number_value(row["playcount"]),
                )
            return

        semaphore = asyncio.Semaphore(4)

        async def fetch(user: dict) -> tuple[int, list[dict]]:
            async with semaphore:
                artists = await self._top_artists_fetcher(user["lastfm_username"])
            return int(user["user_id"]), artists

        user_artist_rows = await asyncio.gather(*(fetch(user) for user in candidates))
        crown_map: dict[str, tuple[str, int, int]] = {}
        for user_id, artists in user_artist_rows:
            for artist in artists:
                artist_name = artist.get("name", "").strip()
                if not artist_name:
                    continue
                plays = self._number_value(artist.get("playcount"))
                if plays < min_required:
                    continue
                artist_key = artist_name.lower()
                current = crown_map.get(artist_key)
                if current is None or plays > current[1]:
                    crown_map[artist_key] = (artist_name, plays, user_id)

        for artist_name, plays, user_id in crown_map.values():
            await self._upsert_crown(guild.id, artist_name, user_id, plays)

    async def _artist_crown(
        self,
        ctx: Context,
        artist: str,
        target_id: int,
    ) -> str:
        if not ctx.guild or not getattr(self.bot, "db", None):
            return ""
        candidates = await self._guild_lastfm_candidates(ctx.guild)
        if not candidates:
            return ""
        rows = await self._fetch_artist_rows(candidates, artist)
        if not rows:
            return ""
        _, top_plays, top_user = rows[0]
        if top_user == target_id and top_plays > 0:
            return "👑"
        return ""
