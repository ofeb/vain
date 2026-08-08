from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile
import textwrap
import urllib.parse
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.discord.package import Package

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.permissions import has_permissions
from config import color

from core.discord.views.embed import body, c2

from .proper.ui import (
    SocialRepostView,
    build_profile_container,
    build_social_repost_container,
    get_bot_dominant_color,
    get_dominant_color,
    get_repost_accent_color,
    layout_from_items,
)

from core.networks.media.compress import discord_upload_limit, fit_for_discord
from core.networks.social import Instagram, TikTok, is_instagram_url, is_tiktok_url
from core.networks.social.models import SocialPost

if TYPE_CHECKING:
    from core.vain import Vain

FONT_PATH = str(Path(__file__).resolve().parents[2] / "var" / "caption.otf")

def _ytdlp_download_sync(url: str, output_dir: str) -> dict:
    """Run yt-dlp synchronously to download media."""
    import yt_dlp

    opts: dict = {
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    
    try:
        from config import api as api_cfg

        cookie = api_cfg.instagram.cookie_header()
        if cookie and ("instagram.com" in (url or "") or "instagr.am" in (url or "")):
            opts["http_headers"] = {
                "Cookie": cookie,
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
                    "Instagram 192.0.0.37.107"
                ),
                "X-IG-App-ID": "936619743392459",
            }
    except Exception:
        pass

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            return {}
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            for ext in (".mp4", ".webm", ".mkv", ".jpg", ".png"):
                if os.path.exists(base + ext):
                    filename = base + ext
                    break
        return {
            "filepath": filename,
            "filename": os.path.basename(filename),
            "title": info.get("title", ""),
            "uploader": info.get("uploader", ""),
            "thumbnail": info.get("thumbnail", ""),
        }


class Socials(Package):
    """Social media lookup, reposts, and feed configuration."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._filters = {}
        from .proper.feeds import FeedStore, FeedWatcher

        self.feeds = FeedStore(bot)
        self.watcher = FeedWatcher(bot)

    async def cog_load(self) -> None:
        try:
            self.watcher.start()
        except Exception:
            pass

    async def cog_unload(self) -> None:
        try:
            self.watcher.stop()
        except Exception:
            pass

    async def _send_profile(self, ctx: Context, containers: list) -> None:
        view = layout_from_items(containers, timeout=180)
        await ctx.send(view=view)

    async def _feed_add(
        self,
        ctx: Context,
        platform: str,
        handle: str,
        channel: discord.TextChannel | discord.Thread | None = None,
    ) -> None:
        from .proper.feeds import PLATFORMS, normalize_handle, valid_handle

        if ctx.guild is None:
            await ctx.warn("Feeds can only be configured in a server.")
            return
        uname = normalize_handle(handle)
        if not valid_handle(uname):
            await ctx.warn("Provide a valid username/handle.")
            return
        dest = channel or ctx.channel
        if not isinstance(dest, (discord.TextChannel, discord.Thread)):
            await ctx.warn("Pick a text channel for the feed.")
            return
        try:
            await self.feeds.add(
                platform,
                guild_id=ctx.guild.id,
                channel_id=dest.id,
                username=uname,
                user_id=uname.lower(),
            )
        except ValueError as exc:
            await ctx.warn(str(exc))
            return
        except Exception as exc:
            await ctx.fail(f"Could not save feed: {str(exc)[:120]}")
            return
        label = PLATFORMS.get(platform, {}).get("label", platform.title())
        profile = PLATFORMS.get(platform, {}).get("profile")
        link = profile(uname) if callable(profile) else uname
        await ctx.success(
            f"Tracking **[{label}]({link})** · `@{uname}` → {dest.mention}"
        )

    async def _feed_remove(self, ctx: Context, platform: str, handle: str) -> None:
        from .proper.feeds import PLATFORMS, normalize_handle

        if ctx.guild is None:
            await ctx.warn("Feeds can only be configured in a server.")
            return
        uname = normalize_handle(handle)
        removed = await self.feeds.remove(platform, guild_id=ctx.guild.id, username=uname)
        label = PLATFORMS.get(platform, {}).get("label", platform.title())
        if removed:
            await ctx.success(f"Stopped tracking **@{uname}** on {label}.")
        else:
            await ctx.warn(f"No {label} feed for **@{uname}**.")

    async def _feed_list(self, ctx: Context, platform: str | None = None) -> None:
        from .proper.feeds import PLATFORMS, format_feed_list

        if ctx.guild is None:
            await ctx.warn("Feeds can only be listed in a server.")
            return
        if platform:
            rows = await self.feeds.list(platform, ctx.guild.id)
            body = format_feed_list(platform, rows, ctx.guild)
            title = f"{PLATFORMS.get(platform, {}).get('label', platform)} feeds"
            await ctx.send(embed=c2(color=color.base, title=title, message=body))
            return
        chunks: list[str] = []
        for plat in PLATFORMS:
            rows = await self.feeds.list(plat, ctx.guild.id)
            if not rows:
                continue
            chunks.append(format_feed_list(plat, rows, ctx.guild))
        if not chunks:
            await ctx.send(
                embed=c2(
                    color=color.base,
                    title="Social Feeds",
                    message="No social feeds configured.\n-# Use `,socials <platform> add @user`",
                )
            )
            return
        await ctx.send(
            embed=c2(color=color.base, title="Social Feeds", message="\n\n".join(chunks)[:3900])
        )

    async def _feed_migrate(
        self,
        ctx: Context,
        platform: str,
        source: discord.TextChannel | discord.Thread,
        dest: discord.TextChannel | discord.Thread,
    ) -> None:
        from .proper.feeds import PLATFORMS

        if ctx.guild is None:
            await ctx.warn("Feeds can only be migrated in a server.")
            return
        n = await self.feeds.migrate(
            platform,
            guild_id=ctx.guild.id,
            from_channel_id=source.id,
            to_channel_id=dest.id,
        )
        label = PLATFORMS.get(platform, {}).get("label", platform.title())
        if n:
            await ctx.success(
                f"Moved **{n}** {label} feed(s) from {source.mention} → {dest.mention}."
            )
        else:
            await ctx.warn(f"No {label} feeds in {source.mention}.")

    async def _feed_message(
        self,
        ctx: Context,
        platform: str,
        template: str,
        handle: str | None = None,
    ) -> None:
        from .proper.feeds import PLATFORMS, normalize_handle

        if ctx.guild is None:
            await ctx.warn("Feeds can only be configured in a server.")
            return
        raw = (template or "").strip()
        clear = raw.lower() in {"none", "off", "clear", "remove", "-"}
        n = await self.feeds.set_template(
            platform,
            guild_id=ctx.guild.id,
            template=None if clear else raw,
            username=normalize_handle(handle) if handle else None,
        )
        label = PLATFORMS.get(platform, {}).get("label", platform.title())
        if not n:
            await ctx.warn(f"No {label} feeds matched.")
            return
        if clear:
            await ctx.success(f"Cleared {label} notification template.")
        else:
            await ctx.success(
                f"Set {label} template for **{n}** feed(s).\n-# vars: `{{user}}` `{{url}}` `{{platform}}`"
            )

    async def _media_list_preview(
        self,
        ctx: Context,
        *,
        title: str,
        items: list[dict],
        empty: str,
    ) -> None:
        if not items:
            await ctx.fail(empty)
            return
        lines: list[str] = []
        for i, item in enumerate(items[:12], 1):
            if not isinstance(item, dict):
                continue
            code = (
                item.get("code")
                or item.get("shortcode")
                or item.get("id")
                or item.get("pk")
                or ""
            )
            cap = (
                item.get("caption")
                or item.get("text")
                or item.get("desc")
                or item.get("title")
                or ""
            )
            if isinstance(cap, dict):
                cap = cap.get("text") or ""
            cap = str(cap).replace("\n", " ").strip()[:80]
            label = f"`{code}`" if code else f"#{i}"
            lines.append(f"**{i}.** {label}" + (f" — {cap}" if cap else ""))
        embed = c2(color=color.base, title=title, message="\n".join(lines) or empty)
        await ctx.send(embed=embed)

    
    
    

    @group(
        name="socials",
        description="Configure social media notifications",
        invoke_without_command=True,
        aliases=["social"],
    )
    @has_permissions(manage_guild=True)
    async def socials(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @socials.command(name="twitter", description="Follow or unfollow an X account", aliases=["x"])
    @describe(action="add or remove", handle="X handle (without @)")
    @has_permissions(manage_guild=True)
    async def socials_twitter(self, ctx: Context, action: str, *, handle: str) -> None:
        act = action.lower().strip()
        if act in ("add", "follow", "set", "watch"):
            await self._feed_add(ctx, "twitter", handle)
        elif act in ("remove", "unfollow", "del", "delete", "rm"):
            await self._feed_remove(ctx, "twitter", handle)
        elif act in ("list", "show"):
            await self._feed_list(ctx, "twitter")
        else:
            await ctx.warn("Use `add`, `remove`, or `list`.")

    @socials.command(name="twitch", description="Follow or unfollow a Twitch channel")
    @describe(action="add or remove", channel="Twitch channel name")
    @has_permissions(manage_guild=True)
    async def socials_twitch(self, ctx: Context, action: str, *, channel: str) -> None:
        act = action.lower().strip()
        if act in ("add", "follow", "set", "watch"):
            await self._feed_add(ctx, "twitch", channel)
        elif act in ("remove", "unfollow", "del", "delete", "rm"):
            await self._feed_remove(ctx, "twitch", channel)
        elif act in ("list", "show"):
            await self._feed_list(ctx, "twitch")
        else:
            await ctx.warn("Use `add`, `remove`, or `list`.")

    @socials.command(name="youtube", description="Follow or unfollow a YouTube channel", aliases=["yt"])
    @describe(action="add or remove", channel="YouTube channel name or ID")
    @has_permissions(manage_guild=True)
    async def socials_youtube(self, ctx: Context, action: str, *, channel: str) -> None:
        act = action.lower().strip()
        if act in ("add", "follow", "set", "watch"):
            await self._feed_add(ctx, "youtube", channel)
        elif act in ("remove", "unfollow", "del", "delete", "rm"):
            await self._feed_remove(ctx, "youtube", channel)
        elif act in ("list", "show"):
            await self._feed_list(ctx, "youtube")
        else:
            await ctx.warn("Use `add`, `remove`, or `list`.")

    @socials.command(name="tiktok", description="Follow or unfollow a TikTok account for feed")
    @describe(action="add or remove", username="TikTok username")
    @has_permissions(manage_guild=True)
    async def socials_tiktok(self, ctx: Context, action: str, *, username: str) -> None:
        act = action.lower().strip()
        if act in ("add", "follow", "set", "watch"):
            await self._feed_add(ctx, "tiktok", username)
        elif act in ("remove", "unfollow", "del", "delete", "rm"):
            await self._feed_remove(ctx, "tiktok", username)
        elif act in ("list", "show"):
            await self._feed_list(ctx, "tiktok")
        else:
            await ctx.warn("Use `add`, `remove`, or `list`.")

    @socials.command(name="instagram", description="Follow or unfollow an Instagram account for feed", aliases=["ig"])
    @describe(action="add or remove", username="Instagram username")
    @has_permissions(manage_guild=True)
    async def socials_instagram(self, ctx: Context, action: str, *, username: str) -> None:
        act = action.lower().strip()
        if act in ("add", "follow", "set", "watch"):
            await self._feed_add(ctx, "instagram", username)
        elif act in ("remove", "unfollow", "del", "delete", "rm"):
            await self._feed_remove(ctx, "instagram", username)
        elif act in ("list", "show"):
            await self._feed_list(ctx, "instagram")
        else:
            await ctx.warn("Use `add`, `remove`, or `list`.")

    @socials.command(name="pinterest", description="Follow or unfollow a Pinterest profile", aliases=["pin"])
    @describe(action="add or remove", username="Pinterest username")
    @has_permissions(manage_guild=True)
    async def socials_pinterest(self, ctx: Context, action: str, *, username: str) -> None:
        act = action.lower().strip()
        if act in ("add", "follow", "set", "watch"):
            await self._feed_add(ctx, "pinterest", username)
        elif act in ("remove", "unfollow", "del", "delete", "rm"):
            await self._feed_remove(ctx, "pinterest", username)
        elif act in ("list", "show"):
            await self._feed_list(ctx, "pinterest")
        else:
            await ctx.warn("Use `add`, `remove`, or `list`.")

    @socials.command(name="snapchat", description="Follow or unfollow a Snapchat profile", aliases=["snap"])
    @describe(action="add or remove", username="Snapchat username")
    @has_permissions(manage_guild=True)
    async def socials_snapchat(self, ctx: Context, action: str, *, username: str) -> None:
        act = action.lower().strip()
        if act in ("add", "follow", "set", "watch"):
            await self._feed_add(ctx, "snapchat", username)
        elif act in ("remove", "unfollow", "del", "delete", "rm"):
            await self._feed_remove(ctx, "snapchat", username)
        elif act in ("list", "show"):
            await self._feed_list(ctx, "snapchat")
        else:
            await ctx.warn("Use `add`, `remove`, or `list`.")

    @socials.command(name="list", description="View all configured social feeds", aliases=["all"])
    @has_permissions(manage_guild=True)
    async def socials_list(self, ctx: Context) -> None:
        await self._feed_list(ctx, None)

    @socials.command(name="migrate", description="Move feeds from one channel to another")
    @describe(platform="Platform name", source="Current channel", destination="New channel")
    @has_permissions(manage_guild=True)
    async def socials_migrate(
        self,
        ctx: Context,
        platform: str,
        source: discord.TextChannel,
        destination: discord.TextChannel,
    ) -> None:
        plat = platform.lower().strip()
        if plat == "x":
            plat = "twitter"
        from .proper.feeds import PLATFORMS

        if plat not in PLATFORMS:
            await ctx.warn("Platforms: " + ", ".join(sorted(PLATFORMS)))
            return
        await self._feed_migrate(ctx, plat, source, destination)

    @socials.command(name="message", description="Set a custom feed notification template", aliases=["template", "msg"])
    @describe(platform="Platform name", template="Template text, or `none` to clear")
    @has_permissions(manage_guild=True)
    async def socials_message(self, ctx: Context, platform: str, *, template: str) -> None:
        plat = platform.lower().strip()
        if plat == "x":
            plat = "twitter"
        from .proper.feeds import PLATFORMS

        if plat not in PLATFORMS:
            await ctx.warn("Platforms: " + ", ".join(sorted(PLATFORMS)))
            return
        await self._feed_message(ctx, plat, template)

    
    
    

    @hybrid(
        name="instagram",
        description="Instagram profiles, posts, stories & highlights",
        aliases=["ig"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(username="Instagram username")
    async def instagram(self, ctx: Context, *, username: str | None = None) -> None:
        if not username:
            await ctx.send_help(ctx.command)
            return
        await ctx.invoke(self.instagram_user, username=username)

    @instagram.command(name="user", description="Look up an Instagram profile", aliases=["profile", "p"])
    @describe(username="Instagram username")
    async def instagram_user(self, ctx: Context, *, username: str) -> None:
        from .proper.api import instagram_user as api_user, parse_instagram_user

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            raw = await api_user(uname)
            data = parse_instagram_user(raw or {}, username=uname)
            if not data:
                
                client = Instagram()
                try:
                    prof = await client.profile(uname)
                finally:
                    await client.close()
                if not prof:
                    await ctx.fail(f"Could not find Instagram user `{uname}`.")
                    return
                data = {
                    "username": prof.get("username") or uname,
                    "full_name": prof.get("full_name") or uname,
                    "bio": prof.get("biography") or "",
                    "followers": int(prof.get("follower_count") or 0),
                    "following": int(prof.get("following_count") or 0),
                    "posts": int(prof.get("media_count") or 0),
                    "is_private": bool(prof.get("is_private")),
                    "is_verified": bool(prof.get("is_verified")),
                    "avatar": prof.get("profile_pic_url_hd") or prof.get("profile_pic_url") or "",
                }
            accent = await get_repost_accent_color(
                self.bot, avatar_url=data.get("avatar") or None, platform="instagram"
            )
            containers = build_profile_container(
                platform="instagram",
                username=data["username"],
                display_name=data.get("full_name") or data["username"],
                bio=data.get("bio") or "",
                avatar_url=data.get("avatar") or None,
                followers=int(data.get("followers") or 0),
                following=int(data.get("following") or 0),
                posts=int(data.get("posts") or 0),
                is_private=bool(data.get("is_private")),
                is_verified=bool(data.get("is_verified")),
                accent=accent,
            )
            await self._send_profile(ctx, containers)

    @instagram.command(name="repost", description="Repost an Instagram post or reel", aliases=["post", "reel"])
    @describe(url="Instagram post/reel URL")
    async def instagram_repost(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                await self._repost(ctx, url)
            except Exception as e:
                await ctx.fail(f"Repost failed: {str(e)[:150]}")

    @instagram.command(name="stories", description="List active Instagram stories", aliases=["story"])
    @describe(username="Instagram username")
    async def instagram_stories(self, ctx: Context, *, username: str) -> None:
        from .proper.api import instagram_user_stories

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            items = await instagram_user_stories(uname)
            await self._media_list_preview(
                ctx,
                title=f"Instagram stories · @{uname}",
                items=items,
                empty=f"No stories for `@{uname}` (private or empty).",
            )

    @instagram.command(name="highlights", description="List Instagram highlight reels", aliases=["highlight", "hl"])
    @describe(username="Instagram username")
    async def instagram_highlights(self, ctx: Context, *, username: str) -> None:
        from .proper.api import instagram_user_highlights

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            items = await instagram_user_highlights(uname)
            await self._media_list_preview(
                ctx,
                title=f"Instagram highlights · @{uname}",
                items=items,
                empty=f"No highlights for `@{uname}`.",
            )

    @instagram.command(name="trending", description="Instagram trending posts", aliases=["explore"])
    @describe(count="How many posts (1-12)")
    async def instagram_trending(self, ctx: Context, count: int = 4) -> None:
        from .proper.api import instagram_trending, parse_instagram_post

        async with ctx.typing():
            items = await instagram_trending(count=max(1, min(int(count or 4), 12)))
            if not items:
                await ctx.fail("No trending posts right now.")
                return
            lines = []
            for i, raw in enumerate(items[:12], 1):
                post = parse_instagram_post(raw) if isinstance(raw, dict) else None
                if post:
                    lines.append(
                        f"**{i}.** [@{post.username}]({post.url}) — {(post.caption or '')[:70]}"
                    )
                else:
                    lines.append(f"**{i}.** post")
            await ctx.send(embed=c2(color=color.base, title="Instagram trending", message="\n".join(lines)))

    @instagram.command(name="posts", description="Recent posts from an Instagram user")
    @describe(username="Instagram username", count="How many posts (1-24)")
    async def instagram_posts(self, ctx: Context, username: str, count: int = 12) -> None:
        from .proper.api import instagram_user_posts

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            items = await instagram_user_posts(uname, count=max(1, min(int(count or 12), 24)))
            await self._media_list_preview(
                ctx,
                title=f"Instagram posts · @{uname}",
                items=items,
                empty=f"No posts for `@{uname}`.",
            )

    @instagram.group(
        name="reposter",
        description="Instagram auto-reposter settings",
        invoke_without_command=True,
        aliases=["auto"],
    )
    @has_permissions(manage_guild=True)
    async def instagram_reposter(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @instagram_reposter.command(name="toggle", description="Toggle Instagram link auto-repost in this guild")
    @has_permissions(manage_guild=True)
    async def instagram_reposter_toggle(self, ctx: Context) -> None:
        
        key = f"ig_reposter:{getattr(ctx.guild, 'id', 0)}"
        cur = bool(self._filters.get(key))
        self._filters[key] = not cur
        state = "enabled" if not cur else "disabled"
        await ctx.success(f"Instagram auto-reposter **{state}** for this server.")

    @instagram_reposter.command(name="prefix", description="Set optional prefix required before IG links to auto-repost")
    @describe(prefix="Prefix text, or `none` to clear")
    @has_permissions(manage_guild=True)
    async def instagram_reposter_prefix(self, ctx: Context, *, prefix: str = "none") -> None:
        key = f"ig_reposter_prefix:{getattr(ctx.guild, 'id', 0)}"
        if prefix.strip().lower() in {"none", "off", "clear", "-"}:
            self._filters.pop(key, None)
            await ctx.success("Instagram auto-reposter prefix cleared.")
            return
        self._filters[key] = prefix.strip()
        await ctx.success(f"Instagram auto-reposter prefix set to `{prefix.strip()}`.")

    
    
    

    @hybrid(
        name="tiktok",
        description="TikTok profiles, posts, FYP & downloads",
        aliases=["tt"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(query="TikTok username or post URL")
    async def tiktok(self, ctx: Context, *, query: str | None = None) -> None:
        if not query:
            await ctx.send_help(ctx.command)
            return
        q = query.strip()
        if is_tiktok_url(q) or "vm.tiktok" in q or "vt.tiktok" in q or "/video/" in q:
            await ctx.invoke(self.tiktok_repost, url=q)
            return
        await ctx.invoke(self.tiktok_user, username=q)

    @tiktok.command(name="user", description="Look up a TikTok profile", aliases=["profile", "p"])
    @describe(username="TikTok username")
    async def tiktok_user(self, ctx: Context, *, username: str) -> None:
        from .proper.api import parse_tiktok_user, tiktok_user as api_user

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            data = None
            raw = await api_user(uname)
            if isinstance(raw, dict) and raw:
                data = parse_tiktok_user(raw, username=uname)
                # If stats are all zero but the API payload has counters, re-parse flat.
                if data and not any(
                    int(data.get(k) or 0)
                    for k in ("followerCount", "followingCount", "heartCount", "videoCount")
                ):
                    flat = parse_tiktok_user(
                        {
                            **raw,
                            "followers": raw.get("followers", raw.get("followerCount")),
                            "following": raw.get("following", raw.get("followingCount")),
                            "likes": raw.get("likes", raw.get("heart_count", raw.get("heartCount"))),
                            "videos": raw.get("videos", raw.get("videoCount")),
                        },
                        username=uname,
                    )
                    if flat:
                        data = flat
            if not data:
                client = TikTok()
                try:
                    data = await client.user(uname)
                finally:
                    await client.close()
            if not data:
                await ctx.fail(f"Could not find TikTok user `@{uname}`.")
                return

            if "uniqueId" not in data:
                data = {
                    "uniqueId": data.get("username") or data.get("unique_id") or uname,
                    "nickname": data.get("nickname") or data.get("display_name") or uname,
                    "avatarLarger": data.get("avatar") or data.get("avatarLarger") or data.get("avatar_larger") or "",
                    "signature": data.get("signature") or data.get("bio") or "",
                    "followerCount": int(
                        data.get("followerCount")
                        if data.get("followerCount") is not None
                        else data.get("followers") or 0
                    ),
                    "followingCount": int(
                        data.get("followingCount")
                        if data.get("followingCount") is not None
                        else data.get("following") or 0
                    ),
                    "heartCount": int(
                        data.get("heartCount")
                        if data.get("heartCount") is not None
                        else data.get("likes") or data.get("heart_count") or 0
                    ),
                    "videoCount": int(
                        data.get("videoCount")
                        if data.get("videoCount") is not None
                        else data.get("videos") or 0
                    ),
                    "verified": bool(data.get("verified")),
                    "is_private": bool(
                        data.get("is_private")
                        or data.get("private")
                        or data.get("private_account")
                        or data.get("privateAccount")
                        or data.get("secret")
                    ),
                }
            avatar = data.get("avatarLarger") or data.get("avatar") or ""
            accent = await get_repost_accent_color(
                self.bot, avatar_url=avatar or None, platform="tiktok"
            )
            containers = build_profile_container(
                platform="tiktok",
                username=data.get("uniqueId") or uname,
                display_name=data.get("nickname") or uname,
                bio=data.get("signature") or "",
                avatar_url=avatar or None,
                followers=int(data.get("followerCount") or 0),
                following=int(data.get("followingCount") or 0),
                likes=int(data.get("heartCount") or 0),
                posts=int(data.get("videoCount") or 0),
                is_private=bool(
                    data.get("is_private")
                    or data.get("privateAccount")
                    or data.get("private_account")
                    or data.get("secret")
                ),
                is_verified=bool(data.get("verified")),
                accent=accent,
            )
            await self._send_profile(ctx, containers)

    @tiktok.command(name="repost", description="Repost a TikTok video or photo set", aliases=["post", "video"])
    @describe(url="TikTok post URL")
    async def tiktok_repost(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                await self._repost(ctx, url)
            except Exception as e:
                await ctx.fail(f"Repost failed: {str(e)[:150]}")

    @tiktok.command(name="download", description="Download a TikTok video by URL", aliases=["dl", "get"])
    @describe(url="TikTok post URL")
    async def tiktok_download(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                loop = asyncio.get_running_loop()
                with tempfile.TemporaryDirectory(prefix="tiktok-") as tmp:
                    result = await loop.run_in_executor(None, _ytdlp_download_sync, url, tmp)
                    if not result or not result.get("filepath"):
                        await ctx.fail("Could not download that TikTok video.")
                        return
                    filepath = result["filepath"]
                    if not os.path.exists(filepath):
                        await ctx.fail("Downloaded file not found.")
                        return
                    if os.path.getsize(filepath) > 100 * 1024 * 1024:
                        await ctx.fail("File is too large to process.")
                        return
                    with open(filepath, "rb") as f:
                        data = f.read()
                    filename = result.get("filename", "tiktok.mp4")
                    file = await self._prepare_file(ctx, data, filename=filename)
                    if file is None:
                        return
                    await ctx.send(file=file)
            except Exception as e:
                await ctx.fail(f"Download failed: {str(e)[:200]}")

    @tiktok.command(name="info", description="Get information about a TikTok video", aliases=["details"])
    @describe(url="TikTok post URL")
    async def tiktok_info(self, ctx: Context, *, url: str) -> None:
        client = TikTok()
        try:
            post = await client.post(url)
        finally:
            await client.close()
        if not post:
            await ctx.fail("Could not fetch that TikTok.")
            return
        lines = [
            f"**Author:** [{post.display_name}]({post.profile_url}) (@{post.username})",
            f"**Likes:** `{post.like_count:,}` · **Comments:** `{post.comment_count:,}`",
            f"**Shares:** `{post.share_count:,}` · **Saves:** `{post.save_count:,}`",
        ]
        if post.play_count:
            lines.append(f"**Plays:** `{post.play_count:,}`")
        if post.music_title:
            lines.append(f"**Music:** {post.music_title}")
        if post.caption:
            lines.append(f"**Caption:** {post.caption[:300]}")
        embed = c2(color=color.base, title="TikTok Video", message="\n".join(lines))
        if post.avatar_url:
            embed.set_thumbnail(url=post.avatar_url)
        await ctx.send(embed=embed)

    @tiktok.command(name="fyp", description="TikTok For You sample", aliases=["feed"])
    @describe(limit="How many posts (1-12)", region="Optional 2-letter region")
    async def tiktok_fyp(self, ctx: Context, limit: int = 8, region: str | None = None) -> None:
        from .proper.api import parse_tiktok_post, tiktok_fyp

        async with ctx.typing():
            items = await tiktok_fyp(limit=max(1, min(int(limit or 8), 12)), region=region)
            if not items:
                await ctx.fail("FYP unavailable right now.")
                return
            lines = []
            for i, raw in enumerate(items[:12], 1):
                post = parse_tiktok_post(raw) if isinstance(raw, dict) else None
                if post:
                    lines.append(f"**{i}.** [@{post.username}]({post.url}) — {(post.caption or '')[:70]}")
                else:
                    lines.append(f"**{i}.** post")
            await ctx.send(embed=c2(color=color.base, title="TikTok FYP", message="\n".join(lines)))

    @tiktok.command(name="posts", description="Recent posts from a TikTok user")
    @describe(username="TikTok username", limit="How many (1-20)")
    async def tiktok_posts(self, ctx: Context, username: str, limit: int = 12) -> None:
        from .proper.api import tiktok_user_posts

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            items = await tiktok_user_posts(uname, limit=max(1, min(int(limit or 12), 20)))
            await self._media_list_preview(
                ctx,
                title=f"TikTok posts · @{uname}",
                items=items,
                empty=f"No posts for `@{uname}`.",
            )

    
    
    

    @hybrid(
        name="x",
        description="X (Twitter) profiles and posts",
        aliases=["twitter", "twt"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(query="X handle or status URL")
    async def x(self, ctx: Context, *, query: str | None = None) -> None:
        if not query:
            await ctx.send_help(ctx.command)
            return
        q = query.strip()
        if "status/" in q or re.search(r"(?:x|twitter)\.com/.+/status/\d+", q, re.I):
            await ctx.invoke(self.x_repost, url=q)
            return
        await ctx.invoke(self.x_user, username=q)

    @x.command(name="user", description="Look up an X profile", aliases=["profile", "p"])
    @describe(username="X handle")
    async def x_user(self, ctx: Context, *, username: str) -> None:
        from .proper.api import parse_twitter_user, twitter_user

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            raw = await twitter_user(uname)
            data = parse_twitter_user(raw or {}, username=uname)
            if not data:
                await ctx.fail(f"Could not find X user `@{uname}`.")
                return
            accent = await get_repost_accent_color(
                self.bot, avatar_url=data.get("avatar") or None, platform="twitter"
            )
            containers = build_profile_container(
                platform="twitter",
                username=data["username"],
                display_name=data.get("name") or data["username"],
                bio=data.get("bio") or "",
                avatar_url=data.get("avatar") or None,
                followers=int(data.get("followers") or 0),
                following=int(data.get("following") or 0),
                posts=int(data.get("statuses") or 0) or None,
                likes=int(data.get("likes") or 0) if data.get("likes") else None,
                is_private=bool(data.get("is_private")),
                is_verified=bool(data.get("is_verified")),
                accent=accent,
            )
            await self._send_profile(ctx, containers)

    @x.command(name="repost", description="Repost an X status", aliases=["post", "status", "tweet"])
    @describe(url="X/Twitter status URL")
    async def x_repost(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                await self._repost(ctx, url)
            except Exception as e:
                await ctx.fail(f"Repost failed: {str(e)[:150]}")

    @x.command(name="tweets", description="Recent tweets from a user", aliases=["posts"])
    @describe(username="X handle")
    async def x_tweets(self, ctx: Context, *, username: str) -> None:
        from .proper.api import twitter_user_tweets

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            items = await twitter_user_tweets(uname)
            await self._media_list_preview(
                ctx,
                title=f"X posts · @{uname}",
                items=items,
                empty=f"No tweets for `@{uname}`.",
            )

    
    
    

    @hybrid(
        name="youtube",
        description="YouTube channels, videos & shorts",
        aliases=["yt"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(query="Channel handle, video URL, or shorts URL")
    async def youtube(self, ctx: Context, *, query: str | None = None) -> None:
        if not query:
            await ctx.send_help(ctx.command)
            return
        q = query.strip()
        if "youtu" in q.lower() and (
            "watch" in q or "shorts" in q or "youtu.be" in q.lower()
        ):
            await ctx.invoke(self.youtube_repost, url=q)
            return
        await ctx.invoke(self.youtube_user, channel=q)

    @youtube.command(name="user", description="Look up a YouTube channel", aliases=["channel", "c", "profile"])
    @describe(channel="Channel handle or ID")
    async def youtube_user(self, ctx: Context, *, channel: str) -> None:
        from .proper.api import parse_youtube_channel, youtube_channel

        ch = channel.strip().lstrip("@")
        async with ctx.typing():
            raw = await youtube_channel(ch)
            data = parse_youtube_channel(raw or {}, channel=ch)
            if not data:
                await ctx.fail(f"Could not find YouTube channel `{ch}`.")
                return
            accent = await get_repost_accent_color(
                self.bot, avatar_url=data.get("avatar") or None, platform="youtube"
            )
            extras = []
            if data.get("views"):
                extras.append(("Views", int(data["views"])))
            if data.get("videos"):
                extras.append(("Videos", int(data["videos"])))
            containers = build_profile_container(
                platform="youtube",
                username=data.get("handle") or ch,
                display_name=data.get("name") or ch,
                bio=data.get("description") or "",
                avatar_url=data.get("avatar") or None,
                profile_url=data.get("url") or None,
                followers=int(data.get("subscribers") or 0),
                following=0,
                extra_stats=extras or None,
                is_verified=bool(data.get("is_verified")),
                accent=accent,
            )
            
            
            await self._send_profile(ctx, containers)

    @youtube.command(name="repost", description="Repost a YouTube video or short", aliases=["video", "short"])
    @describe(url="YouTube video or shorts URL")
    async def youtube_repost(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                await self._repost(ctx, url)
            except Exception as e:
                await ctx.fail(f"Repost failed: {str(e)[:150]}")

    @youtube.command(name="shorts", description="Recent shorts from a channel")
    @describe(channel="Channel handle", limit="How many (1-20)")
    async def youtube_shorts(self, ctx: Context, channel: str, limit: int = 10) -> None:
        from .proper.api import youtube_channel_shorts

        ch = channel.strip().lstrip("@")
        async with ctx.typing():
            items = await youtube_channel_shorts(ch, limit=max(1, min(int(limit or 10), 20)))
            await self._media_list_preview(
                ctx,
                title=f"YouTube shorts · @{ch}",
                items=items,
                empty=f"No shorts for `{ch}`.",
            )

    @youtube.command(name="videos", description="Recent videos from a channel")
    @describe(channel="Channel handle", limit="How many (1-20)")
    async def youtube_videos(self, ctx: Context, channel: str, limit: int = 10) -> None:
        from .proper.api import youtube_channel_videos

        ch = channel.strip().lstrip("@")
        async with ctx.typing():
            items = await youtube_channel_videos(ch, limit=max(1, min(int(limit or 10), 20)))
            await self._media_list_preview(
                ctx,
                title=f"YouTube videos · @{ch}",
                items=items,
                empty=f"No videos for `{ch}`.",
            )

    
    
    

    @hybrid(
        name="telegram",
        description="Telegram users and channels",
        aliases=["tg"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(username="Telegram username")
    async def telegram(self, ctx: Context, *, username: str | None = None) -> None:
        if not username:
            await ctx.send_help(ctx.command)
            return
        await ctx.invoke(self.telegram_user, username=username)

    @telegram.command(name="user", description="Look up a Telegram user", aliases=["profile", "p"])
    @describe(username="Telegram username")
    async def telegram_user(self, ctx: Context, *, username: str) -> None:
        from .proper.api import parse_telegram_user, telegram_user as api_user

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            raw = await api_user(uname)
            data = parse_telegram_user(raw or {}, username=uname)
            if not data:
                await ctx.fail(f"Could not find Telegram user `@{uname}`.")
                return
            accent = await get_repost_accent_color(
                self.bot, avatar_url=data.get("avatar") or None, platform="telegram"
            )
            extras = []
            if data.get("is_bot"):
                extras.append(("Bot", "yes"))
            if data.get("is_premium"):
                extras.append(("Premium", "yes"))
            containers = build_profile_container(
                platform="telegram",
                username=data.get("username") or uname,
                display_name=data.get("name") or uname,
                bio=data.get("bio") or "",
                avatar_url=data.get("avatar") or None,
                followers=0,
                following=0,
                extra_stats=extras or None,
                is_verified=bool(data.get("is_verified")),
                accent=accent,
            )
            await self._send_profile(ctx, containers)

    @telegram.command(name="channel", description="Look up a Telegram channel", aliases=["ch"])
    @describe(username="Channel username")
    async def telegram_channel(self, ctx: Context, *, username: str) -> None:
        from .proper.api import parse_telegram_channel, telegram_channel as api_ch

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            raw = await api_ch(uname)
            data = parse_telegram_channel(raw or {}, username=uname)
            if not data:
                await ctx.fail(f"Could not find Telegram channel `@{uname}`.")
                return
            accent = await get_repost_accent_color(
                self.bot, avatar_url=data.get("avatar") or None, platform="telegram"
            )
            containers = build_profile_container(
                platform="telegram",
                username=data.get("username") or uname,
                display_name=data.get("name") or uname,
                bio=data.get("bio") or "",
                avatar_url=data.get("avatar") or None,
                followers=int(data.get("members") or 0),
                following=0,
                is_private=bool(data.get("is_private")),
                is_verified=bool(data.get("is_verified")),
                accent=accent,
            )
            await self._send_profile(ctx, containers)

    
    
    

    @hybrid(
        name="twitch",
        description="Twitch profiles, live status & videos",
        aliases=["ttv"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(username="Twitch login")
    async def twitch(self, ctx: Context, *, username: str | None = None) -> None:
        if not username:
            await ctx.send_help(ctx.command)
            return
        await ctx.invoke(self.twitch_user, username=username)

    @twitch.command(name="user", description="Look up a Twitch profile", aliases=["profile", "p"])
    @describe(username="Twitch login")
    async def twitch_user(self, ctx: Context, *, username: str) -> None:
        from .proper.api import parse_twitch_user, twitch_user as api_user

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            raw = await api_user(uname)
            data = parse_twitch_user(raw or {}, username=uname)
            if not data:
                await ctx.fail(f"Could not find Twitch user `{uname}`.")
                return
            accent = await get_repost_accent_color(
                self.bot, avatar_url=data.get("avatar") or None, platform="twitch"
            )
            extras: list[tuple[str, int | str]] = []
            if data.get("is_live"):
                extras.append(("Live", "yes"))
                if data.get("stream_title"):
                    extras.append(("Title", str(data["stream_title"])[:80]))
                if data.get("game"):
                    extras.append(("Game", str(data["game"])[:40]))
                if data.get("viewers"):
                    extras.append(("Viewers", int(data["viewers"])))
            if data.get("is_partner"):
                extras.append(("Partner", "yes"))
            containers = build_profile_container(
                platform="twitch",
                username=data.get("username") or uname,
                display_name=data.get("display_name") or uname,
                bio=data.get("bio") or "",
                avatar_url=data.get("avatar") or None,
                profile_url=data.get("url") or None,
                followers=int(data.get("followers") or 0),
                following=0,
                extra_stats=extras or None,
                is_verified=bool(data.get("is_partner")),
                accent=accent,
            )
            await self._send_profile(ctx, containers)

    @twitch.command(name="live", description="Check if a Twitch channel is live")
    @describe(username="Twitch login")
    async def twitch_live(self, ctx: Context, *, username: str) -> None:
        from .proper.api import parse_twitch_user, twitch_live, twitch_user as api_user

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            live = await twitch_live(uname)
            raw = live or await api_user(uname)
            data = parse_twitch_user(raw or {}, username=uname) if raw else None
            if not data and not live:
                await ctx.fail(f"Could not check Twitch live for `{uname}`.")
                return
            is_live = bool(
                (data or {}).get("is_live")
                or (isinstance(live, dict) and (live.get("is_live") or (live.get("stream") or {}).get("type") == "live"))
            )
            title = (data or {}).get("stream_title") or ""
            game = (data or {}).get("game") or ""
            viewers = (data or {}).get("viewers") or 0
            if is_live:
                bits = [f"**@{uname}** is **live**"]
                if title:
                    bits.append(str(title)[:200])
                if game:
                    bits.append(f"Playing **{game}**")
                if viewers:
                    bits.append(f"`{viewers}` watching")
                await ctx.send(
                    embed=c2(
                        color=color.base,
                        title="Twitch Live",
                        message="\n".join(bits),
                        footer=f"https://www.twitch.tv/{uname}",
                    )
                )
            else:
                await ctx.send(
                    embed=c2(
                        color=color.base,
                        title="Twitch Live",
                        message=f"**@{uname}** is offline.",
                    )
                )

    @twitch.command(name="videos", description="Recent Twitch videos / VODs")
    @describe(username="Twitch login")
    async def twitch_videos(self, ctx: Context, *, username: str) -> None:
        from .proper.api import twitch_videos

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            items = await twitch_videos(uname)
            await self._media_list_preview(
                ctx,
                title=f"Twitch videos · {uname}",
                items=items,
                empty=f"No videos for `{uname}`.",
            )

    @hybrid(
        name="snapchat",
        description="Snapchat public profiles",
        aliases=["snap"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(username="Snapchat username")
    async def snapchat(self, ctx: Context, *, username: str | None = None) -> None:
        if not username:
            await ctx.send_help(ctx.command)
            return
        await ctx.invoke(self.snapchat_user, username=username)

    @snapchat.command(name="user", description="Look up a Snapchat profile", aliases=["profile", "p"])
    @describe(username="Snapchat username")
    async def snapchat_user(self, ctx: Context, *, username: str) -> None:
        from .proper.api import parse_snapchat_user, snapchat_user as api_user

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            raw = await api_user(uname)
            data = parse_snapchat_user(raw or {}, username=uname)
            if not data:
                await ctx.fail(f"Could not find Snapchat user `@{uname}`.")
                return
            accent = await get_repost_accent_color(
                self.bot, avatar_url=data.get("avatar") or None, platform="snapchat"
            )
            extras: list[tuple[str, int | str]] = []
            if data.get("subscribers"):
                extras.append(("Subscribers", int(data["subscribers"])))
            if data.get("has_story"):
                extras.append(("Story", "active"))
            containers = build_profile_container(
                platform="snapchat",
                username=data.get("username") or uname,
                display_name=data.get("name") or uname,
                bio=data.get("bio") or "",
                avatar_url=data.get("avatar") or None,
                profile_url=data.get("url") or None,
                followers=int(data.get("subscribers") or 0),
                following=0,
                extra_stats=extras or None,
                is_verified=bool(data.get("is_verified")),
                accent=accent,
            )
            await self._send_profile(ctx, containers)

    @hybrid(
        name="pinterest",
        description="Pinterest profiles, pins & search",
        aliases=["pin"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(query="Username or pin URL")
    async def pinterest(self, ctx: Context, *, query: str | None = None) -> None:
        if not query:
            await ctx.send_help(ctx.command)
            return
        q = query.strip()
        if "pinterest." in q.lower() and ("/pin/" in q.lower() or q.startswith("http")):
            await ctx.invoke(self.pinterest_repost, url=q)
            return
        await ctx.invoke(self.pinterest_user, username=q)

    @pinterest.command(name="user", description="Look up a Pinterest profile", aliases=["profile", "p"])
    @describe(username="Pinterest username")
    async def pinterest_user(self, ctx: Context, *, username: str) -> None:
        from .proper.api import parse_pinterest_user, pinterest_user as api_user

        uname = username.strip().lstrip("@")
        async with ctx.typing():
            raw = await api_user(uname)
            data = parse_pinterest_user(raw or {}, username=uname)
            if not data:
                await ctx.fail(f"Could not find Pinterest user `@{uname}`.")
                return
            accent = await get_repost_accent_color(
                self.bot, avatar_url=data.get("avatar") or None, platform="pinterest"
            )
            extras: list[tuple[str, int | str]] = []
            if data.get("pins"):
                extras.append(("Pins", int(data["pins"])))
            if data.get("boards"):
                extras.append(("Boards", int(data["boards"])))
            containers = build_profile_container(
                platform="pinterest",
                username=data.get("username") or uname,
                display_name=data.get("name") or uname,
                bio=data.get("bio") or "",
                avatar_url=data.get("avatar") or None,
                profile_url=data.get("url") or None,
                followers=int(data.get("followers") or 0),
                following=int(data.get("following") or 0),
                extra_stats=extras or None,
                is_private=bool(data.get("is_private")),
                is_verified=bool(data.get("is_verified")),
                accent=accent,
            )
            await self._send_profile(ctx, containers)

    @pinterest.command(name="repost", description="Repost a Pinterest pin", aliases=["pin"])
    @describe(url="Pinterest pin URL or id")
    async def pinterest_repost(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                await self._repost(ctx, url)
            except Exception as e:
                await ctx.fail(f"Repost failed: {str(e)[:150]}")

    @pinterest.command(name="search", description="Search Pinterest pins")
    @describe(query="Search query", limit="How many (1-12)")
    async def pinterest_search(self, ctx: Context, query: str, limit: int = 8) -> None:
        from .proper.api import parse_pinterest_pin, pinterest_search

        async with ctx.typing():
            items = await pinterest_search(query, limit=max(1, min(int(limit or 8), 12)))
            if not items:
                await ctx.fail("No pins found.")
                return
            lines = []
            for i, raw in enumerate(items[:12], 1):
                post = parse_pinterest_pin(raw) if isinstance(raw, dict) else None
                if post:
                    lines.append(
                        f"**{i}.** [@{post.username}]({post.url}) — {(post.caption or '')[:70]}"
                    )
                else:
                    title = ""
                    if isinstance(raw, dict):
                        title = str(raw.get("title") or raw.get("grid_title") or "")[:70]
                    lines.append(f"**{i}.** {title or 'pin'}")
            await ctx.send(
                embed=c2(color=color.base, title=f"Pinterest · {query}", message="\n".join(lines))
            )

    @hybrid(
        name="brave",
        description="Brave search & page scrape",
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(query="Search query")
    async def brave(self, ctx: Context, *, query: str | None = None) -> None:
        if not query:
            await ctx.send_help(ctx.command)
            return
        await ctx.invoke(self.brave_search, query=query)

    @brave.command(name="search", description="Search the web via Brave", aliases=["s", "q"])
    @describe(query="Search query")
    async def brave_search(self, ctx: Context, *, query: str) -> None:
        from .proper.api import brave_search, parse_search_results

        async with ctx.typing():
            raw = await brave_search(query, count=8)
            results = parse_search_results(raw)
            if not results:
                await ctx.fail("No Brave results.")
                return
            lines = []
            for i, r in enumerate(results[:8], 1):
                title = r.get("title") or r.get("url") or "result"
                url = r.get("url") or ""
                snip = (r.get("snippet") or "")[:90]
                if url:
                    lines.append(f"**{i}.** [{title}]({url})" + (f"\n> {snip}" if snip else ""))
                else:
                    lines.append(f"**{i}.** {title}")
            await ctx.send(
                embed=c2(color=color.base, title=f"Brave · {query[:80]}", message="\n".join(lines))
            )

    @brave.command(name="scrape", description="Scrape a URL via Brave")
    @describe(url="Page URL")
    async def brave_scrape(self, ctx: Context, *, url: str) -> None:
        from .proper.api import brave_scrape

        async with ctx.typing():
            data = await brave_scrape(url.strip())
            if not data:
                await ctx.fail("Could not scrape that URL.")
                return
            title = str(data.get("title") or data.get("name") or "Page")[:120]
            text = str(
                data.get("text")
                or data.get("content")
                or data.get("description")
                or data.get("snippet")
                or ""
            )[:1500]
            await ctx.send(
                embed=c2(
                    color=color.base,
                    title=title,
                    message=text or "_no text extracted_",
                    footer=url.strip()[:200],
                )
            )

    @brave.command(name="ai", description="Brave AI answer")
    @describe(query="Question")
    async def brave_ai(self, ctx: Context, *, query: str) -> None:
        from .proper.api import brave_ai

        async with ctx.typing():
            data = await brave_ai(query)
            if not data:
                await ctx.fail("Brave AI unavailable.")
                return
            answer = str(
                data.get("answer")
                or data.get("response")
                or data.get("text")
                or data.get("result")
                or ""
            )[:1800]
            if not answer and isinstance(data.get("data"), dict):
                answer = str(data["data"].get("answer") or data["data"].get("text") or "")[:1800]
            if not answer:
                await ctx.fail("Empty AI response.")
                return
            await ctx.send(
                embed=c2(color=color.base, title="Brave AI", message=answer, footer=query[:120])
            )

    @hybrid(
        name="google",
        description="Google search & page scrape",
        aliases=["g"],
        group=True,
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(query="Search query")
    async def google(self, ctx: Context, *, query: str | None = None) -> None:
        if not query:
            await ctx.send_help(ctx.command)
            return
        await ctx.invoke(self.google_search, query=query)

    @google.command(name="search", description="Search the web via Google", aliases=["s", "q"])
    @describe(query="Search query")
    async def google_search(self, ctx: Context, *, query: str) -> None:
        from .proper.api import google_search, parse_search_results

        async with ctx.typing():
            raw = await google_search(query, count=8)
            results = parse_search_results(raw)
            if not results:
                await ctx.fail("No Google results.")
                return
            lines = []
            for i, r in enumerate(results[:8], 1):
                title = r.get("title") or r.get("url") or "result"
                url = r.get("url") or ""
                snip = (r.get("snippet") or "")[:90]
                if url:
                    lines.append(f"**{i}.** [{title}]({url})" + (f"\n> {snip}" if snip else ""))
                else:
                    lines.append(f"**{i}.** {title}")
            await ctx.send(
                embed=c2(color=color.base, title=f"Google · {query[:80]}", message="\n".join(lines))
            )

    @google.command(name="scrape", description="Scrape a URL via Google path")
    @describe(url="Page URL")
    async def google_scrape(self, ctx: Context, *, url: str) -> None:
        from .proper.api import google_scrape

        async with ctx.typing():
            data = await google_scrape(url.strip())
            if not data:
                await ctx.fail("Could not scrape that URL.")
                return
            title = str(data.get("title") or data.get("name") or "Page")[:120]
            text = str(
                data.get("text")
                or data.get("content")
                or data.get("description")
                or data.get("snippet")
                or ""
            )[:1500]
            await ctx.send(
                embed=c2(
                    color=color.base,
                    title=title,
                    message=text or "_no text extracted_",
                    footer=url.strip()[:200],
                )
            )

    @hybrid(
        name="repost",
        description="Repost TikTok, Instagram, X, YouTube, or Pinterest media",
        example=",repost https://www.instagram.com/reel/xxxx",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(url="Social media post URL")
    async def repost(self, ctx: Context, *, url: str) -> None:
        async with ctx.typing():
            try:
                await self._repost(ctx, url)
            except Exception as e:
                await ctx.fail(f"Repost failed: {str(e)[:150]}")


    @staticmethod
    def _is_video_url(u: str) -> bool:
        lu = (u or "").lower()
        
        image_hint = any(
            token in lu
            for token in (
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".gif",
                "mime_type=image",
                "/image/",
                "avatar",
                "thumbnail",
                "~tplv-",
            )
        )
        video_hint = any(
            token in lu
            for token in (
                ".mp4",
                ".webm",
                ".mov",
                "mime_type=video",
                "/video/",
                "video_mp4",
                "playwm",
                "play?",
                "/play",
                "aweme",
                "/v/t16/",
                "/v/t50/",
                "tikwm.com/video",
                "tikmate",
                "musical.ly",
            )
        )
        if image_hint and not video_hint:
            return False
        return video_hint

    @staticmethod
    def _looks_like_video_bytes(data: bytes | None) -> bool:
        """True when *data* is large enough and not an HTML/JSON error body."""
        if not data or len(data) < 2048:
            return False
        head = data.lstrip()[:64]
        if head.startswith((b"<", b"{", b"[")) or head.upper().startswith(b"<!DOCTYPE"):
            return False
        
        if b"ftyp" in data[:64]:
            return True
        if data[:4] == b"\x1aE\xdf\xa3":
            return True
        if data[:4] == b"RIFF" and data[8:12] != b"WEBP":
            return True
        
        return b"\x00" in data[:16]

    def _upload_limit(self, ctx: Context) -> int:
        return discord_upload_limit(getattr(ctx, "guild", None))

    async def _download_bytes(
        self,
        media_url: str,
        *,
        platform: str = "",
        max_bytes: int | None = None,
    ) -> bytes | None:
        """Download media. Large files are kept so they can be compressed later."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": (
                "https://www.instagram.com/"
                if platform == "instagram"
                else "https://www.tiktok.com/"
            ),
        }
        
        base_limit = max_bytes if max_bytes is not None else 24 * 1024 * 1024
        hard_cap = max(base_limit * 4, 100 * 1024 * 1024)
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    media_url, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        return None
                    
                    cl = resp.headers.get("Content-Length")
                    if cl and cl.isdigit() and int(cl) > hard_cap:
                        return None
                    data = await resp.read()
                    if not data or len(data) > hard_cap:
                        return None
                    return data
        except Exception:
            return None

    async def _prepare_file(
        self,
        ctx: Context,
        data: bytes,
        *,
        filename: str,
    ) -> discord.File | None:
        """Compress if needed and build a Discord file under the guild limit."""
        if not data:
            return None
        limit = self._upload_limit(ctx)
        fitted, name = await fit_for_discord(
            data,
            filename=filename,
            guild=getattr(ctx, "guild", None),
            max_bytes=limit,
        )
        if len(fitted) > limit:
            mb = len(fitted) / (1024 * 1024)
            lim_mb = limit / (1024 * 1024)
            await ctx.fail(
                f"Video is still too large after compression "
                f"({mb:.1f}MB / {lim_mb:.0f}MB limit)."
            )
            return None
        return discord.File(io.BytesIO(fitted), filename=name)

    async def _ytdlp_file(
        self,
        ctx: Context,
        source_url: str,
        platform: str,
    ) -> discord.File | None:
        """Download playable media via yt-dlp when CDN URL is unavailable."""
        loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory(prefix="repost-") as tmp:
            result = await loop.run_in_executor(None, _ytdlp_download_sync, source_url, tmp)
            if not result or not result.get("filepath"):
                return None
            filepath = result["filepath"]
            if not os.path.exists(filepath):
                return None
            
            if os.path.getsize(filepath) > 100 * 1024 * 1024:
                return None
            with open(filepath, "rb") as fh:
                data = fh.read()
            ext = os.path.splitext(result.get("filename") or "media.mp4")[1] or ".mp4"
            return await self._prepare_file(ctx, data, filename=f"{platform}{ext}")


    async def _repost(self, ctx: Context, url: str) -> None:
        """Fetch social media and send Components V2 repost panel.

        Supports TikTok, Instagram, X/Twitter, YouTube, Pinterest, Twitch.
        Videos attach as a file; multi-image sets paginate.
        """
        from .proper.api import (
            fetch_twitter_social_post,
            fetch_youtube_social_post,
            parse_pinterest_pin,
            parse_twitch_video,
            pinterest_pin,
            twitch_video,
            twitter_status_id_from_url,
            youtube_video_id_from_url,
        )

        url = (url or "").strip()
        if not url:
            await ctx.warn(
                "Provide a TikTok, Instagram, X, YouTube, Pinterest, or Twitch URL."
            )
            return
        if not url.startswith("http"):
            url = "https://" + url

        post: SocialPost | None = None
        lu = url.lower()

        if is_tiktok_url(url) or "vm.tiktok" in lu or "vt.tiktok" in lu:
            client = TikTok()
            try:
                post = await client.post(url)
            finally:
                await client.close()
        elif is_instagram_url(url):
            client = Instagram()
            try:
                post = await client.post(url)
            finally:
                await client.close()
        elif "twitter.com" in lu or "x.com" in lu or twitter_status_id_from_url(url):
            post = await fetch_twitter_social_post(url)
        elif "youtu" in lu or youtube_video_id_from_url(url):
            post = await fetch_youtube_social_post(url)
            if post is None:
                upload = await self._ytdlp_file(ctx, url, "youtube")
                if upload is None:
                    await ctx.fail("Could not fetch that YouTube video.")
                    return
                view = SocialRepostView(
                    platform="youtube",
                    username="youtube",
                    display_name="YouTube",
                    caption="",
                    media_urls=[],
                    source_url=url,
                    attachment_filename=upload.filename,
                    owner_id=ctx.author.id,
                    play_count=0,
                )
                try:
                    upload.fp.seek(0)
                except Exception:
                    pass
                msg = await ctx.send(file=upload, view=view)
                view.message = msg
                return
        elif "pinterest." in lu or "pin.it" in lu:
            raw = await pinterest_pin(url)
            post = parse_pinterest_pin(raw or {}, source_url=url) if raw else None
        elif "twitch.tv" in lu:
            m = re.search(r"twitch\.tv/videos/(\d+)", lu)
            if m:
                raw = await twitch_video(m.group(1))
                post = parse_twitch_video(raw or {}, source_url=url) if raw else None
            else:
                await ctx.warn("Use a Twitch VOD URL (`twitch.tv/videos/...`), or `,twitch user`.")
                return
        else:
            await ctx.warn(
                "Supported links: **TikTok**, **Instagram**, **X**, **YouTube**, "
                "**Pinterest**, **Twitch** VODs."
            )
            return

        if post is None:
            await ctx.fail("Could not fetch that post. It may be private or unavailable.")
            return

        media_urls = [u for u in (post.media_urls or []) if u]
        video_urls = [u for u in media_urls if self._is_video_url(u)]
        image_urls = [u for u in media_urls if not self._is_video_url(u)]

        wants_video = bool(
            video_urls
            or post.is_video
            or "/reel" in (post.url or url).lower()
            or "/video/" in (post.url or url).lower()
            or "/shorts/" in (post.url or url).lower()
            or (post.platform or "").lower() == "youtube"
        )
        limit = self._upload_limit(ctx)
        thumb = None
        if isinstance(post.raw, dict):
            thumb = post.raw.get("thumbnail_url") or post.raw.get("cover")
        accent = await get_repost_accent_color(
            self.bot,
            avatar_url=post.avatar_url,
            thumbnail_url=str(thumb) if thumb else None,
            platform=post.platform,
        )

        upload: discord.File | None = None
        display_media = image_urls[:]

        post_id = post.raw.get("id") if isinstance(post.raw, dict) else None
        if post_id and str(post_id).replace("-", "").isalnum():
            video_filename = f"{post_id}.mp4"
        else:
            video_filename = f"{(post.platform or 'video').lower()}.mp4"

        if wants_video:
            data: bytes | None = None
            candidates = list(dict.fromkeys([*video_urls, *media_urls]))
            for media_url in candidates:
                blob = await self._download_bytes(
                    media_url, platform=post.platform, max_bytes=limit
                )
                if self._looks_like_video_bytes(blob):
                    data = blob
                    break
            if data:
                upload = await self._prepare_file(ctx, data, filename=video_filename)
                if upload is None:
                    return
            else:
                upload = await self._ytdlp_file(ctx, post.url or url, post.platform)
                if upload is None:
                    
                    if image_urls:
                        display_media = image_urls
                        wants_video = False
                    else:
                        await ctx.fail("Could not download that video.")
                        return
            if upload is not None:
                display_media = []
                video_filename = upload.filename or video_filename
        elif image_urls:
            display_media = image_urls
        else:
            upload = await self._ytdlp_file(ctx, post.url or url, post.platform)
            if upload is None and not display_media:
                await ctx.fail("Could not get media for that post.")
                return
            if upload is not None:
                video_filename = upload.filename or video_filename
                display_media = []

        view = SocialRepostView(
            platform=post.platform,
            username=post.username,
            display_name=post.display_name or post.username,
            caption=post.caption or "",
            media_urls=display_media,
            avatar_url=post.avatar_url,
            source_url=post.url or url,
            accent=accent,
            like_count=post.like_count,
            comment_count=post.comment_count,
            save_count=post.save_count,
            share_count=post.share_count,
            play_count=getattr(post, "play_count", 0) or 0,
            region=post.region,
            music_title=post.music_title,
            music_author=post.music_author,
            music_url=post.music_url,
            attachment_filename=(upload.filename if upload is not None else None),
            owner_id=ctx.author.id,
        )

        send_kw: dict = {"view": view}
        if upload is not None:
            try:
                upload.fp.seek(0)
            except Exception:
                pass
            send_kw["file"] = upload

        try:
            msg = await ctx.send(**send_kw)
            view.message = msg
        except discord.HTTPException as exc:
            if upload is not None and (
                getattr(exc, "code", None) == 40005 or exc.status == 413
            ):
                try:
                    upload.fp.seek(0)
                except Exception:
                    pass
                raw = upload.fp.read()
                tighter = max(8 * 1024 * 1024, limit // 2)
                fitted, name = await fit_for_discord(
                    raw,
                    filename=upload.filename or video_filename,
                    max_bytes=tighter,
                )
                if len(fitted) > tighter:
                    await ctx.fail(
                        "Video is too large for Discord even after compression."
                    )
                    return
                view.attachment_filename = name
                view._rebuild()
                msg = await ctx.send(
                    file=discord.File(io.BytesIO(fitted), filename=name),
                    view=view,
                )
                view.message = msg
            else:
                raise


    async def _generate_quote_image(
        self,
        content: str,
        display_name: str,
        username: str,
        avatar_url: str,
    ) -> bytes:
        """Generate a quote image locally using PIL."""
        loop = asyncio.get_running_loop()

        def _build() -> bytes:
            W, H = 857, 450
            font_size = 50

            try:
                font = ImageFont.truetype(FONT_PATH, font_size)
                name_font = ImageFont.truetype(FONT_PATH, 32)
                user_font = ImageFont.truetype(FONT_PATH, 22)
            except Exception:
                font = ImageFont.load_default()
                name_font = font
                user_font = font

            blank = Image.new("RGB", (W, H), color=(0, 0, 0))

            
            try:
                resp = urllib.request.urlopen(avatar_url)
                avatar_raw = resp.read()
                avatar = Image.open(io.BytesIO(avatar_raw)).convert("RGBA")
                avatar = avatar.resize((450, 450), Image.LANCZOS)
            except Exception:
                avatar = Image.new("RGBA", (450, 450), (80, 80, 80, 255))

            
            gradient = Image.new("RGBA", (450, 450), (0, 0, 0, 0))
            draw_grad = ImageDraw.Draw(gradient)
            for y in range(450):
                alpha = int(255 * (y / 450) * 0.7)
                draw_grad.line([(0, y), (450, y)], fill=(0, 0, 0, alpha))

            
            avatar.paste(Image.alpha_composite(avatar, gradient), (0, 0), avatar)
            avatar_rgb = avatar.convert("RGB")

            blank.paste(avatar_rgb, (0, 0))

            
            max_chars = 20
            words = content.split()
            lines = []
            current_line = ""
            for word in words:
                test = f"{current_line} {word}".strip()
                if len(test) <= max_chars:
                    current_line = test
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)
            wrapped = "\n".join(lines)

            
            text_x = 550
            max_text_w = W - text_x - 30
            max_text_h = H - 120
            while font_size > 12:
                test_font = ImageFont.truetype(FONT_PATH, font_size)
                bbox = test_font.getbbox(wrapped)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                if tw <= max_text_w and th <= max_text_h:
                    font = test_font
                    break
                font_size -= 2

            
            draw = ImageDraw.Draw(blank)
            text_bbox = font.getbbox(wrapped)
            text_h = text_bbox[3] - text_bbox[1]
            text_y = (H - text_h) // 2 - 20
            draw.text((text_x, text_y), wrapped, fill=(255, 255, 255), font=font)

            
            name_y = text_y + text_h + 15
            draw.text((text_x, name_y), f"- {display_name}", fill=(255, 255, 255), font=name_font)

            
            user_y = name_y + 40
            draw.text((text_x, user_y), f"@{username}", fill=(89, 89, 89), font=user_font)

            
            draw.text((W - 100, H - 30), "vain", fill=(89, 89, 89), font=user_font)

            buf = io.BytesIO()
            blank.save(buf, format="PNG", quality=95)
            return buf.getvalue()

        return await loop.run_in_executor(None, _build)

    @hybrid(
        name="quote",
        description="Quote a message as an image",
        aliases=["qm", "quotemessage"],
    )
    @describe(message="Message to quote (or reply to one)")
    async def quote_command(self, ctx: Context, message: discord.Message = None) -> None:
        if not message and ctx.message.reference:
            message = ctx.message.reference.resolved
        if not message:
            return await ctx.warn("Please reply to a message to quote it.")
        if not message.content:
            return await ctx.warn("You cannot quote this message (no text content).")

        async with ctx.typing():
            avatar_url = str(message.author.display_avatar.url)
            image_data = await self._generate_quote_image(
                message.clean_content,
                message.author.display_name,
                message.author.name,
                avatar_url,
            )
            file = discord.File(io.BytesIO(image_data), filename="quote.png")
            await ctx.send(file=file)

async def setup(bot: Vain):
    from .extended.roblox import Roblox
    from .proper.builders import register_builders
    cog = Socials(bot)
    await register_builders(bot)
    await bot.add_cog(cog)
    await bot.add_cog(Roblox(bot))
