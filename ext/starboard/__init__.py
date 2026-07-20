from __future__ import annotations

import json
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.managers.values import color, emojis

from .settings import Settings as StarboardSettings



def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def aesthetic_embed(
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
    return aesthetic_embed(color=color, message=message, footer=subtitle, timestamp=False)



if TYPE_CHECKING:
    from .events import StarboardEvents


def _toggle_emoji(enabled: bool) -> str:
    """Map a boolean to success/fail emoji."""
    return emojis.approve if enabled else emojis.deny


class HexColor(commands.Converter):
    """Resolve color-like argument to hex string."""

    async def convert(self, ctx: Context, argument: str) -> str:
        colour = await commands.ColourConverter().convert(ctx, argument)
        return format(colour.value, "06x")


def requires_starboard():
    """Ensure starboard is configured before subcommand runs."""
    async def predicate(ctx: Context) -> bool:
        if await StarboardSettings.exists(ctx.bot, ctx.guild):
            return True
        raise commands.CommandError(
            f"**starboard** hasn't been setup using `{ctx.prefix}starboard set`"
        )
    return commands.check(predicate)


class ResetConfirm(discord.ui.View):
    """Approve/decline prompt for resetting starboard."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(timeout=15)
        self.ctx = ctx
        self.value: bool | None = None
        self.message: discord.Message | None = None

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user == self.ctx.author:
            return True
        embed = reply_embed(
            color=color.base,
            message=(
                f"{emojis.warn} {interaction.user.mention}: "
                f"Only {self.ctx.author.mention} can use this!"
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        guild_id = self.ctx.guild.id
        await self.ctx.bot.db.execute(
            "DELETE FROM starboard_entries WHERE guild_id = $1", guild_id
        )
        await self.ctx.bot.db.execute(
            "DELETE FROM starboard WHERE guild_id = $1", guild_id
        )
        embed = reply_embed(
            color=color.base,
            message=f"{emojis.approve} {self.ctx.author.mention}: starboard has been **reset**",
        )
        if self.message is not None:
            await self.message.edit(embed=embed, view=None)
        self.value = True
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._guard(interaction):
            return
        if self.message is not None:
            await self.message.delete()
        self.value = False
        self.stop()


class Starboard(commands.Cog):
    """Showcase the best messages in your server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @hybrid(
        name="starboard",
        description="Showcase the best messages in your server",
        guild_only=True,
        invoke_without_command=True,
    )
    async def starboard(self, ctx: Context) -> None:
        """Main starboard command group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @starboard.command(name="emoji")
    @describe(emoji="Emoji that triggers starboard messages")
    @requires_starboard()
    async def starboard_emoji(self, ctx: Context, emoji: str) -> None:
        """Sets the emoji that triggers the starboard messages."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(emoji=str(emoji))
        await ctx.success(f"successfully set the starboard emoji as {str(emoji)}")

    @starboard.command(name="config")
    @requires_starboard()
    async def starboard_config(self, ctx: Context) -> None:
        """View the settings for starboard in guild."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        if not settings:
            return await ctx.fail(
                "**starboard** hasn't been setup using `{ctx.prefix}starboard set`"
            )

        channel_mention = settings.channel.mention if settings.channel else "No channel set"
        color_display = f"`#{settings.color}`" if settings.color else "Author color"
        general_value = body(
            f"**Channel:** {channel_mention}",
            f"**Color:** {color_display}",
            f"**Threshold:** {settings.threshold}",
            f"**Emoji:** {settings.emoji}",
        )
        options_value = body(
            f"**Show Attachments:** {_toggle_emoji(bool(settings.attachments))}",
            f"**Show Timestamps:** {_toggle_emoji(bool(settings.ts))}",
            f"**Show Jump URL:** {_toggle_emoji(bool(settings.jump))}",
            f"**Self Star:** {_toggle_emoji(bool(settings.self_star) if settings.self_star is not None else True)}",
        )

        roles = channels = members = 0
        if settings.ignore_entries:
            raw = settings.ignore_entries
            entries = json.loads(raw) if isinstance(raw, str) else (raw or [])
            for snowflake in entries:
                if ctx.guild.get_channel(snowflake):
                    channels += 1
                elif ctx.guild.get_member(snowflake):
                    members += 1
                elif ctx.guild.get_role(snowflake):
                    roles += 1

        count_value = body(
            f"**Blacklisted Channels:** {channels}",
            f"**Blacklisted Users:** {members}",
            f"**Blacklisted Roles:** {roles}",
        )
        embed = aesthetic_embed(
            color=color.base,
            title="Starboard configuration",
            message=f"**Locked:** {_toggle_emoji(bool(settings.lock))}",
        )
        embed.add_field(name="General", value=general_value, inline=True)
        embed.add_field(name="Options", value=options_value, inline=True)
        embed.add_field(name="Count", value=count_value, inline=True)
        await ctx.send(embed=embed)

    @starboard.command(name="attachments")
    @describe(setting="Enable or disable attachments")
    @requires_starboard()
    async def starboard_attachments(self, ctx: Context, setting: bool) -> None:
        """Allow attachments to appear on Starboard posts."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(attachments=setting)
        await ctx.success(
            f"successfully **{'enabled' if setting else 'disabled'}** starboard attachments"
        )

    @starboard.command(name="set")
    @describe(channel="Channel where starboard messages will be sent", emoji="Emoji that triggers starboard", threshold="Reactions needed")
    async def starboard_set(
        self,
        ctx: Context,
        channel: discord.TextChannel | discord.Thread | None = None,
        emoji: str = "⭐",
        threshold: int = 1,
    ) -> None:
        """Sets the channel where starboard messages will be sent to."""
        channel = channel or ctx.channel
        if await StarboardSettings.exists(self.bot, ctx.guild):
            return await ctx.fail(
                f"**starboard** has already been setup. Use `{ctx.prefix}starboard reset` to reset"
            )
        try:
            await ctx.message.add_reaction(emoji)
        except discord.HTTPException:
            return await ctx.fail(f"**{emoji}** is not a valid emoji")
        note = "" if threshold == 1 else f"with a threshold of `{threshold}`"
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(
            channel_id=channel.id,
            emoji=emoji,
            threshold=threshold,
        )
        await ctx.success(
            f"**starboard** channel has been set to {channel.mention} using **{emoji}** {note}"
        )

    @starboard.command(name="unlock")
    @requires_starboard()
    async def starboard_unlock(self, ctx: Context) -> None:
        """Enables/unlocks starboard from operating."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        if not settings.lock:
            return await ctx.fail(
                f"**starboard** is **already unlocked**, use `{ctx.prefix}starboard lock` to lock"
            )
        await settings.upsert(lock=False)
        await ctx.success(
            f"**starboard** has been **unlocked**, use `{ctx.prefix}starboard lock` to revert"
        )

    @starboard.command(name="color")
    @describe(color="Default color for starboard posts")
    @requires_starboard()
    async def starboard_color(self, ctx: Context, color: HexColor) -> None:
        """Set default color for starboard posts."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(color=str(color))
        await ctx.success(f"successfully set the starboard color to `#{str(color)}`")

    @starboard.command(name="selfstar")
    @describe(setting="Enable or disable self-star")
    @requires_starboard()
    async def starboard_selfstar(self, ctx: Context, setting: bool) -> None:
        """Allow an author to star their own message."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(self_star=setting)
        await ctx.success(f"**starboard** selfstar has been set to `{setting}`")

    @starboard.command(name="jumpurl")
    @describe(setting="Enable or disable jump URL")
    @requires_starboard()
    async def starboard_jumpurl(self, ctx: Context, setting: bool) -> None:
        """Allow the jump URL to appear on a Starboard post."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(jump=setting)
        await ctx.success(
            f"successfully **{'enabled' if setting else 'disabled'}** starboard jump urls on embeds"
        )

    @starboard.command(name="lock")
    @requires_starboard()
    async def starboard_lock(self, ctx: Context) -> None:
        """Disables/locks starboard from operating."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        if settings.lock:
            return await ctx.fail(
                f"**starboard** is **already locked**, use `{ctx.prefix}starboard unlock` to unlock"
            )
        await settings.upsert(lock=True)
        await ctx.success(
            f"**starboard** has been **locked**, use `{ctx.prefix}starboard unlock` to revert"
        )

    @starboard.command(name="reset")
    @requires_starboard()
    async def starboard_reset(self, ctx: Context) -> None:
        """Resets guild's configuration for starboard."""
        embed = reply_embed(
            color=color.base,
            message=f"{emojis.warn} {ctx.author.mention}: Are you sure you want to **reset** your starboard settings?",
        )
        view = ResetConfirm(ctx)
        view.message = await ctx.send(embed=embed, view=view)
        await view.wait()
        if view.value is None:
            await view.message.delete()

    @starboard.command(name="threshold")
    @describe(threshold="Amount of reactions needed to post")
    @requires_starboard()
    async def starboard_threshold(self, ctx: Context, threshold: int) -> None:
        """Sets the default amount stars needed to post."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(threshold=threshold)
        await ctx.success(f"**starboard** threshold has been set to `{threshold}`")

    @starboard.command(name="timestamp")
    @describe(setting="Enable or disable timestamp")
    @requires_starboard()
    async def starboard_timestamp(self, ctx: Context, setting: bool) -> None:
        """Allow a timestamp to appear on a Starboard post."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(ts=setting)
        await ctx.success(
            f"successfully **{'enabled' if setting else 'disabled'}** starboard timestamps"
        )

    @starboard.command(name="ignore", slash=False)
    @describe(target="Channel, member, or role to ignore")
    @requires_starboard()
    async def starboard_ignore(
        self,
        ctx: Context,
        target: discord.Member | discord.Role | discord.TextChannel | discord.Thread,
    ) -> None:
        """Ignore a channel, member, or role for reactions."""
        settings = await StarboardSettings.fetch(self.bot, ctx.guild)
        raw = settings.ignore_entries
        entries: list[int] = json.loads(raw or "[]") if isinstance(raw, str) else list(raw or [])
        if target.id not in entries:
            entries.append(target.id)
            option = f"**starboard** will now **ignore** {target.mention}"
        else:
            entries.remove(target.id)
            option = f"**starboard** will no longer ignore {target.mention}"
        await settings.upsert(ignore_entries=json.dumps(entries))
        await ctx.success(option)

    @starboard.command(name="ignore list", slash=False)
    @requires_starboard()
    async def starboard_ignore_list(self, ctx: Context) -> None:
        """View ignored roles, members and channels for starboard."""
        stored = await self.bot.db.fetchval(
            "SELECT ignore_entries FROM starboard WHERE guild_id = $1", ctx.guild.id
        )
        entries: list[int] = json.loads(stored or "[]")
        if not entries:
            return await ctx.fail(
                "**starboard** has no ignored **roles**, **members**, or **channels**"
            )
        rows: list[str] = []
        index = 0
        for snowflake in entries:
            if role := ctx.guild.get_role(snowflake):
                index += 1
                rows.append(f"`{index}` {role.mention} --**role**")
            elif member := ctx.guild.get_member(snowflake):
                index += 1
                rows.append(f"`{index}` {member.mention} --**member**")
            elif channel := ctx.guild.get_channel(snowflake):
                index += 1
                rows.append(f"`{index}` {channel.mention} --**channel**")
        
        embed = aesthetic_embed(color=color.base, title="Starboard Blacklists", message="")
        for i in range(0, len(rows), 10):
            chunk = rows[i:i+10]
            embed.add_field(name=f"Page {i//10 + 1}", value=body(*chunk), inline=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    """Load the Starboard cog."""
    from .events import StarboardEvents

    await bot.add_cog(Starboard(bot))
    await bot.add_cog(StarboardEvents(bot))
