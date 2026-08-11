from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from config import color, emojis
from core.managers.permissions import has_permissions

from .settings import Settings as AutoroleSettings

from core.discord.views.embed import panel_embed

if TYPE_CHECKING:
    from .events import AutoroleEvents

EMOJI_REGEX = re.compile(
    r"<(?P<animated>a?):(?P<name>[a-zA-Z0-9_]{2,32}):(?P<id>[0-9]{18,22})>"
)
DEFAULT_EMOJIS = re.compile(
    r"[\U0001F300-\U0001F5FF]|[\U0001F600-\U0001F64F]|[\U0001F680-\U0001F6FF]|[\U0001F700-\U0001F77F]|[\U0001F780-\U0001F7FF]|[\U0001F800-\U0001F8FF]|[\U0001F900-\U0001F9FF]|[\U0001FA00-\U0001FA6F]|[\U0001FA70-\U0001FAFF]|[\U00002702-\U000027B0]|[\U000024C2-\U0001F251]|[\U0001F910-\U0001F9C0]|[\U0001F3A0-\U0001F3FF]"
)

class Autorole(commands.Cog):
    """Automatic role assignment system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @group(
        name="autorole",
        description="Set up automatic role assign on member join",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def autorole(self, ctx: Context) -> None:
        """Autorole management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @autorole.command(
        name="list",
        description="View a list of every auto role",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def autorole_list(self, ctx: Context) -> None:
        """View a list of every auto role."""
        settings = await AutoroleSettings.fetch(self.bot, ctx.guild)
        role_ids = settings.rows
        if not role_ids:
            await ctx.warn("No auto roles\n> -# **use `autorole add` to configure one**")
            return
        
        roles = [
            ctx.guild.get_role(r["role_id"]).mention
            for r in role_ids
            if ctx.guild.get_role(r["role_id"])
        ]
        rows = [f"`{i}` {r}" for i, r in enumerate(roles, start=1)]
        embed = panel_embed(title="Auto Roles", color=color.base, lines=rows, timestamp=False)
        await ctx.send(embed=embed)

    @autorole.command(
        name="remove",
        description="Removes a autorole and stops assigning on join",
        guild_only=True,
    )
    @describe(role="Role to remove from auto role")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def autorole_remove(self, ctx: Context, role: discord.Role) -> None:
        """Removes a autorole and stops assigning on join."""
        await self.bot.db.execute(
            "DELETE FROM auto_role WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )
        await ctx.success(f"Auto role removed\n> -# **{role.mention}**")

    @autorole.command(
        name="reset",
        description="Clears every autorole for guild",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def autorole_reset(self, ctx: Context) -> None:
        """Clears every autorole for guild."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        emb = discord.Embed(
            color=color.base,
            description=(
                "This will **clear every autorole** for this server.\n"
                "This action **cannot be undone**.\n"
                "Are you sure you want to do this?\n"
            ),
        )
        if not await view.prompt(embed=emb):
            return await ctx.warn("Cancelled\n> -# **no autoroles were removed**")
        settings = await AutoroleSettings.fetch(self.bot, ctx.guild)
        await settings.delete_all()
        await ctx.success(
            "Auto roles cleared\n> -# **this action cannot be undone**"
        )

    @autorole.command(
        name="add",
        description="Adds a autorole and assigns on join to member",
        guild_only=True,
    )
    @describe(role="Role to add as auto role")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def autorole_add(self, ctx: Context, role: discord.Role) -> None:
        """Adds a autorole and assigns on join to member."""
        await self.bot.db.execute(
            "INSERT INTO auto_role (guild_id, role_id) VALUES($1, $2) ON CONFLICT(guild_id, role_id) DO NOTHING",
            ctx.guild.id,
            role.id,
        )
        await ctx.success(f"Auto role added\n> -# **{role.mention}**")

    @group(
        name="buttonrole",
        description="Button role management",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def buttonrole(self, ctx: Context) -> None:
        """Button role management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @buttonrole.command(
        name="remove",
        description="Remove a button role from a message",
        guild_only=True,
    )
    @describe(message="Message to remove button role from", index="Index of button to remove")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def buttonrole_remove(self, ctx: Context, message: discord.Message, index: int) -> None:
        """Remove a button role from a message."""
        entries = await self.bot.db.fetch(
            "SELECT index FROM button_roles WHERE message_id = $1 ORDER BY index ASC",
            message.id,
        )
        if index > len(entries):
            index = len(entries)
        
        await self.bot.db.execute(
            "DELETE FROM button_roles WHERE message_id = $1 AND index = $2",
            message.id,
            entries[index - 1].index,
        )
        
        await message.edit(view=None)
        await ctx.success(f"Button removed\n> -# **[message]({message.jump_url})**")

    @buttonrole.command(
        name="reset",
        description="Clears every button role from guild",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def buttonrole_reset(self, ctx: Context) -> None:
        """Clears every button role from guild."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        emb = discord.Embed(
            color=color.base,
            description=(
                "This will **clear every button role** for this server.\n"
                "This action **cannot be undone**.\n"
                "Are you sure you want to do this?\n"
            ),
        )
        if not await view.prompt(embed=emb):
            return await ctx.warn("Cancelled\n> -# **no button roles were removed**")
        for row in await self.bot.db.fetch(
            "SELECT message_id, channel_id FROM button_roles WHERE guild_id = $1",
            ctx.guild.id,
        ):
            channel = ctx.guild.get_channel(row.channel_id)
            if not channel:
                continue
            try:
                message = await channel.fetch_message(row.message_id)
            except Exception:
                continue
            await message.edit(view=None)
        
        await self.bot.db.execute(
            "DELETE FROM button_roles WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.success(
            "Button roles cleared\n> -# **this action cannot be undone**"
        )

    @buttonrole.command(
        name="removeall",
        description="Removes all button roles from a message",
        guild_only=True,
    )
    @describe(message="Message to remove all button roles from")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def buttonrole_removeall(self, ctx: Context, message: discord.Message) -> None:
        """Removes all button roles from a message."""
        await message.edit(view=None)
        await self.bot.db.execute(
            "DELETE FROM button_roles WHERE message_id = $1",
            message.id,
        )
        await ctx.success(f"Button roles removed\n> -# **[message]({message.jump_url})**")

    @buttonrole.command(
        name="list",
        description="View a list of every button role",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def buttonrole_list(self, ctx: Context) -> None:
        """View a list of every button role."""
        rows = []
        i = 0
        for row in await self.bot.db.fetch(
            "SELECT message_id, channel_id, role_id FROM button_roles WHERE guild_id = $1 ORDER BY index ASC",
            ctx.guild.id,
        ):
            if not (channel := ctx.guild.get_channel(row.channel_id)):
                asyncio.ensure_future(
                    self.bot.db.execute(
                        "DELETE FROM button_roles WHERE channel_id = $1 AND guild_id = $2",
                        row.channel_id,
                        ctx.guild.id,
                    )
                )
                continue
            try:
                message = await channel.fetch_message(row.message_id)
            except Exception:
                asyncio.ensure_future(
                    self.bot.db.execute(
                        "DELETE FROM button_roles WHERE message_id = $1 AND guild_id = $2",
                        row.message_id,
                        ctx.guild.id,
                    )
                )
                continue
            if not (role := ctx.guild.get_role(row.role_id)):
                asyncio.ensure_future(
                    self.bot.db.execute(
                        "DELETE FROM button_roles WHERE role_id = $1 AND guild_id = $2",
                        row.role_id,
                        ctx.guild.id,
                    )
                )
                continue
            i += 1
            rows.append(f"`{i}` {role.mention} - [message]({message.jump_url})")

        embed = panel_embed(
            color=color.base,
            title="Button roles",
            author=str(ctx.author),
            author_icon=ctx.author.display_avatar.url,
            lines=rows,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @buttonrole.command(
        name="add",
        description="Add a button role to a message",
        guild_only=True,
    )
    @describe(message="Message to add button to", role="Role to assign", style="Button style", emoji="Button emoji", label="Button label")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def buttonrole_add(
        self,
        ctx: Context,
        message: discord.Message,
        role: discord.Role,
        style: discord.ButtonStyle,
        emoji: str = None,
        label: str = None,
    ) -> None:
        """Add a button role to a message."""
        if message.author.id != self.bot.user.id:
            await ctx.warn("Invalid message\n> -# **the message must be sent by this bot**")
            return
        if not emoji and not label:
            await ctx.warn("Missing input\n> -# **provide an emoji or label for the button**")
            return
        
        indexes = await self.bot.db.fetch(
            "SELECT index FROM button_roles WHERE message_id = $1 ORDER BY index ASC",
            message.id,
        )
        try:
            index = indexes[-1].index + 1
        except Exception:
            index = 1
        
        if len(label) > 100:
            await ctx.warn("Label too long\n> -# **button labels must be 100 characters or fewer**")
            return
        
        await self.bot.db.execute(
            "INSERT INTO button_roles (guild_id, message_id, channel_id, role_id, style, emoji, label, index) VALUES($1, $2, $3, $4, $5, $6, $7, $8)",
            ctx.guild.id,
            message.id,
            message.channel.id,
            role.id,
            style,
            emoji,
            label,
            index,
        )
        await ctx.success("Button role added")

    @group(
        name="reactionrole",
        description="Set up self-assignable roles with reactions",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def reactionrole(self, ctx: Context) -> None:
        """Reaction role management group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @reactionrole.command(
        name="removeall",
        description="Removes all reaction roles from a message",
        guild_only=True,
    )
    @describe(message="Message to remove all reaction roles from")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def reactionrole_removeall(self, ctx: Context, message: discord.Message) -> None:
        """Removes all reaction roles from a message."""
        await self.bot.db.execute(
            "DELETE FROM reaction_role WHERE guild_id = $1 AND message_id = $2",
            ctx.guild.id,
            message.id,
        )
        await ctx.success(f"Reaction roles cleared\n> -# **[message]({message.jump_url})**")

    @reactionrole.command(
        name="reset",
        description="Clears every reaction role from guild",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def reactionrole_reset(self, ctx: Context) -> None:
        """Clears every reaction role from guild."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        emb = discord.Embed(
            color=color.base,
            description=(
                "This will **clear every reaction role** for this server.\n"
                "This action **cannot be undone**.\n"
                "Are you sure you want to do this?\n"
            ),
        )
        if not await view.prompt(embed=emb):
            return await ctx.warn("Cancelled\n> -# **no reaction roles were removed**")
        await self.bot.db.execute(
            "DELETE FROM reaction_role WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.success(
            "Reaction roles cleared\n> -# **this action cannot be undone**"
        )

    @reactionrole.command(
        name="remove",
        description="Removes a reaction role from a message",
        guild_only=True,
    )
    @describe(message="Message to remove reaction role from", emoji="Emoji to remove")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def reactionrole_remove(self, ctx: Context, message: discord.Message, emoji: str) -> None:
        """Removes a reaction role from a message."""
        await self.bot.db.execute(
            "DELETE FROM reaction_role WHERE guild_id = $1 AND message_id = $2 AND emoji = $3",
            ctx.guild.id,
            message.id,
            str(emoji),
        )
        await ctx.success("Reaction role removed")

    @reactionrole.command(
        name="list",
        description="View a list of every reaction role",
        guild_only=True,
    )
    @has_permissions(manage_guild=True, manage_roles=True)
    async def reactionrole_list(self, ctx: Context) -> None:
        """View a list of every reaction role."""
        def get_message_link(row):
            return f"https://discord.com/channels/{row.guild_id}/{row.channel_id}/{row.message_id}"

        def get_row(row):
            if not (role := ctx.guild.get_role(row.role_id)):
                return None
            return f"{str(row.emoji)} [{row.message_id}]({get_message_link(row)}) {role.mention}"

        rows = await self.bot.db.fetch(
            "SELECT * FROM reaction_role WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not rows:
            await ctx.warn("No reaction roles\n> -# **use `reactionrole add` to configure one**")
            return
        
        rows = [
            f"`{i}` {row}"
            for i, row in enumerate([get_row(r) for r in rows if get_row(r)], start=1)
        ]
        embed = panel_embed(title="Reaction Roles", color=color.base, lines=rows, timestamp=False)
        await ctx.send(embed=embed)

    @reactionrole.command(
        name="add",
        description="Adds a reaction role to a message",
        guild_only=True,
    )
    @describe(message="Message to add reaction role to", emoji="Emoji to react with", role="Role to assign")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def reactionrole_add(
        self,
        ctx: Context,
        message: discord.Message,
        emoji: str,
        role: discord.Role,
    ) -> None:
        """Adds a reaction role to a message."""
        try:
            await message.add_reaction(emoji)
        except Exception:
            await ctx.warn(f"Invalid emoji\n> -# **`{emoji}` is not a valid emoji**")
            return
        
        await self.bot.db.execute(
            "INSERT INTO reaction_role (guild_id, channel_id, message_id, emoji, role_id) VALUES($1, $2, $3, $4, $5) ON CONFLICT(guild_id, channel_id, message_id, role_id) DO UPDATE SET emoji = excluded.emoji",
            ctx.guild.id,
            message.channel.id,
            message.id,
            str(emoji),
            role.id,
        )
        await ctx.success(f"Reaction role added\n> -# **[message]({message.jump_url})**")

async def setup(bot: commands.Bot):
    """Load the Autorole cog."""
    await bot.add_cog(Autorole(bot))
