from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from config import color, emojis
from core.managers.permissions import has_permissions



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



if TYPE_CHECKING:
    from .events import ReactionEvents


class Reaction(commands.Cog):
    """Auto-reaction management system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @hybrid(
        name="react",
        description="Add a reaction(s) to a message",
        guild_only=True,
    )
    @describe(message="Message to react to", emoji="Emoji to react with")
    @has_permissions(manage_messages=True)
    async def react(
        self,
        ctx: Context,
        message: discord.Message,
        emoji: str,
    ) -> None:
        """Add a reaction to a message."""
        try:
            await message.add_reaction(emoji)
            await ctx.message.add_reaction(emojis.approve)
        except Exception:
            await ctx.message.add_reaction(emojis.deny)

    @group(
        name="reaction",
        description="Auto-reaction management",
        guild_only=True,
    )
    @has_permissions(manage_expressions=True)
    async def reaction_group(self, ctx: Context) -> None:
        """Auto-reaction management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @reaction_group.command(
        name="clear",
        description="Removes every reaction trigger in guild",
    )
    @has_permissions(manage_expressions=True)
    async def reaction_clear(self, ctx: Context) -> None:
        """Removes every reaction trigger in guild."""
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.success("Cleared auto reactions")

    @reaction_group.command(
        name="add",
        description="Adds a reaction trigger to guild",
    )
    @describe(emoji="Emoji to react with", trigger="Word to trigger reaction")
    @has_permissions(manage_expressions=True)
    async def reaction_add(self, ctx: Context, emoji: str, trigger: str) -> None:
        """Adds a reaction trigger to guild."""
        await ctx.message.add_reaction(emoji)
        await self.bot.db.execute(
            """
            INSERT INTO auto_reactions (guild_id, trigger, response, owner_id, strict)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id, trigger, response)
            DO UPDATE SET response = EXCLUDED.response
            """,
            ctx.guild.id,
            trigger,
            [emoji],
            ctx.author.id,
            True,
        )
        await ctx.success(f"Created reaction trigger `{trigger}`")

    @reaction_group.command(
        name="delete",
        description="Removes a reaction trigger in guild",
    )
    @describe(emoji="Emoji to remove", trigger="Trigger word to remove")
    @has_permissions(manage_expressions=True)
    async def reaction_delete(self, ctx: Context, emoji: str, trigger: str) -> None:
        """Removes a reaction trigger in guild."""
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1 AND trigger = $2 AND response = $3",
            ctx.guild.id,
            trigger,
            [emoji],
        )
        await ctx.success(f"Deleted reaction trigger `{trigger}`")

    @reaction_group.group(
        name="messages",
        description="Add or remove auto reaction on messages",
        guild_only=True,
    )
    @has_permissions(manage_expressions=True)
    async def reaction_messages(self, ctx: Context) -> None:
        """Auto reaction on messages group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @reaction_messages.command(
        name="list",
        description="List auto reactions for all channels",
    )
    @has_permissions(manage_expressions=True)
    async def reaction_messages_list(self, ctx: Context) -> None:
        """List auto reactions for all channels."""
        reactions = await self.bot.db.fetch(
            "SELECT trigger, response FROM auto_reactions WHERE guild_id = $1",
            ctx.guild.id,
        )
        rows = []
        for record in reactions:
            if record.trigger.isnumeric():
                if channel := ctx.guild.get_channel(int(record.trigger)):
                    rows.append(f"{channel.mention} - {''.join(r for r in record.response)}")
        if len(rows) == 0:
            await ctx.warn("No Auto Channel Reactions found")
            return
        rows = [f"`{i}` {row}" for i, row in enumerate(rows, start=1)]
        embed = panel_embed(
            color=color.base,
            title="Auto Channel Reactions",
            author=str(ctx.author),
            author_icon=ctx.author.display_avatar.url,
            lines=rows,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @reaction_group.command(
        name="deleteall",
        description="Removes every reaction trigger for a specific word",
    )
    @describe(trigger_word="Word to delete all triggers for")
    @has_permissions(manage_expressions=True)
    async def reaction_deleteall(self, ctx: Context, trigger_word: str) -> None:
        """Removes every reaction trigger for a specific word."""
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE trigger = $1 AND guild_id = $2",
            trigger_word,
            ctx.guild.id,
        )
        await ctx.success(f"Deleted all auto reactions triggered by `{trigger_word}`")

    @reaction_group.command(
        name="list",
        description="View a list of every reaction trigger in guild",
    )
    @has_permissions(manage_expressions=True)
    async def reaction_list(self, ctx: Context) -> None:
        """View a list of every reaction trigger in guild."""
        reactions = await self.bot.db.fetch(
            "SELECT trigger, response FROM auto_reactions WHERE guild_id = $1",
            ctx.guild.id,
        )
        rows = []
        for record in reactions:
            if record.trigger.isnumeric():
                if channel := ctx.guild.get_channel(int(record.trigger)):
                    continue
            rows.append(f"{record.trigger} - {''.join(r for r in record.response)}")
        rows = [f"`{i}` {row}" for i, row in enumerate(rows, start=1)]
        embed = panel_embed(
            color=color.base,
            title="Reaction Triggers",
            author=str(ctx.author),
            author_icon=ctx.author.display_avatar.url,
            lines=rows,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @reaction_group.command(
        name="owner",
        description="Gets the author of a trigger word",
    )
    @describe(trigger_word="Trigger word to get owner of")
    @has_permissions(manage_expressions=True)
    async def reaction_owner(self, ctx: Context, trigger_word: str) -> None:
        """Gets the author of a trigger word."""
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM auto_reactions WHERE trigger = $1 AND guild_id = $2",
            trigger_word.lower(),
            ctx.guild.id,
        )
        if not owner_id:
            await ctx.fail(f"No reaction trigger found under `{trigger_word}`")
            return
        user = self.bot.get_user(owner_id)
        if not user:
            user = await self.bot.fetch_user(owner_id)
        await ctx.normal(f"Reaction Trigger `{trigger_word}` author is `{str(user)}`", emoji="ℹ️")


async def setup(bot: commands.Bot):
    await bot.add_cog(Reaction(bot))
