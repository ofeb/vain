from __future__ import annotations

import random
from asyncio import Lock
from collections import defaultdict

import discord

from core.discord.package import Package


class FunEvents(Package):
    def __init__(self, bot):
        super().__init__(bot)
        self.locks = defaultdict(Lock)
        self.message_stats = defaultdict(int)

    @Package.listener("on_message")
    async def on_message_stats(self, message: discord.Message):
        if message.author.bot:
            return

        self.message_stats[message.author.id] += 1

    @Package.listener("on_reaction_add")
    async def on_reaction_bonus(self, reaction: discord.Reaction, user: discord.Member):
        if user.bot:
            return

        try:
            config = await self.db.fetchrow(
                "SELECT * FROM fun_config WHERE guild_id = $1",
                reaction.message.guild.id,
            )
        except Exception:
            return
        if not config or not config.get("reaction_rewards", False):
            return

        if random.random() < 0.1:
            self.message_stats[user.id] += 1

    @Package.listener("on_member_join")
    async def on_welcome_message(self, member: discord.Member):
        try:
            config = await self.db.fetchrow(
                "SELECT * FROM fun_config WHERE guild_id = $1",
                member.guild.id,
            )
        except Exception:
            return
        if not config or not config.get("welcome_enabled", False):
            return

        welcome_channel = member.guild.get_channel(config.get("welcome_channel"))
        if not welcome_channel:
            return

        welcome_messages = [
            f"Welcome {member.mention} to {member.guild.name}!",
            f"Hey {member.mention}, glad you're here!",
            f"Welcome aboard {member.mention}!",
            f"Great to see you {member.mention}!",
        ]

        message = random.choice(welcome_messages)
        await welcome_channel.send(message)
