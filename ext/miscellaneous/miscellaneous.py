from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid, group
from core.managers.values import color

if TYPE_CHECKING:
    pass


class Miscellaneous(commands.Cog):
    """Various useful commands that don't fit elsewhere."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.afk_users: dict[int, dict] = {}
        self.active_polls: list[dict] = []

    @hybrid(
        name="ping",
        description="Check the bot's response time",
        guild_only=True,
    )
    async def ping(self, ctx: Context) -> None:
        latency = round(self.bot.latency * 1000)
        await ctx.success(f"Pong! **{latency}ms**")

    @hybrid(
        name="uptime",
        description="Check how long the bot has been online",
        guild_only=True,
    )
    async def uptime(self, ctx: Context) -> None:
        now = discord.utils.utcnow()
        delta = now - self.bot.started_at
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        embed = discord.Embed(
            title="Uptime",
            description=f"**{hours}h {minutes}m {seconds}s**",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="invite",
        description="Get the bot's invite link",
        guild_only=True,
    )
    async def invite(self, ctx: Context) -> None:
        bot_id = self.bot.user.id if self.bot.user else "0"
        embed = discord.Embed(
            title="Invite Bleed",
            description=f"[Click here to invite me!](https://discord.com/oauth2/authorize?client_id={bot_id}&permissions=8&scope=bot%20applications.commands)",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="afk",
        description="Set yourself as away from keyboard",
        guild_only=True,
    )
    @describe(reason="Reason for going AFK")
    async def afk(self, ctx: Context, *, reason: str = "AFK") -> None:
        self.afk_users[ctx.author.id] = {
            "reason": reason,
            "since": discord.utils.utcnow(),
            "guild_id": ctx.guild.id,
        }

        try:
            nick = f"[AFK] {ctx.author.display_name}"
            if len(nick) <= 32 and ctx.guild.me.guild_permissions.manage_nicknames:
                await ctx.author.edit(nick=nick)
        except Exception:
            pass

        embed = discord.Embed(
            title="AFK",
            description=f"{ctx.author.mention} is now AFK: **{reason}**",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @commands.Cog.listener()
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

    @hybrid(
        name="poll",
        description="Create a poll with upvote and downvote reactions",
        guild_only=True,
    )
    @describe(question="The poll question")
    async def poll(self, ctx: Context, *, question: str) -> None:
        embed = discord.Embed(
            title="Poll",
            description=question,
            color=color.base,
        )
        embed.set_footer(text=f"Started by {ctx.author.display_name}")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    @hybrid(
        name="quickpoll",
        description="Add upvote/downvote reactions to a message",
        guild_only=True,
    )
    @describe(message_id="ID of the message to add reactions to")
    async def quickpoll(self, ctx: Context, message_id: str) -> None:
        try:
            msg = await ctx.channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound, discord.Forbidden):
            await ctx.fail("Could not find that message.")
            return

        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await ctx.success("Added reactions to that message.")

    @hybrid(
        name="avatar",
        description="View a user's avatar",
        aliases=["av"],
        guild_only=True,
    )
    @describe(user="User whose avatar to view")
    async def avatar(self, ctx: Context, *, user: discord.User = None) -> None:
        user = user or ctx.author
        embed = discord.Embed(
            title=f"{user.display_name}'s Avatar",
            color=color.base,
        )
        embed.set_image(url=user.display_avatar.url)
        await ctx.send(embed=embed)

    @hybrid(
        name="userinfo",
        description="View information about a user",
        aliases=["ui", "whois"],
        guild_only=True,
    )
    @describe(user="User to get info about")
    async def userinfo(self, ctx: Context, *, user: discord.Member = None) -> None:
        user = user or ctx.author
        roles = [r.mention for r in user.roles if r != ctx.guild.default_role]
        embed = discord.Embed(
            title=f"User Info — {user.display_name}",
            color=color.base,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=user.id, inline=True)
        embed.add_field(name="Joined", value=discord.utils.format_dt(user.joined_at, style="R"), inline=True)
        embed.add_field(name="Registered", value=discord.utils.format_dt(user.created_at, style="R"), inline=True)
        embed.add_field(name="Roles", value=" ".join(roles[:5]) if roles else "None", inline=False)
        await ctx.send(embed=embed)

    @hybrid(
        name="serverinfo",
        description="View information about the server",
        aliases=["si", "guildinfo"],
        guild_only=True,
    )
    async def serverinfo(self, ctx: Context) -> None:
        guild = ctx.guild
        embed = discord.Embed(
            title=f"Server Info — {guild.name}",
            color=color.base,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="ID", value=guild.id, inline=True)
        embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "N/A", inline=True)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, style="R"), inline=True)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Miscellaneous(bot))
