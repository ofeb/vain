from __future__ import annotations

import contextlib
import re
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands
from discord.ext.commands import group

from core.discord.package import Package
from core.discord.views.embed import c2
from core.managers.permissions import has_permissions
from core.tools.moderation_args import parse_duration_seconds, is_duration_token
from .events import HighlightEvents
from .settings import Settings


_PUNISHMENTS = ("none", "ban", "softban", "hardban", "warn", "timeout")


class Highlight(HighlightEvents, Package):
    """Keyword highlights with optional log destination and punishment."""

    def __init__(self, bot):
        Package.__init__(self, bot)
        HighlightEvents.__init__(self, bot)

    async def cog_load(self) -> None:
        await Settings.ensure_schema(self.bot.db)
        await super().cog_load()

    async def _get_config(self, guild_id: int) -> dict:
        return await Settings.get_config(self.bot.db, guild_id)

    @group(
        name="highlight",
        aliases=["hl"],
        description="set notifications for when a keyword is said",
        invoke_without_command=True,
    )
    @has_permissions(guild_owner=True)
    async def highlight(self, ctx):
        return await ctx.send_help(ctx.command)

    @highlight.command(name="add", description="add a highlighted keyword")
    async def highlight_add(self, ctx, *, keyword: str):
        kw = keyword.strip().lower()
        if not kw:
            return await ctx.warn("Provide a keyword")
        await Settings.add_highlight(self.bot.db, ctx.guild.id, ctx.author.id, kw)
        return await ctx.success(f"Added keyword\n> -# **keyword:** `{kw}`")

    @highlight.command(name="remove", description="remove a highlighted keyword", aliases=["rm", "del"])
    async def highlight_remove(self, ctx, *, keyword: str):
        kw = keyword.strip().lower()
        await Settings.remove_highlight(self.bot.db, ctx.guild.id, ctx.author.id, kw)
        return await ctx.success(f"Removed keyword\n> -# **keyword:** `{kw}`")

    @highlight.command(name="list", description="list all your highlighted keywords", aliases=["ls"])
    async def highlight_list(self, ctx):
        rows = await Settings.fetch_highlights(self.bot.db, ctx.guild.id, ctx.author.id)
        if not rows:
            return await ctx.warn(
                "You have no keywords set\n"
                f"> -# **add one with:** {ctx.cmd('highlight add <keyword>')}"
            )
        keywords = [f"`{h['keyword']}`" for h in rows]
        return await ctx.success(f"Your keywords\n{', '.join(keywords)}")

    @highlight.command(name="reset", description="remove all your highlighted keywords")
    async def highlight_reset(self, ctx):
        await Settings.reset_highlights(self.bot.db, ctx.guild.id, ctx.author.id)
        return await ctx.success("Cleared all your highlighted keywords")

    @highlight.command(
        name="type",
        description="where highlight logs are sent (dm or channel)",
        example=",highlight type channel #logs",
    )
    @has_permissions(manage_guild=True)
    async def highlight_type(self, ctx, kind: str = None, channel: discord.TextChannel = None):
        """Set highlight log destination: dm or channel."""
        if not kind:
            cfg = await self._get_config(ctx.guild.id)
            if cfg["log_type"] == "channel" and cfg.get("log_channel_id"):
                return await ctx.normal(
                    f"Highlight logs go to <#{cfg['log_channel_id']}>\n"
                    f"> -# **change with:** {ctx.cmd('highlight type dm')} or "
                    f"{ctx.cmd('highlight type channel #channel')}"
                )
            return await ctx.normal(
                "Highlight logs are sent via **DM**\n"
                f"> -# **change with:** {ctx.cmd('highlight type channel #channel')}"
            )

        kind = kind.strip().lower()
        if kind in {"dm", "dms", "direct"}:
            await Settings.set_log_type_dm(self.bot.db, ctx.guild.id)
            return await ctx.success("Highlight logs will be sent via **DM**")

        if kind in {"channel", "ch", "log", "logs"}:
            dest = channel
            if dest is None and ctx.message.channel_mentions:
                dest = ctx.message.channel_mentions[0]
            if dest is None:
                return await ctx.warn(
                    "Provide a channel\n"
                    f"> -# **usage:** {ctx.cmd('highlight type channel #channel')}"
                )
            await Settings.set_log_type_channel(self.bot.db, ctx.guild.id, dest.id)
            return await ctx.success(f"Highlight logs will post in {dest.mention}")

        return await ctx.warn(
            "Type must be **dm** or **channel**\n"
            f"> -# **usage:** {ctx.cmd('highlight type dm')} · "
            f"{ctx.cmd('highlight type channel #channel')}"
        )

    @highlight.command(
        name="punishment",
        aliases=["punish", "action"],
        description="punishment when a highlighted keyword is used",
        example=",highlight punishment timeout 10m --delete 5s",
    )
    @has_permissions(manage_guild=True)
    async def highlight_punishment(self, ctx, *, args: str = None):
        """Set punishment: ban, softban, hardban, warn, timeout <amount>, or none.
        Optional --delete <duration> to delete the triggering message after that delay.
        """
        if not args or not str(args).strip():
            cfg = await self._get_config(ctx.guild.id)
            pun = cfg.get("punishment") or "none"
            extra = ""
            if pun == "timeout" and cfg.get("timeout_seconds"):
                extra = f" ({cfg['timeout_seconds']}s)"
            delete_info = "off"
            if cfg.get("delete_after_seconds"):
                delete_info = f"{cfg['delete_after_seconds']}s"
            return await ctx.normal(
                f"Highlight punishment is **{pun}**{extra}\n"
                f"> -# **delete after:** {delete_info}\n"
                f"> -# **set with:** {ctx.cmd('highlight punishment timeout 10m --delete 5s')}"
            )

        tokens = args.split()
        delete_after = None
        
        cleaned = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            low = tok.lower()
            if low in {"--delete", "-delete", "--del", "-del"}:
                if i + 1 < len(tokens) and is_duration_token(tokens[i + 1]):
                    delete_after = parse_duration_seconds(tokens[i + 1])
                    i += 2
                    continue
                
                delete_after = 0
                i += 1
                continue
            if low.startswith("--delete=") or low.startswith("-delete="):
                raw = tok.split("=", 1)[1]
                if is_duration_token(raw):
                    delete_after = parse_duration_seconds(raw)
                i += 1
                continue
            cleaned.append(tok)
            i += 1

        if not cleaned:
            return await ctx.warn(
                "Provide a punishment\n"
                f"> -# **options:** `none` `ban` `softban` `hardban` `warn` `timeout <amount>`"
            )

        action = cleaned[0].lower()
        timeout_seconds = None

        if action in {"none", "off", "disable"}:
            action = "none"
        elif action in {"ban", "softban", "hardban", "warn"}:
            pass
        elif action == "timeout":
            if len(cleaned) < 2 or not is_duration_token(cleaned[1]):
                return await ctx.warn(
                    "Provide a timeout duration\n"
                    f"> -# **usage:** {ctx.cmd('highlight punishment timeout 10m')}"
                )
            timeout_seconds = parse_duration_seconds(cleaned[1])
            if not timeout_seconds or timeout_seconds < 1:
                return await ctx.warn("Invalid timeout duration")
        else:
            
            return await ctx.warn(
                f"Unknown punishment `{action}`\n"
                f"> -# **options:** `none` `ban` `softban` `hardban` `warn` `timeout <amount>`"
            )

        await Settings.set_punishment(
            self.bot.db,
            ctx.guild.id,
            action,
            timeout_seconds,
            delete_after,
        )

        bits = [f"Highlight punishment set to **{action}**"]
        if timeout_seconds:
            bits.append(f"> -# **timeout:** {timeout_seconds}s")
        if delete_after is not None:
            bits.append(f"> -# **delete after:** {delete_after}s")
        else:
            bits.append("> -# **delete after:** off")
        return await ctx.success("\n".join(bits))

    @highlight.command(name="ignore", description="ignore highlights from a member, role, or channel")
    async def highlight_ignore(self, ctx, target: discord.Role | discord.Member | discord.TextChannel):
        if isinstance(target, discord.Member):
            ttype, label = "user", target.mention
        elif isinstance(target, discord.Role):
            ttype, label = "role", target.mention
        else:
            ttype, label = "channel", target.mention
        await Settings.add_ignore(self.bot.db, ctx.guild.id, ctx.author.id, target.id, ttype)
        return await ctx.success(f"Ignoring highlights from {label}")

    @highlight.command(name="unignore", description="stop ignoring a member, role, or channel")
    async def highlight_unignore(self, ctx, target: discord.Role | discord.Member | discord.TextChannel):
        if isinstance(target, discord.Member):
            ttype = "user"
        elif isinstance(target, discord.Role):
            ttype = "role"
        else:
            ttype = "channel"
        await Settings.remove_ignore(self.bot.db, ctx.guild.id, ctx.author.id, target.id, ttype)
        return await ctx.success(f"No longer ignoring {target.mention}")

    @highlight.command(name="ignorelist", aliases=["ignores"], description="list ignored targets")
    async def highlight_ignore_list(self, ctx):
        ignores = await Settings.fetch_ignores(self.bot.db, ctx.guild.id, ctx.author.id)
        if not ignores:
            return await ctx.warn(
                "You aren't ignoring anyone\n"
                f"> -# **ignore with:** {ctx.cmd('highlight ignore <target>')}"
            )
        lines = []
        for ignore in ignores:
            if ignore["target_type"] == "user":
                member = ctx.guild.get_member(ignore["target_id"])
                if member:
                    lines.append(f"> {member.mention} (user)")
            elif ignore["target_type"] == "role":
                role = ctx.guild.get_role(ignore["target_id"])
                if role:
                    lines.append(f"> {role.mention} (role)")
            elif ignore["target_type"] == "channel":
                channel = ctx.guild.get_channel(ignore["target_id"])
                if channel:
                    lines.append(f"> {channel.mention} (channel)")
        if not lines:
            return await ctx.warn("All ignored targets are gone from this server")
        return await ctx.success("Ignored targets\n" + "\n".join(lines))
