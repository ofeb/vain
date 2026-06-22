from __future__ import annotations

import discord

from core.discord.package import Package


class MiscellaneousEvents:
    @Package.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        ctx = await self.bot.get_context(message)
        if not ctx.valid:
            return

        mentioned_afk = []
        for user in message.mentions:
            afk_data = self.afk_users.get(user.id)
            if afk_data and afk_data["guild_id"] == message.guild.id:
                ago = discord.utils.utcnow() - afk_data["since"]
                minutes = int(ago.total_seconds() // 60)
                mentioned_afk.append(f"{user.display_name} is AFK (**{afk_data['reason']}**) — {minutes}m ago")

        if mentioned_afk:
            await message.channel.send("\n".join(mentioned_afk), delete_after=8)

        afk_data = self.afk_users.pop(message.author.id, None)
        if afk_data and afk_data["guild_id"] == message.guild.id:
            try:
                nickname = message.author.display_name
                if nickname.startswith("[AFK] "):
                    nickname = nickname[6:]
                if message.guild.me.guild_permissions.manage_nicknames:
                    await message.author.edit(nick=nickname)
            except Exception:
                pass
            await message.channel.send(
                f"Welcome back {message.author.mention}! Removed your AFK.",
                delete_after=5,
            )

