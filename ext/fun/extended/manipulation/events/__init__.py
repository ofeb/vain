from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import discord

from core.discord.package import Package
from core.discord.views.embed import c2

if TYPE_CHECKING:
    from core.vain import Vain


class ManipulationEvents(Package):
    """Bot-mention quote + prefix info."""

    @Package.listener("on_message")
    async def on_bot_mention_quote(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not self.bot.user or self.bot.user not in message.mentions:
            return

        # strip bot mentions to see if anything else remains
        content = message.content or ""
        for m in message.mentions:
            content = content.replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "")
        content = content.strip()

        # reply + mention => quote referenced message
        if message.reference and not content:
            ref = message.reference.resolved
            if not isinstance(ref, discord.Message):
                try:
                    ref = await message.channel.fetch_message(message.reference.message_id)
                except Exception:
                    ref = None
            if not isinstance(ref, discord.Message):
                return

            cog = self.bot.get_cog("Manipulation")
            if cog is None:
                return
            # Build a minimal context and invoke quote
            try:
                from core.discord.ctx import Context

                ctx = await self.bot.get_context(message, cls=Context)
                await cog.quote_command(ctx, message=ref)
            except Exception:
                with contextlib.suppress(Exception):
                    await message.channel.send(
                        "Couldn't quote that message.",
                        delete_after=8,
                    )
            return

        # bare mention (or mention-only) => prefix card
        if content:
            return

        try:
            data = await self.bot._fetch_prefixes(message.guild.id, message.author.id)
        except Exception:
            data = {"user": None, "guild": [","]}

        guild_pfxs = list(data.get("guild") or [])
        if not guild_pfxs:
            try:
                from config import Bot
                guild_pfxs = [Bot.prefix]
            except Exception:
                guild_pfxs = [","]

        personal = data.get("user")
        if len(guild_pfxs) == 1:
            guild_line = f"My prefix is: `{guild_pfxs[0]}`"
        else:
            shown = " ".join(f"`{p}`" for p in guild_pfxs)
            guild_line = f"My prefixes are: {shown}"

        if personal:
            personal_line = f"Your personal prefix is: `{personal}`"
        else:
            personal_line = "Your personal prefix is: *not set*"

        embed = c2(message=f"{guild_line}\n{personal_line}")
        with contextlib.suppress(Exception):
            await message.channel.send(embed=embed)
