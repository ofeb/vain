from __future__ import annotations

import discord

from core.discord.package import Package
from ..settings import Settings


class LastfmEvents:
    @Package.listener("on_message")
    async def on_message_lastfm_custom(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return
        if not getattr(self.bot, "db", None):
            return
        rows = await Settings.list_custom_commands(self.bot, message.guild.id)
        if not rows:
            return
        content = message.content.lower()
        ctx = await self.bot.get_context(message)
        if not ctx.valid:
            return
        for row in rows:
            trigger = (row.get("command") or "").lower()
            if not trigger or trigger not in content:
                continue
            owner_id = int(row["user_id"])
            is_public = bool(row.get("public"))
            if owner_id != message.author.id and not is_public:
                continue
            member = message.guild.get_member(owner_id)
            if member is None:
                continue
            await self.lastfm_now(ctx, query=member.mention)
            return

