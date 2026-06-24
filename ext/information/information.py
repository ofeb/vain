from __future__ import annotations

import platform
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.discord.package import Package
from core.discord.views.paginate import send_pages
from core.managers.values import color

from .lookup import (
    build_cashapp_embed,
    build_define_embed,
    build_github_embed,
    build_urban_embed,
    build_weather_embed,
    fetch_cashapp_profile,
    fetch_dictionary,
    fetch_github_profile,
    fetch_urban_dictionary,
    fetch_weather,
)

if TYPE_CHECKING:
    from core.bleed import Bleed

_CONTEXTS = dict(guilds=True, dms=True, groupchats=True)


class InformationCommands(Package):
    """base mixin for standalone information commands."""

    def __init__(self, bot: Bleed):
        super().__init__(bot)

    @hybrid(
        name="botinfo",
        description="View information about the bot",
        aliases=["bi", "stats"],
    )
    async def botinfo(self, ctx: Context) -> None:
        bot = self.bot
        total_commands = len(set(bot.walk_commands()))
        guilds = len(bot.guilds)
        users = sum(g.member_count or 0 for g in bot.guilds)
        latency = round(bot.latency * 1000)
        uptime = discord.utils.format_dt(bot.started_at, style="R")
        shard_count = bot.shard_count or 1
        lines = [
            f"## {bot.user.display_name if bot.user else 'Bleed'}",
            f"-# Commands » `{total_commands}`",
            f"-# Latency » `{latency}ms`",
            f"-# Uptime » {uptime}",
            f"-# Guilds » `{guilds:,}`",
            f"-# Users » `{users:,}`",
            f"-# Shards » `{shard_count}`",
            f"-# Python » `{platform.python_version()}`",
        ]
        embed = discord.Embed(color=color.base, description="\n".join(lines))
        if bot.user:
            embed.set_thumbnail(url=bot.user.display_avatar.url)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Website",
            style=discord.ButtonStyle.link,
            url="https://percs.cc",
            emoji="\U0001f310",
        ))
        if bot.user:
            view.add_item(discord.ui.Button(
                label="Invite",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/oauth2/authorize?client_id={bot.user.id}&scope=bot+applications.commands&permissions=8",
                emoji="\U0001f517",
            ))
        await ctx.send(embed=embed, view=view)

    @hybrid(
        name="inviteinfo",
        description="View information about an invite",
        aliases=["ii"],
        guild_only=True,
    )
    @describe(invite="Invite code or URL")
    async def inviteinfo(self, ctx: Context, invite: str) -> None:
        code = invite.split("/")[-1].replace("discord.gg/", "").strip()
        try:
            inv = await self.bot.fetch_invite(code, with_counts=True, with_expiration=True)
        except discord.NotFound:
            return await ctx.fail("Could not find that invite.")
        except discord.HTTPException:
            return await ctx.fail("Could not fetch that invite.")

        guild = inv.guild
        channel = inv.channel
        embed = discord.Embed(
            title=f"Invite — {guild.name if guild else 'Unknown'}",
            color=color.base,
        )
        if guild and guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Code", value=f"`{inv.code}`", inline=True)
        embed.add_field(name="Uses", value=str(inv.uses or 0), inline=True)
        embed.add_field(name="Max Uses", value=str(inv.max_uses) if inv.max_uses else "Unlimited", inline=True)
        embed.add_field(name="Temporary", value="Yes" if inv.temporary else "No", inline=True)
        embed.add_field(name="Expires", value=discord.utils.format_dt(inv.expires_at, style="R") if inv.expires_at else "Never", inline=True)
        if guild:
            embed.add_field(name="Members", value=str(inv.approximate_member_count or guild.member_count or "?"), inline=True)
            embed.add_field(name="Online", value=str(inv.approximate_presence_count or "?"), inline=True)
        if channel:
            embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        if inv.inviter:
            embed.add_field(name="Inviter", value=str(inv.inviter), inline=True)
        embed.add_field(name="URL", value=f"https://discord.gg/{inv.code}", inline=False)
        await ctx.send(embed=embed)

    @hybrid(
        name="channelinfo",
        description="View information about a channel",
        aliases=["ci"],
        guild_only=True,
    )
    @describe(channel="Channel to inspect")
    async def channelinfo(self, ctx: Context, channel: discord.abc.GuildChannel = None) -> None:
        channel = channel or ctx.channel
        embed = discord.Embed(title=f"#{channel.name}", color=color.base)
        embed.add_field(name="ID", value=str(channel.id), inline=True)
        embed.add_field(name="Type", value=str(channel.type).replace("_", " ").title(), inline=True)
        embed.add_field(name="Category", value=channel.category.name if getattr(channel, "category", None) else "None", inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(channel.created_at, style="R"), inline=True)
        if isinstance(channel, discord.TextChannel):
            embed.add_field(name="Topic", value=channel.topic or "None", inline=False)
            embed.add_field(name="NSFW", value="Yes" if channel.is_nsfw() else "No", inline=True)
            embed.add_field(name="Slowmode", value=f"{channel.slowmode_delay}s", inline=True)
        if isinstance(channel, discord.VoiceChannel):
            embed.add_field(name="Bitrate", value=str(channel.bitrate), inline=True)
            embed.add_field(name="User Limit", value=str(channel.user_limit or "Unlimited"), inline=True)
        await ctx.send(embed=embed)

    @hybrid(
        name="roleinfo",
        description="View information about a role",
        aliases=["ri"],
        guild_only=True,
    )
    @describe(role="Role to inspect")
    async def roleinfo(self, ctx: Context, role: discord.Role) -> None:
        embed = discord.Embed(title=role.name, color=role.color if role.color.value else color.base)
        embed.add_field(name="ID", value=str(role.id), inline=True)
        embed.add_field(name="Members", value=str(len(role.members)), inline=True)
        embed.add_field(name="Position", value=str(role.position), inline=True)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="Managed", value="Yes" if role.managed else "No", inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(role.created_at, style="R"), inline=True)
        perms = [name.replace("_", " ").title() for name, value in role.permissions if value]
        embed.add_field(
            name="Key Permissions",
            value=", ".join(perms[:12]) if perms else "None",
            inline=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="memberinfo",
        description="View detailed information about a member",
        aliases=["mi"],
        guild_only=True,
    )
    @describe(member="Member to inspect")
    async def memberinfo(self, ctx: Context, member: discord.Member = None) -> None:
        member = member or ctx.author
        roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
        embed = discord.Embed(title=member.display_name, color=member.color if member.color.value else color.base)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="ID", value=str(member.id), inline=True)
        embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, style="R"), inline=True)
        embed.add_field(name="Registered", value=discord.utils.format_dt(member.created_at, style="R"), inline=True)
        embed.add_field(name="Top Role", value=member.top_role.mention, inline=True)
        embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:20]) if roles else "None", inline=False)
        if member.premium_since:
            embed.add_field(name="Boosting Since", value=discord.utils.format_dt(member.premium_since, style="R"), inline=True)
        await ctx.send(embed=embed)

    @hybrid(
        name="shardinfo",
        description="View shard statistics",
        aliases=["shards"],
    )
    async def shardinfo(self, ctx: Context) -> None:
        shard_count = self.bot.shard_count or 1
        lines = []
        for shard_id in range(shard_count):
            guilds = [g for g in self.bot.guilds if g.shard_id == shard_id]
            members = sum(g.member_count or 0 for g in guilds)
            latency = round(self.bot.latency * 1000)
            if hasattr(self.bot, "latencies"):
                for sid, lat in self.bot.latencies:
                    if sid == shard_id:
                        latency = round(lat * 1000)
            lines.append(f"**Shard {shard_id}** — `{len(guilds)}` guilds, `{members:,}` users, `{latency}ms`")
        embed = discord.Embed(
            title="Shard Info",
            description="\n".join(lines) if lines else "Single-shard mode",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="weather",
        description="Get weather information for a location",
        example=",weather Cork",
        **_CONTEXTS,
    )
    @describe(location="City or location name")
    async def weather(self, ctx: Context, *, location: str) -> None:
        from core.managers.values import api

        if not api.openweathermap.strip():
            return await ctx.warn("OpenWeatherMap API key is not configured.")
        try:
            async with aiohttp.ClientSession() as session:
                data = await fetch_weather(session, location)
            embed = build_weather_embed(data, ctx.author)
            await ctx.send(embed=embed)
        except ValueError as exc:
            await ctx.warn(str(exc))
        except aiohttp.ClientError:
            await ctx.fail("Could not reach the weather service.")

    @hybrid(
        name="cashapp",
        description="Retrieve simple CashApp profile information",
        example=",cashapp $jonathan",
        **_CONTEXTS,
    )
    @describe(username="Cash App cashtag")
    async def cashapp(self, ctx: Context, *, username: str) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                profile = await fetch_cashapp_profile(session, username)
            await ctx.send(embed=build_cashapp_embed(profile, ctx.author))
        except ValueError as exc:
            await ctx.warn(str(exc))
        except aiohttp.ClientError:
            await ctx.fail("Could not reach Cash App.")

    @hybrid(
        name="github",
        description="Gets profile information on the given Github user",
        aliases=["git", "gh"],
        example=",github jonathan",
        **_CONTEXTS,
    )
    @describe(username="GitHub username")
    @commands.cooldown(1, 4.5, commands.BucketType.guild)
    async def github(self, ctx: Context, *, username: str) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                profile = await fetch_github_profile(session, username)
            await ctx.send(embed=build_github_embed(profile, ctx.author))
        except ValueError as exc:
            await ctx.warn(str(exc))
        except aiohttp.ClientError:
            await ctx.fail("Could not reach GitHub.")

    @github.error
    async def github_error(self, ctx: Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.cooldown(
                f"Please wait **{error.retry_after:.2f} seconds** before using this command again"
            )

    @hybrid(
        name="define",
        description="Get the definition of a word",
        example=",define vet",
        **_CONTEXTS,
    )
    @describe(word="Word to define")
    async def define(self, ctx: Context, *, word: str) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                entry = await fetch_dictionary(session, word)
            await ctx.send(embed=build_define_embed(entry, ctx.author))
        except ValueError as exc:
            await ctx.warn(str(exc))
        except aiohttp.ClientError:
            await ctx.fail("Could not reach the dictionary service.")

    @hybrid(
        name="urbandictionary",
        description="Get the definition of a word or slang from Urban Dictionary",
        aliases=["ud", "urban"],
        example=",urbandictionary chav",
        **_CONTEXTS,
    )
    @describe(word="Word or slang to look up")
    async def urbandictionary(self, ctx: Context, *, word: str) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                results = await fetch_urban_dictionary(session, word)
        except ValueError as exc:
            return await ctx.warn(str(exc))
        except aiohttp.ClientError:
            return await ctx.fail("Could not reach Urban Dictionary.")

        total = min(len(results), 10)
        pages = [
            build_urban_embed(entry, author=ctx.author, page=index + 1, total=total)
            for index, entry in enumerate(results[:10])
        ]
        await send_pages(ctx, pages)

    @hybrid(
        name="seen",
        description="See when a member was last seen in the server",
        example=",seen @member",
        guild_only=True,
    )
    @describe(member="Member to check")
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def seen(self, ctx: Context, member: discord.Member | None = None) -> None:
        member = member or ctx.author
        cache = getattr(self.bot, "member_last_seen", {})
        last = cache.get((ctx.guild.id, member.id))
        now = discord.utils.utcnow()

        if member.status is not discord.Status.offline:
            label = "now"
        elif last is not None and (now - last).total_seconds() < 60:
            label = "now"
        elif last is not None:
            label = discord.utils.format_dt(last, style="R")
        else:
            label = "a while ago"

        embed = discord.Embed(
            description=f"**{member.display_name}** was last seen {label}",
        )
        await ctx.send(embed=embed)

    @seen.error
    async def seen_error(self, ctx: Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.cooldown(
                f"Please wait **{error.retry_after:.2f} seconds** before using this command again"
            )
