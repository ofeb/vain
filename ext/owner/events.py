"""Event listeners for owner — bot join/leave logging and blacklist expiry."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks

from core.discord.package import Package
from core.managers.values import color
from core.tools.aesthetic import panel_embed, get_bot_dominant_color

if TYPE_CHECKING:
    from core.vain import Vain


DEVLOG_GUILD_IGNORE: set[int] = {
    1424433148892287108,
    1333981881913315358,
    1431305396244713624,
    
    1182395946529738822,
    1339029903949168753,
    1235958190127058946,
    1136858318900564029,
}


class OwnerEvents(Package):
    """Bot join/leave logging and periodic tasks"""

    @Package.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Log when the bot joins a new guild"""
        if guild.id in DEVLOG_GUILD_IGNORE:
            return

        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_member(guild.owner_id)
            except Exception:
                owner = None
        owner_str = f"{owner} (`{getattr(owner, 'id', guild.owner_id)}`)" if owner else f"Unknown (`{guild.owner_id}`)"

        try:
            dom = await get_bot_dominant_color(self.bot)
        except Exception:
            dom = 0xD4B8D0

        
        lines = [
            f"**Owner**: {owner_str}",
            f"**Members**: {guild.member_count}",
            f"**Created**: <t:{int(guild.created_at.timestamp())}:R>",
            f"**ID**: `{guild.id}`",
            f"**Boost Tier**: {guild.premium_tier}",
            f"**Features**: {len(guild.features or [])}",
        ]

        embed = panel_embed(
            title=f"📥 Joined {guild.name}",
            color=dom,
            lines=lines,
            thumbnail=guild.icon.url if guild.icon else None,
            timestamp=True,
        )

        channel_id = await self.db.fetchval(
            "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
            self.bot.user.id,
        )
        if channel_id:
            ch = self.bot.get_channel(channel_id)
            if ch:
                try:
                    await ch.send(embed=embed)
                except discord.HTTPException:
                    pass

    @Package.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Log when the bot leaves a guild"""
        if guild.id in DEVLOG_GUILD_IGNORE:
            return

        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_member(guild.owner_id)
            except Exception:
                owner = None
        owner_str = f"{owner} (`{getattr(owner, 'id', guild.owner_id)}`)" if owner else f"Unknown (`{guild.owner_id}`)"

        try:
            dom = await get_bot_dominant_color(self.bot)
        except Exception:
            dom = 0xE07A7A

        lines = [
            f"**Owner**: {owner_str}",
            f"**Members**: {guild.member_count}",
            f"**ID**: `{guild.id}`",
        ]

        embed = panel_embed(
            title=f"📤 Left {guild.name}",
            color=dom,
            lines=lines,
            thumbnail=guild.icon.url if guild.icon else None,
            timestamp=True,
        )

        channel_id = await self.db.fetchval(
            "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
            self.bot.user.id,
        )
        if channel_id:
            ch = self.bot.get_channel(channel_id)
            if ch:
                try:
                    await ch.send(embed=embed)
                except discord.HTTPException:
                    pass

    @tasks.loop(minutes=5)
    async def check_blacklist_expiry(self) -> None:
        """Remove expired blacklist entries"""
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
