"""Event listeners for owner — bot join/leave logging and blacklist expiry."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks

from core.discord.package import Package
from core.managers.values import color
from core.tools.aesthetic import panel_embed

if TYPE_CHECKING:
    from core.vain import Vain


DEVLOG_GUILD_IGNORE: set[int] = {
    1424433148892287108,
    1333981881913315358,
    1431305396244713624,
}


class OwnerEvents(Package):
    """Bot join/leave logging and periodic tasks"""

    @Package.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Log when the bot joins a new guild"""
        if guild.id in DEVLOG_GUILD_IGNORE:
            return

        owner = guild.owner
        owner_str = str(owner) if owner else "Unknown"

        embed = panel_embed(
            title=f"{guild.name} joined",
            color=0xD4B8D0,
            lines=[],
            thumbnail=guild.icon.url if guild.icon else None,
            timestamp=False,
        )
        embed.timestamp = datetime.now(timezone.utc)
        embed.add_field(name="Owner", value=owner_str, inline=True)
        embed.add_field(name="Guild ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(
            name="Member Count", value=str(guild.member_count), inline=True
        )
        embed.add_field(
            name="Created",
            value=f"<t:{int(guild.created_at.timestamp())}:R>",
            inline=True,
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
        owner_str = str(owner) if owner else "Unknown"

        embed = panel_embed(
            title=f"{guild.name} left",
            color=0xE07A7A,
            lines=[],
            thumbnail=guild.icon.url if guild.icon else None,
            timestamp=False,
        )
        embed.timestamp = datetime.now(timezone.utc)
        embed.add_field(name="Owner", value=owner_str, inline=True)
        embed.add_field(name="Guild ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(
            name="Member Count", value=str(guild.member_count), inline=True
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
