from __future__ import annotations

import platform
from typing import Any, Iterable, Sequence, TYPE_CHECKING

import aiohttp
import discord
from discord import ui
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.discord.package import Package
from core.discord.views.paginate import send_pages
from config import color
import asyncio
from io import BytesIO
from colorthief import ColorThief


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"

def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def panel_embed(
    *,
    color: int | None = None,
    title: str | None = None,
    author: str | None = None,
    author_icon: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    timestamp: bool = True,
    thumbnail: str | None = None,
    url: str | None = None,
) -> discord.Embed:
    description = compose(
        body(*(lines or [])),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description or None, url=url)
    if title:
        embed.title = title
    if author:
        if author_icon:
            embed.set_author(name=author, icon_url=author_icon)
        else:
            embed.set_author(name=author)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed

def panel_container(
    *,
    accent: int | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    thumbnail: str | None = None,
    buttons: Sequence[ui.Button] | None = None,
) -> ui.Container:
    """Build a clean panel container with separators (preferred over panel_embed)."""
    c = ui.Container(accent_colour=accent)

    header = f"**{title}**" if title else None
    if header and thumbnail:
        try:
            body_text = header if not subtitle else f"{header}\n-# {subtitle}"
            c.add_item(
                ui.Section(
                    ui.TextDisplay(body_text),
                    accessory=ui.Thumbnail(media=str(thumbnail)),
                )
            )
        except Exception:
            c.add_item(ui.TextDisplay(header))
            if subtitle:
                c.add_item(ui.TextDisplay(f"-# {subtitle}"))
    elif header:
        c.add_item(ui.TextDisplay(header))
        if subtitle:
            c.add_item(ui.TextDisplay(f"-# {subtitle}"))
    elif subtitle:
        c.add_item(ui.TextDisplay(f"-# {subtitle}"))

    if lines:
        if header or subtitle:
            c.add_item(ui.Separator(visible=True))
        c.add_item(ui.TextDisplay(body(*lines)))

    if footer:
        c.add_item(ui.Separator(visible=True))
        c.add_item(ui.TextDisplay(caption(footer)))

    if buttons:
        c.add_item(ui.Separator(visible=True))
        for i in range(0, len(list(buttons)), 5):
            chunk = list(buttons)[i : i + 5]
            c.add_item(ui.ActionRow(*chunk))

    return c

def layout_from_items(
    items: Iterable[ui.Item],
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    layout = ui.LayoutView(timeout=timeout)
    for item in items:
        layout.add_item(item)
    return layout

def panel_layout(**kwargs: Any) -> ui.LayoutView:
    return layout_from_items([panel_container(**kwargs)])

def c2(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed

def reply_embed(
    *,
    color: int,
    message: str,
    subtitle: str | None = None,
) -> discord.Embed:
    return c2(color=color, message=message, footer=subtitle, timestamp=False)

async def get_dominant_color(url: str, fallback: int = 0x5865F2) -> int:
    """Fetch image and return dominant color using colorthief."""
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
    return 0x5865F2



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
        description="View information about the bot, stats, uptime, shards and invite links",
        aliases=["bi", "stats"],
        usage="",
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
        started = discord.utils.format_dt(bot.started_at, style="F")

        try:
            dom_color = await get_bot_dominant_color(bot)
        except Exception:
            dom_color = color.base or 0x5865F2

        info_lines = [
            label_line("Commands", f"`{total_commands}`"),
            label_line("Latency", f"`{latency}ms`"),
            label_line("Uptime", uptime),
            label_line("Guilds", f"`{guilds:,}`"),
            label_line("Users", f"`{users:,}`"),
            label_line("Shards", f"`{shard_count}`"),
            label_line("Python", f"`{platform.python_version()}`"),
            label_line("Started", started),
        ]

        bot_name = bot.user.display_name if bot.user else "vain"
        thumb = bot.user.display_avatar.url if bot.user else None

        buttons = [
            discord.ui.Button(
                label="Website",
                style=discord.ButtonStyle.link,
                url="https://vain.bot",
            ),
        ]
        if bot.user:
            buttons.append(
                discord.ui.Button(
                    label="Invite",
                    style=discord.ButtonStyle.link,
                    url=(
                        f"https://discord.com/oauth2/authorize?client_id={bot.user.id}"
                        f"&scope=bot+applications.commands&permissions=8"
                    ),
                )
            )
        buttons.append(
            discord.ui.Button(
                label="Support",
                style=discord.ButtonStyle.link,
                url="https://discord.gg/vainbot",
            )
        )

        layout = panel_layout(
            accent=dom_color,
            title=bot_name,
            subtitle="Bot Information",
            lines=info_lines,
            thumbnail=thumb,
            buttons=buttons,
        )
        await ctx.send(view=layout)

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
        try:
            dom = await get_bot_dominant_color(self.bot)
        except Exception:
            dom = color.base
        embed = panel_embed(
            title=f"#{channel.name}",
            color=dom,
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
        try:
            dom = await get_bot_dominant_color(self.bot)
        except Exception:
            dom = color.base
        embed = panel_embed(
            title=role.name,
            color=role.color if role.color.value else dom,
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
        try:
            dom = await get_bot_dominant_color(self.bot)
        except Exception:
            dom = color.base
        embed = panel_embed(
            title=member.display_name,
            color=member.color if member.color.value else dom,
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
        try:
            dom = await get_bot_dominant_color(self.bot)
        except Exception:
            dom = color.base
        embed = panel_embed(
            title="Shard Info",
            color=dom,
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
        from config import api

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


from discord.ext import commands

from core.discord.mixin import _Meta

from .extended.sticker import Sticker
from .extended.emoji import Emoji
from .extended.highlight import Highlight
from .extended.birthday import Birthday
from .extended.timezone import Timezone
from .extended.roblox import Roblox
from .extended.snapchat import Snapchat


class Information(
    InformationCommands,
    Sticker,
    Emoji,
    Highlight,
    Birthday,
    Timezone,
    Roblox,
    Snapchat,
    commands.Cog,
    metaclass=_Meta,
):
    """main information extension — all subcommands combined"""


async def setup(bot) -> None:
    """load information extension"""
    from .events import InformationEvents

    await bot.add_cog(Information(bot))
    await bot.add_cog(InformationEvents(bot))
