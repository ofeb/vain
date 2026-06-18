from __future__ import annotations

from discord import Embed, TextChannel
from discord.ext.commands import CommandError, group, has_permissions

from core.discord.package import Package


class SuggestCommands(Package):
    """suggestion channel management"""

    @group(
        name="suggest",
        aliases=["suggestion"],
        description="manage the suggestion channel",
        invoke_without_command=True,
    )
    async def suggest(self, ctx):
        """post a suggestion"""
        await ctx.send_help(ctx.command)

    @suggest.command(
        name="channel",
        aliases=["set"],
        description="set the suggestions channel",
        example=",suggest channel #suggestions",
    )
    @has_permissions(manage_guild=True)
    async def suggest_channel(self, ctx, channel: TextChannel):
        """configure suggestion channel"""
        await self.db.execute(
            """INSERT INTO suggest_config (guild_id, channel_id) VALUES($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET channel_id = excluded.channel_id""",
            ctx.guild.id, channel.id,
        )
        await ctx.success(f"suggestions channel set to {channel.mention}")

    @suggest.command(
        name="add",
        aliases=["submit", "a"],
        description="submit a suggestion",
        example=",suggest add add more music commands",
    )
    async def suggest_add(self, ctx, *, content: str):
        """submit a suggestion"""
        row = await self.db.fetchrow(
            """SELECT channel_id FROM suggest_config WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("no suggestion channel configured")
        ch = ctx.guild.get_channel(row["channel_id"])
        if not ch:
            raise CommandError("suggestion channel not found")
        e = Embed(description=content, color=self.color)
        e.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        msg = await ch.send(embed=e)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await ctx.success(f"suggestion submitted to {ch.mention}")

    @suggest.command(
        name="reset",
        aliases=["disable", "off"],
        description="disable suggestions channel",
    )
    @has_permissions(manage_guild=True)
    async def suggest_reset(self, ctx):
        """remove suggestion config"""
        await self.db.execute(
            """DELETE FROM suggest_config WHERE guild_id = $1""",
            ctx.guild.id,
        )
        await ctx.success("suggestions channel disabled")
