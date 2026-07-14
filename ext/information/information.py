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
from core.tools.aesthetic import label_line, panel_embed, reply_embed

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
    from core.vain import Vain

_CONTEXTS = dict(guilds=True, dms=True, groupchats=True)


class InformationCommands(Package):
    """base mixin for standalone information commands."""

    def __init__(self, bot: Vain):
        super().__init__(bot)

    @hybrid(
        name="botinfo",
        description="View information about the bot, stats, uptime and links",
        aliases=["bi", "stats"],
        example=",botinfo",
    )
    async def botinfo(self, ctx: Context) -> None:
        bot = self.bot
        total_commands = len(set(bot.walk_commands()))
        guilds = len(bot.guilds)
        users = sum(g.member_count or 0 for g in bot.guilds)
        latency = round(bot.latency * 1000)
        uptime = discord.utils.format_dt(bot.started_at, style="R")
        shard_count = bot.shard_count or 1
        info_lines = [
            label_line("Commands", f"`{total_commands}`"),
            label_line("Latency", f"`{latency}ms`"),
            label_line("Uptime", uptime),
            label_line("Guilds", f"`{guilds:,}`"),
            label_line("Users", f"`{users:,}`"),
            label_line("Shards", f"`{shard_count}`"),
            label_line("Python", f"`{platform.python_version()}`"),
        ]
        embed = panel_embed(
            color=color.base,
            title=f"{bot.user.display_name if bot.user else 'Vain'}",
            lines=info_lines,
            timestamp=False,
            thumbnail=bot.user.display_avatar.url if bot.user else None,
        )

        # v2 container for botinfo to be aesthetic and modern
        try:
            cont = discord.ui.Container(accent_colour=color.base)
            cont.add_item(discord.ui.TextDisplay(f"**{bot.user.display_name if bot.user else 'bleed'}**"))
            cont.add_item(discord.ui.TextDisplay("-# bot information"))
            for line in (info_lines or []):
                cont.add_item(discord.ui.TextDisplay(f"-# {line}"))
            cont.add_item(discord.ui.Separator())
            cont.add_item(discord.ui.TextDisplay("-# @hroe • general"))
            comps = [cont]
            await ctx.send(components=comps, flags=discord.MessageFlags.components_v2)
            return
        except Exception:
            pass
        # fallback
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Website",
            style=discord.ButtonStyle.link,
            url="https://vain.bot",
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
        created = discord.utils.format_dt(inv.created_at, style="D") if inv.created_at else "Unknown"
        created_r = f" ({discord.utils.format_dt(inv.created_at, style='R')})" if inv.created_at else ""
        expires = discord.utils.format_dt(inv.expires_at, style="R") if inv.expires_at else "Never"
        inv_url = f"[{inv.code}](https://discord.gg/{inv.code})"
        member_count = inv.approximate_member_count or (guild.member_count if guild else "?")
        online_count = inv.approximate_presence_count or "?"

        embed = panel_embed(
            color=0xFFFFFF,
            author=guild.name if guild else "Invite Info",
            author_icon=guild.icon.url if guild and guild.icon else None,
            lines=[
                label_line("Created", f"{created}{created_r}"),
                label_line("Invite", f"{inv_url} · expires {expires}"),
                label_line("Members", f"`{member_count:,}`"),
                label_line("Online", f"`{online_count:,}`"),
            ],
            timestamp=False,
            thumbnail=guild.icon.url if guild and guild.icon else None,
        )
        if guild and hasattr(guild, "banner") and guild.banner:
            embed.set_image(url=guild.banner.url)
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
        lines = [
            label_line("ID", str(channel.id)),
            label_line("Type", str(channel.type).replace("_", " ").title()),
            label_line(
                "Category",
                channel.category.name if getattr(channel, "category", None) else "None",
            ),
            label_line("Created", discord.utils.format_dt(channel.created_at, style="R")),
        ]
        if isinstance(channel, discord.TextChannel):
            lines.extend([
                label_line("Topic", channel.topic or "None"),
                label_line("NSFW", "Yes" if channel.is_nsfw() else "No"),
                label_line("Slowmode", f"{channel.slowmode_delay}s"),
            ])
        if isinstance(channel, discord.VoiceChannel):
            lines.extend([
                label_line("Bitrate", str(channel.bitrate)),
                label_line("User Limit", str(channel.user_limit or "Unlimited")),
            ])
        embed = panel_embed(
            title=f"#{channel.name}",
            color=color.base,
            lines=lines,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="roleinfo",
        description="View information about a role",
        aliases=["ri"],
        guild_only=True,
    )
    @describe(role="Role to inspect")
    async def roleinfo(self, ctx: Context, role: discord.Role) -> None:
        perms = [name.replace("_", " ").title() for name, value in role.permissions if value]
        embed = panel_embed(
            title=role.name,
            color=role.color if role.color.value else color.base,
            lines=[
                label_line("ID", str(role.id)),
                label_line("Members", str(len(role.members))),
                label_line("Position", str(role.position)),
                label_line("Mentionable", "Yes" if role.mentionable else "No"),
                label_line("Hoisted", "Yes" if role.hoist else "No"),
                label_line("Managed", "Yes" if role.managed else "No"),
                label_line("Created", discord.utils.format_dt(role.created_at, style="R")),
                label_line("Key Permissions", ", ".join(perms[:12]) if perms else "None"),
            ],
            timestamp=False,
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
        lines = [
            label_line("User", member.mention),
            label_line("ID", str(member.id)),
            label_line("Bot", "Yes" if member.bot else "No"),
            label_line("Joined", discord.utils.format_dt(member.joined_at, style="R")),
            label_line("Registered", discord.utils.format_dt(member.created_at, style="R")),
            label_line("Top Role", member.top_role.mention),
            label_line(f"Roles ({len(roles)})", " ".join(roles[:20]) if roles else "None"),
        ]
        if member.premium_since:
            lines.append(
                label_line("Boosting Since", discord.utils.format_dt(member.premium_since, style="R"))
            )
        embed = panel_embed(
            title=member.display_name,
            color=member.color if member.color.value else color.base,
            lines=lines,
            timestamp=False,
            thumbnail=member.display_avatar.url,
        )
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
            lines.append(
                label_line(
                    f"Shard {shard_id}",
                    f"`{len(guilds)}` guilds · `{members:,}` users · `{latency}ms`",
                )
            )
        embed = panel_embed(
            title="Shard Info",
            color=color.base,
            lines=lines or ["Single-shard mode"],
            timestamp=False,
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

        embed = reply_embed(
            color=color.base,
            message=f"**{member.display_name}** was last seen {label}",
        )
        await ctx.send(embed=embed)

    @seen.error
    async def seen_error(self, ctx: Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.cooldown(
                f"Please wait **{error.retry_after:.2f} seconds** before using this command again"
            )
