from __future__ import annotations

import discord
from discord.ext.commands import group, command

from core.discord.package import Package
from core.managers.permissions import has_permissions


class Highlight(Package):
    """highlight management"""

    def __init__(self, bot):
        self.bot = bot

    @group(
        name="highlight",
        aliases=["hl"],
        description="Set notifications for when a keyword is said",
        invoke_without_command=True,
    )
    @has_permissions(guild_owner=True)
    async def highlight(self, ctx):
        """highlight group help"""
        return await ctx.send_help(ctx.command)

    @highlight.command(
        name="add",
        description="Add a highlighted keyword",
    )
    async def highlight_add(self, ctx, *, keyword: str):
        """add highlighted keyword"""
        await self.bot.db.execute(
            "INSERT INTO highlights (guild_id, user_id, keyword) VALUES($1, $2, $3) "
            "ON CONFLICT(guild_id, user_id, keyword) DO NOTHING",
            ctx.guild.id, ctx.author.id, keyword.lower()
        )
        await ctx.success(
            f"Added keyword\n"
            f"> -# **keyword:** `{keyword.lower()}`"
        )

    @highlight.command(
        name="remove",
        description="Remove a highlighted keyword",
    )
    async def highlight_remove(self, ctx, *, keyword: str):
        """remove highlighted keyword"""
        await self.bot.db.execute(
            "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
            ctx.guild.id, ctx.author.id, keyword.lower()
        )
        await ctx.success(
            f"Removed keyword\n"
            f"> -# **keyword:** `{keyword.lower()}`"
        )

    @highlight.command(
        name="list",
        description="List all your highlighted keywords",
    )
    async def highlight_list(self, ctx):
        """list highlighted keywords"""
        highlights = await self.bot.db.fetch(
            "SELECT keyword FROM highlights WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, ctx.author.id
        )

        if not highlights:
            return await ctx.warn(
                "You have no keywords set\n"
                f"> -# **add one with:** `,highlight add <keyword>`"
            )

        keywords = [f"`{h['keyword']}`" for h in highlights]
        await ctx.success(
            f"Your keywords\n"
            f"{', '.join(keywords)}"
        )

    @highlight.command(
        name="reset",
        description="Remove all your highlighted keywords",
    )
    async def highlight_reset(self, ctx):
        """reset all highlights"""
        await self.bot.db.execute(
            "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, ctx.author.id
        )
        await ctx.success("Removed all keywords")

    @highlight.command(
        name="ignore",
        description="Ignore notifications from a member, channel, or role",
    )
    async def highlight_ignore(self, ctx, target: discord.Role | discord.Member | discord.TextChannel):
        """ignore highlight from member/channel/role"""
        if isinstance(target, discord.Member):
            target_type = "user"
            target_id = target.id
            label = target.mention
        elif isinstance(target, discord.Role):
            target_type = "role"
            target_id = target.id
            label = target.mention
        elif isinstance(target, discord.abc.GuildChannel):
            target_type = "channel"
            target_id = target.id
            label = target.mention
        else:
            return await ctx.fail(
                "Please provide a **valid target**\n"
                f"> -# **accepted:** member, role, or channel"
            )

        await self.bot.db.execute(
            "INSERT INTO highlight_ignores (guild_id, user_id, target_id, target_type) "
            "VALUES($1, $2, $3, $4) ON CONFLICT(guild_id, user_id, target_id, target_type) DO NOTHING",
            ctx.guild.id, ctx.author.id, target_id, target_type
        )
        await ctx.success(
            f"Now ignoring\n"
            f"> -# **target:** {label}\n"
            f"> -# **type:** {target_type}"
        )

    @highlight.command(
        name="unignore",
        description="Stop ignoring a member, channel, or role",
    )
    async def highlight_unignore(self, ctx, target: discord.Role | discord.Member | discord.TextChannel):
        """unignore highlight target"""
        if isinstance(target, discord.Member):
            target_type = "user"
            target_id = target.id
            label = target.mention
        elif isinstance(target, discord.Role):
            target_type = "role"
            target_id = target.id
            label = target.mention
        elif isinstance(target, discord.abc.GuildChannel):
            target_type = "channel"
            target_id = target.id
            label = target.mention
        else:
            return await ctx.fail(
                "Please provide a **valid target**\n"
                f"> -# **accepted:** member, role, or channel"
            )

        result = await self.bot.db.execute(
            "DELETE FROM highlight_ignores WHERE guild_id = $1 AND user_id = $2 AND target_id = $3 AND target_type = $4",
            ctx.guild.id, ctx.author.id, target_id, target_type
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"{label} is not ignored\n"
                f"> -# **check with:** `,highlight ignores`"
            )
        await ctx.success(
            f"Stopped ignoring\n"
            f"> -# **target:** {label}"
        )

    @highlight.command(
        name="ignores",
        aliases=["ignorelist", "ignored"],
        description="List all ignored members, channels, and roles",
    )
    async def highlight_ignore_list(self, ctx):
        """list ignored highlights"""
        ignores = await self.bot.db.fetch(
            "SELECT target_id, target_type FROM highlight_ignores WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, ctx.author.id
        )

        if not ignores:
            return await ctx.warn(
                "You have no ignored targets\n"
                f"> -# **ignore with:** `,highlight ignore <target>`"
            )

        lines = []
        for ignore in ignores:
            if ignore['target_type'] == "user":
                member = ctx.guild.get_member(ignore['target_id'])
                if member:
                    lines.append(f"> {member.mention} (user)")
            elif ignore['target_type'] == "role":
                role = ctx.guild.get_role(ignore['target_id'])
                if role:
                    lines.append(f"> {role.mention} (role)")
            elif ignore['target_type'] == "channel":
                channel = ctx.guild.get_channel(ignore['target_id'])
                if channel:
                    lines.append(f"> {channel.mention} (channel)")

        if not lines:
            return await ctx.warn(
                "All ignored targets are no longer in this server\n"
                f"> -# **they may have left or been deleted**"
            )

        await ctx.success(
            f"Ignored targets\n" + "\n".join(lines)
        )
