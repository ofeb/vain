from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from typing import TYPE_CHECKING

import aiohttp
import discord
from colorthief import ColorThief
from discord.ext import tasks

from config import color
from core.discord.package import Package
from core.discord.views.embed import panel_embed

if TYPE_CHECKING:
    from core.vain import Vain

DEVLOG_GUILD_IGNORE: set[int] = {
    1424433148892287108,
    1333981881913315358,
    1431305396244713624,
    1411409392334672013,
    1182395946529738822,
    1339029903949168753,
    1235958190127058946,
    1136858318900564029,
}


async def get_dominant_color(url: str, fallback: int = 0xE1D2DE) -> int:
    if not url:
        return fallback
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return fallback
                data = await resp.read()

        def _extract():
            ct = ColorThief(BytesIO(data))
            r, g, b = ct.get_color(quality=1)
            if (r + g + b) < 80:
                r = min(r + 60, 255)
                g = min(g + 60, 255)
                b = min(b + 60, 255)
            return (r << 16) + (g << 8) + b

        return await asyncio.to_thread(_extract)
    except Exception:
        return fallback


async def get_bot_dominant_color(bot) -> int:
    if bot.user and bot.user.display_avatar:
        return await get_dominant_color(str(bot.user.display_avatar.url))
    return 0xE1D2DE


def _humans_bots(guild: discord.Guild) -> tuple[int, int]:
    humans = 0
    bots = 0
    for m in guild.members:
        if m.bot:
            bots += 1
        else:
            humans += 1
    total = guild.member_count or (humans + bots)
    if humans + bots == 0 and total:
        return total, 0
    return humans, bots


def _guild_devlog_lines(guild: discord.Guild, *, owner_str: str) -> list[str]:
    humans, bots = _humans_bots(guild)
    total = guild.member_count or (humans + bots)
    text_c = len(guild.text_channels)
    voice_c = len(guild.voice_channels)
    cats = len(guild.categories)
    roles = max(0, len(guild.roles) - 1)
    emojis = len(guild.emojis)
    stickers = len(getattr(guild, "stickers", []) or [])
    boosts = guild.premium_subscription_count or 0
    tier = guild.premium_tier
    vanity = getattr(guild, "vanity_url_code", None)
    verification = str(guild.verification_level).replace("_", " ").title()
    created_ts = int(guild.created_at.timestamp())

    lines = [
        f"**Owner:** {owner_str}",
        f"**Members:** `{total:,}` · humans `{humans:,}` · bots `{bots:,}`",
        f"**Channels:** `{text_c + voice_c + cats:,}` · text `{text_c}` · voice `{voice_c}` · categories `{cats}`",
        f"**Roles:** `{roles:,}` · **Emojis:** `{emojis}` · **Stickers:** `{stickers}`",
        f"**Boosts:** `{boosts}` · tier `{tier}`",
        f"**Verification:** {verification}",
        f"**Created:** <t:{created_ts}:D> (<t:{created_ts}:R>)",
        f"**ID:** `{guild.id}`",
    ]
    if vanity:
        lines.insert(-1, f"**Vanity:** `discord.gg/{vanity}`")
    return lines


async def _resolve_owner_str(guild: discord.Guild) -> str:
    owner = guild.owner
    if owner is None and guild.owner_id:
        try:
            owner = await guild.fetch_member(guild.owner_id)
        except Exception:
            owner = None
    if owner is not None:
        return f"{owner.mention} · `{owner}` (`{owner.id}`)"
    if guild.owner_id:
        return f"<@{guild.owner_id}> (`{guild.owner_id}`)"
    return "Unknown"


async def _devlog_channel(bot) -> discord.abc.Messageable | None:
    if not bot.user:
        return None
    channel_id = await bot.db.fetchval(
        "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
        bot.user.id,
    )
    if not channel_id:
        return None
    ch = bot.get_channel(channel_id)
    if ch is None:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception:
            return None
    return ch


class OwnerEvents(Package):
    """Bot join/leave logging and periodic tasks."""

    @Package.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        if guild.id in DEVLOG_GUILD_IGNORE:
            return

        await self.db.execute(
            "INSERT INTO guild_cache (guild_id, name, owner_id, icon_url, member_count) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (guild_id) DO UPDATE SET name = $2, owner_id = $3, icon_url = $4, member_count = $5",
            guild.id,
            guild.name,
            guild.owner_id,
            str(guild.icon.url) if guild.icon else None,
            guild.member_count,
        )

        owner_str = await _resolve_owner_str(guild)

        guilds = len(self.bot.guilds)
        users = sum((g.member_count or 0) for g in self.bot.guilds)

        lines = _guild_devlog_lines(guild, owner_str=owner_str)
        lines.append(f"**Bot reach:** `{guilds:,}` guilds · `{users:,}` users")

        embed = panel_embed(
            title=f"Joined {guild.name}",
            lines=lines,
            thumbnail=guild.icon.url if guild.icon else None,
            timestamp=True,
            footer=f"Guild join · {guilds} guilds",
        )
        embed.color = None

        ch = await _devlog_channel(self.bot)
        if ch is None:
            return
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    @Package.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        if guild.id in DEVLOG_GUILD_IGNORE:
            return

        cached = await self.db.fetchrow(
            "SELECT name, owner_id, icon_url, member_count FROM guild_cache WHERE guild_id = $1",
            guild.id,
        )

        guild_name = cached["name"] if cached else guild.name
        owner_id = cached["owner_id"] if cached else guild.owner_id
        icon_url = cached["icon_url"] if cached else (str(guild.icon.url) if guild.icon else None)
        member_count = cached["member_count"] if cached else guild.member_count

        if owner_id:
            owner_str = f"<@{owner_id}> (`{owner_id}`)"
        else:
            owner_str = "Unknown"

        guilds = len(self.bot.guilds) - 1
        users = sum((g.member_count or 0) for g in self.bot.guilds) - (member_count or 0)

        humans = member_count or 0
        text_c = 0
        voice_c = 0
        cats = 0
        roles = 0
        emojis = 0
        stickers = 0
        boosts = 0
        tier = 0
        created_ts = int(guild.created_at.timestamp())

        lines = [
            f"**Owner:** {owner_str}",
            f"**Members:** `{humans:,}` · humans `{humans:,}` · bots `0`",
            f"**Channels:** `0` · text `0` · voice `0` · categories `0`",
            f"**Roles:** `0` · **Emojis:** `0` · **Stickers:** `0`",
            f"**Boosts:** `0` · tier `0`",
            f"**Verification:** Unknown",
            f"**Created:** <t:{created_ts}:D> (<t:{created_ts}:R>)",
            f"**ID:** `{guild.id}`",
        ]
        lines.append(f"**Bot reach:** `{guilds:,}` guilds · `{users:,}` users")

        embed = panel_embed(
            title=f"Left {guild_name}",
            lines=lines,
            thumbnail=icon_url,
            timestamp=True,
            footer=f"Guild leave · {guilds} guilds",
        )
        embed.color = None

        ch = await _devlog_channel(self.bot)
        if ch is None:
            return
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

        await self.db.execute(
            "DELETE FROM guild_cache WHERE guild_id = $1",
            guild.id,
        )

    @tasks.loop(minutes=5)
    async def check_blacklist_expiry(self) -> None:
        now = datetime.now(timezone.utc)
        expired = await self.db.fetch(
            "DELETE FROM blacklist WHERE expires_at IS NOT NULL "
            "AND expires_at <= $1 RETURNING user_id",
            now,
        )
        for row in expired:
            if row["user_id"]:
                if self.bot.redis:
                    await self.bot.redis.delete(
                        f"blacklist:*:{row['user_id']}"
                    )

    @check_blacklist_expiry.before_loop
    async def before_check_blacklist_expiry(self) -> None:
        await self.bot.wait_until_ready()
