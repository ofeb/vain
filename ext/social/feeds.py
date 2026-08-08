from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import tasks

from core.discord.views.embed import c2

from .ui import (
    build_social_repost_container,
    layout_from_items,
)

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("vain.social.feeds")

PLATFORMS: dict[str, dict[str, Any]] = {
    "tiktok": {
        "table": "monitor.tiktok",
        "label": "TikTok",
        "limit": 20,
        "profile": lambda u: f"https://www.tiktok.com/@{u}",
    },
    "instagram": {
        "table": "monitor.instagram",
        "label": "Instagram",
        "limit": 10,
        "profile": lambda u: f"https://www.instagram.com/{u}/",
    },
    "twitter": {
        "table": "monitor.twitter",
        "label": "X",
        "limit": 40,
        "profile": lambda u: f"https://x.com/{u}",
    },
    "youtube": {
        "table": "monitor.youtube",
        "label": "YouTube",
        "limit": 30,
        "profile": lambda u: f"https://www.youtube.com/@{u.lstrip('@')}",
    },
    "twitch": {
        "table": "monitor.twitch",
        "label": "Twitch",
        "limit": 10,
        "profile": lambda u: f"https://www.twitch.tv/{u}",
    },
    "pinterest": {
        "table": "monitor.pinterest",
        "label": "Pinterest",
        "limit": 50,
        "profile": lambda u: f"https://www.pinterest.com/{u}/",
    },
    "snapchat": {
        "table": "monitor.snapchat",
        "label": "Snapchat",
        "limit": 15,
        "profile": lambda u: f"https://www.snapchat.com/add/{u}",
    },
}

_HANDLE_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")


def normalize_handle(raw: str) -> str:
    return (raw or "").strip().lstrip("@").strip().strip("/")


def valid_handle(raw: str) -> bool:
    h = normalize_handle(raw)
    return bool(h) and bool(_HANDLE_RE.match(h))


class FeedStore:
    """CRUD for ``monitor.*`` feed rows."""

    def __init__(self, bot: Vain) -> None:
        self.bot = bot

    def _meta(self, platform: str) -> dict[str, Any]:
        key = (platform or "").lower().strip()
        if key == "x":
            key = "twitter"
        if key not in PLATFORMS:
            raise ValueError(f"unknown platform: {platform}")
        return PLATFORMS[key]

    async def count(self, platform: str, guild_id: int) -> int:
        meta = self._meta(platform)
        val = await self.bot.db.fetchval(
            f"SELECT COUNT(*) FROM {meta['table']} WHERE guild_id = $1",
            guild_id,
        )
        return int(val or 0)

    async def list(self, platform: str, guild_id: int) -> list[dict[str, Any]]:
        meta = self._meta(platform)
        rows = await self.bot.db.fetch(
            f"SELECT * FROM {meta['table']} WHERE guild_id = $1 ORDER BY username",
            guild_id,
        )
        return [dict(r) for r in rows]

    async def list_all(self, guild_id: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for platform in PLATFORMS:
            for row in await self.list(platform, guild_id):
                out.append({**row, "platform": platform})
        return out

    async def add(
        self,
        platform: str,
        *,
        guild_id: int,
        channel_id: int,
        username: str,
        user_id: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        meta = self._meta(platform)
        uname = normalize_handle(username)
        uid = (user_id or uname).strip() or uname
        if not uname:
            raise ValueError("username required")

        limit = int(meta["limit"])
        if await self.count(platform, guild_id) >= limit:
            raise ValueError(f"limit reached ({limit} {meta['label']} feeds per server)")

        table = meta["table"]
        plat = (platform or "").lower()
        if plat == "x":
            plat = "twitter"

        if plat == "pinterest":
            board_id = str(extra.get("board_id") or "")
            board_name = extra.get("board_name")
            row = await self.bot.db.fetchrow(
                f"""
                INSERT INTO {table}
                    (guild_id, channel_id, user_id, username, board_id, board_name, template)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (guild_id, user_id, board_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    username = EXCLUDED.username,
                    board_name = COALESCE(EXCLUDED.board_name, {table}.board_name)
                RETURNING *
                """,
                guild_id,
                channel_id,
                uid,
                uname,
                board_id,
                board_name,
                extra.get("template"),
            )
        elif plat == "tiktok":
            row = await self.bot.db.fetchrow(
                f"""
                INSERT INTO {table}
                    (guild_id, channel_id, user_id, username, template, reposts, lives)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    username = EXCLUDED.username
                RETURNING *
                """,
                guild_id,
                channel_id,
                uid,
                uname,
                extra.get("template"),
                bool(extra.get("reposts", False)),
                bool(extra.get("lives", False)),
            )
        elif plat == "twitter":
            row = await self.bot.db.fetchrow(
                f"""
                INSERT INTO {table}
                    (guild_id, channel_id, user_id, username, template, retweets, replies, quotes)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    username = EXCLUDED.username
                RETURNING *
                """,
                guild_id,
                channel_id,
                uid,
                uname,
                extra.get("template"),
                bool(extra.get("retweets", True)),
                bool(extra.get("replies", False)),
                bool(extra.get("quotes", True)),
            )
        elif plat == "youtube":
            row = await self.bot.db.fetchrow(
                f"""
                INSERT INTO {table}
                    (guild_id, channel_id, user_id, username, template, shorts)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    username = EXCLUDED.username
                RETURNING *
                """,
                guild_id,
                channel_id,
                uid,
                uname,
                extra.get("template"),
                bool(extra.get("shorts", True)),
            )
        elif plat == "instagram":
            row = await self.bot.db.fetchrow(
                f"""
                INSERT INTO {table}
                    (guild_id, channel_id, user_id, username, template, stories)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    username = EXCLUDED.username
                RETURNING *
                """,
                guild_id,
                channel_id,
                uid,
                uname,
                extra.get("template"),
                bool(extra.get("stories", False)),
            )
        else:
            row = await self.bot.db.fetchrow(
                f"""
                INSERT INTO {table}
                    (guild_id, channel_id, user_id, username, template)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    username = EXCLUDED.username
                RETURNING *
                """,
                guild_id,
                channel_id,
                uid,
                uname,
                extra.get("template"),
            )
        return dict(row) if row else {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "user_id": uid,
            "username": uname,
        }

    async def remove(
        self,
        platform: str,
        *,
        guild_id: int,
        username: str,
        channel_id: int | None = None,
    ) -> int:
        meta = self._meta(platform)
        uname = normalize_handle(username)
        if channel_id:
            result = await self.bot.db.execute(
                f"DELETE FROM {meta['table']} WHERE guild_id = $1 AND "
                f"(username ILIKE $2 OR user_id = $2) AND channel_id = $3",
                guild_id,
                uname,
                channel_id,
            )
        else:
            result = await self.bot.db.execute(
                f"DELETE FROM {meta['table']} WHERE guild_id = $1 AND "
                f"(username ILIKE $2 OR user_id = $2)",
                guild_id,
                uname,
            )
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def migrate(
        self,
        platform: str,
        *,
        guild_id: int,
        from_channel_id: int,
        to_channel_id: int,
    ) -> int:
        meta = self._meta(platform)
        result = await self.bot.db.execute(
            f"UPDATE {meta['table']} SET channel_id = $1 "
            f"WHERE guild_id = $2 AND channel_id = $3",
            to_channel_id,
            guild_id,
            from_channel_id,
        )
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def set_template(
        self,
        platform: str,
        *,
        guild_id: int,
        template: str | None,
        username: str | None = None,
    ) -> int:
        meta = self._meta(platform)
        if username:
            uname = normalize_handle(username)
            result = await self.bot.db.execute(
                f"UPDATE {meta['table']} SET template = $1 "
                f"WHERE guild_id = $2 AND (username ILIKE $3 OR user_id = $3)",
                template,
                guild_id,
                uname,
            )
        else:
            result = await self.bot.db.execute(
                f"UPDATE {meta['table']} SET template = $1 WHERE guild_id = $2",
                template,
                guild_id,
            )
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0

    async def all_records(self, platform: str) -> list[dict[str, Any]]:
        meta = self._meta(platform)
        rows = await self.bot.db.fetch(f"SELECT * FROM {meta['table']}")
        return [dict(r) for r in rows]


class FeedWatcher:
    """Polls social APIs for new posts and dispatches C2 notifications."""

    INTERVAL_SECONDS = 90

    def __init__(self, bot: Vain) -> None:
        self.bot = bot
        self.store = FeedStore(bot)
        self._memory_seen: set[str] = set()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        if not self._poll_loop.is_running():
            self._poll_loop.start()
        self._started = True

    def stop(self) -> None:
        if self._poll_loop.is_running():
            self._poll_loop.cancel()
        self._started = False

    async def _seen(self, platform: str, item_id: str) -> bool:
        key = f"{platform}:{item_id}"
        if key in self._memory_seen:
            return True
        redis = getattr(self.bot, "redis", None)
        if redis is not None:
            try:
                if await redis.sismember(f"feeds:seen:{platform}", item_id):
                    self._memory_seen.add(key)
                    return True
            except Exception:
                pass
        try:
            hit = await self.bot.db.fetchval(
                "SELECT 1 FROM monitor.seen WHERE platform = $1 AND item_id = $2",
                platform,
                str(item_id),
            )
            if hit:
                self._memory_seen.add(key)
                return True
        except Exception:
            pass
        return False

    async def _mark_seen(self, platform: str, item_id: str) -> None:
        key = f"{platform}:{item_id}"
        self._memory_seen.add(key)
        if len(self._memory_seen) > 20_000:
            
            self._memory_seen = set(list(self._memory_seen)[10_000:])
        redis = getattr(self.bot, "redis", None)
        if redis is not None:
            try:
                await redis.sadd(f"feeds:seen:{platform}", item_id)
            except Exception:
                pass
        try:
            await self.bot.db.execute(
                "INSERT INTO monitor.seen (platform, item_id) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING",
                platform,
                str(item_id),
            )
        except Exception as exc:
            log.debug("mark_seen failed: %s", exc)

    def _resolve_channel(self, record: dict[str, Any]) -> Any | None:
        guild = self.bot.get_guild(int(record["guild_id"]))
        if guild is None:
            return None
        channel = guild.get_channel(int(record["channel_id"]))
        if channel is None:
            try:
                channel = guild.get_thread(int(record["channel_id"]))  # type: ignore[attr-defined]
            except Exception:
                channel = None
        if channel is None:
            return None
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return None
        me = guild.me
        if me is None:
            return channel
        try:
            perms = channel.permissions_for(me)
            if not (perms.send_messages and perms.embed_links):
                return None
        except Exception:
            return None
        return channel

    def _item_id(self, platform: str, item: dict[str, Any], username: str) -> str:
        _ = platform
        for key in ("id", "aweme_id", "item_id", "pk", "code", "shortcode", "rest_id", "video_id"):
            val = item.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        url = item.get("url") or item.get("share_url") or ""
        if url:
            return str(url)
        cap = (item.get("caption") or item.get("desc") or item.get("title") or "")[:40]
        return f"{username}:{cap}"

    async def _fetch_items(self, platform: str, username: str) -> list[dict[str, Any]]:
        from . import api as social_api

        uname = normalize_handle(username)
        try:
            if platform == "tiktok":
                return await social_api.tiktok_user_posts(uname, limit=6)
            if platform == "instagram":
                return await social_api.instagram_user_posts(uname, count=6)
            if platform == "twitter":
                return await social_api.twitter_user_tweets(uname)
            if platform == "youtube":
                return await social_api.youtube_channel_videos(uname, limit=6)
            if platform == "twitch":
                
                live = await social_api.twitch_live(uname)
                if isinstance(live, dict) and live:
                    stream = live.get("stream") if isinstance(live.get("stream"), dict) else live
                    if stream and (
                        stream.get("type") == "live"
                        or stream.get("is_live")
                        or live.get("is_live")
                    ):
                        return [
                            {
                                "id": f"live:{stream.get('id') or uname}",
                                "title": stream.get("title") or "Live on Twitch",
                                "url": f"https://www.twitch.tv/{uname}",
                                "is_live": True,
                                "viewers": stream.get("viewers") or stream.get("viewer_count"),
                                "game": (
                                    (stream.get("game") or {}).get("name")
                                    if isinstance(stream.get("game"), dict)
                                    else stream.get("game_name") or stream.get("game")
                                ),
                            }
                        ]
                videos = await social_api.twitch_videos(uname)
                return videos[:4] if videos else []
            if platform == "pinterest":
                
                pins = await social_api.pinterest_search(uname, limit=6)
                return pins
            if platform == "snapchat":
                user = await social_api.snapchat_user(uname)
                if not user:
                    return []
                parsed = social_api.parse_snapchat_user(user, username=uname) or {}
                if parsed.get("has_story"):
                    return [
                        {
                            "id": f"story:{uname}",
                            "title": f"@{uname} has a new story",
                            "url": parsed.get("url") or f"https://www.snapchat.com/add/{uname}",
                        }
                    ]
                return []
        except Exception as exc:
            log.debug("fetch %s/%s failed: %s", platform, uname, exc)
        return []

    def _parse_post(self, platform: str, item: dict[str, Any], username: str = ""):
        from . import api as social_api

        _ = username
        if platform == "tiktok":
            return social_api.parse_tiktok_post(item)
        if platform == "instagram":
            return social_api.parse_instagram_post(item)
        if platform == "twitter":
            return social_api.parse_twitter_status(item)
        if platform == "youtube":
            return social_api.parse_youtube_video(item)
        if platform == "twitch":
            if item.get("is_live"):
                return None
            return social_api.parse_twitch_video(item)
        if platform == "pinterest":
            return social_api.parse_pinterest_pin(item)
        return None

    async def _dispatch(
        self,
        platform: str,
        record: dict[str, Any],
        item: dict[str, Any],
        *,
        first_run: bool,
    ) -> None:
        if first_run:
            
            return

        channel = self._resolve_channel(record)
        if channel is None:
            return

        username = normalize_handle(record.get("username") or "")
        post = self._parse_post(platform, item, username)
        template = (record.get("template") or "").strip()

        meta = PLATFORMS.get(platform) or {}
        profile = ""
        if callable(meta.get("profile")):
            profile = meta["profile"](username)

        try:
            if post is not None:
                handle = post.username if post.username not in ("", "unknown") else username
                display = post.display_name or handle or username
                containers = build_social_repost_container(
                    platform=platform,
                    username=handle or username or "unknown",
                    display_name=display,
                    caption=post.caption or "",
                    media_urls=list(post.media_urls or [])[:4],
                    avatar_url=post.avatar_url,
                    source_url=post.url or profile,
                    like_count=post.like_count,
                    comment_count=post.comment_count,
                    save_count=post.save_count,
                    share_count=post.share_count,
                    play_count=post.play_count,
                    include_actions=True,
                )
                view = layout_from_items(containers, timeout=None)
                content = None
                if template:
                    content = (
                        template.replace("{user}", handle or username)
                        .replace("{username}", handle or username)
                        .replace("{name}", display)
                        .replace("{url}", post.url or profile)
                        .replace("{platform}", meta.get("label", platform))
                    )
                await channel.send(content=content, view=view)  # type: ignore[arg-type]
                return

            
            title = (
                item.get("title")
                or item.get("caption")
                or item.get("desc")
                or item.get("text")
                or "New update"
            )
            url = item.get("url") or profile
            label = meta.get("label", platform.title())
            lines = [f"**{label}** · [@{username}]({profile or url})"]
            if title:
                lines.append(str(title)[:400])
            if item.get("is_live"):
                viewers = item.get("viewers")
                game = item.get("game")
                if game:
                    lines.append(f"Playing **{game}**")
                if viewers:
                    lines.append(f"`{viewers}` watching")
            embed = c2(
                title=f"{label} feed",
                message="\n".join(lines),
                footer=url if url else None,
                timestamp=True,
            )
            content = None
            if template:
                content = (
                    template.replace("{user}", username)
                    .replace("{username}", username)
                    .replace("{name}", username)
                    .replace("{url}", str(url or ""))
                    .replace("{platform}", label)
                )
            await channel.send(content=content, embed=embed)
        except Exception as exc:
            log.debug(
                "dispatch %s guild=%s channel=%s failed: %s",
                platform,
                record.get("guild_id"),
                record.get("channel_id"),
                exc,
            )

    async def _check_platform(self, platform: str) -> None:
        try:
            records = await self.store.all_records(platform)
        except Exception as exc:
            log.debug("load %s feeds failed: %s", platform, exc)
            return
        if not records:
            return

        by_user: dict[str, list[dict[str, Any]]] = {}
        for rec in records:
            key = normalize_handle(rec.get("username") or rec.get("user_id") or "")
            if not key:
                continue
            by_user.setdefault(key.lower(), []).append(rec)

        for uname, group in by_user.items():
            items = await self._fetch_items(platform, uname)
            if not items:
                continue
            prepared: list[tuple[str, dict]] = []
            for item in items[:8]:
                if not isinstance(item, dict):
                    continue
                iid = self._item_id(platform, item, uname)
                prepared.append((iid, item))

            
            unseen_flags: list[bool] = []
            for iid, _ in prepared:
                unseen_flags.append(not await self._seen(platform, iid))
            first_run = bool(unseen_flags) and all(unseen_flags)

            for iid, item in prepared:
                if await self._seen(platform, iid):
                    continue
                await self._mark_seen(platform, iid)
                if first_run:
                    continue
                for rec in group:
                    await self._dispatch(platform, rec, item, first_run=False)
            await asyncio.sleep(0.35)

    @tasks.loop(seconds=INTERVAL_SECONDS)
    async def _poll_loop(self) -> None:
        for platform in PLATFORMS:
            try:
                await self._check_platform(platform)
            except Exception as exc:
                log.debug("poll %s error: %s", platform, exc)
            await asyncio.sleep(0.5)

    @_poll_loop.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()


def format_feed_list(platform: str, rows: list[dict[str, Any]], guild: discord.Guild) -> str:
    meta = PLATFORMS.get(platform) or {"label": platform.title(), "profile": lambda u: u}
    if not rows:
        return f"No **{meta['label']}** feeds configured."
    lines: list[str] = []
    for i, row in enumerate(rows, 1):
        uname = row.get("username") or row.get("user_id") or "?"
        ch = guild.get_channel(int(row["channel_id"])) if row.get("channel_id") else None
        mention = ch.mention if ch else f"`{row.get('channel_id')}`"
        profile = meta["profile"](normalize_handle(str(uname))) if callable(meta.get("profile")) else ""
        link = f"[@{uname}]({profile})" if profile else f"**@{uname}**"
        flags: list[str] = []
        if row.get("lives"):
            flags.append("live")
        if row.get("reposts"):
            flags.append("reposts")
        if row.get("shorts") is False:
            flags.append("no-shorts")
        if row.get("stories"):
            flags.append("stories")
        flag_s = f" · {', '.join(flags)}" if flags else ""
        lines.append(f"**{i}.** {mention} - {link}{flag_s}")
    return "\n".join(lines)


__all__ = [
    "PLATFORMS",
    "FeedStore",
    "FeedWatcher",
    "format_feed_list",
    "normalize_handle",
    "valid_handle",
]
