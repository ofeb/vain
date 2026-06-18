from __future__ import annotations

import json
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.managers.values import color, emojis

if TYPE_CHECKING:
    from .events import ClownboardEvents


def _toggle_emoji(enabled: bool) -> str:
    """Map a boolean to success/fail emoji."""
    return emojis.approve if enabled else emojis.deny


class HexColor(commands.Converter):
    """Resolve color-like argument to hex string."""

    async def convert(self, ctx: Context, argument: str) -> str:
        colour = await commands.ColourConverter().convert(ctx, argument)
        return format(colour.value, "06x")


def requires_clownboard():
    """Ensure clownboard is configured before subcommand runs."""
    async def predicate(ctx: Context) -> bool:
        exists = await ctx.bot.db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM clownboard WHERE guild_id = $1)", ctx.guild.id
        )
        if exists:
            return True
        raise commands.CommandError(
            f"**clownboard** hasn't been setup using `{ctx.prefix}clownboard set`"
        )
    return commands.check(predicate)


class ResetConfirm(discord.ui.View):
    """Approve/decline prompt for resetting clownboard."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(timeout=15)
        self.ctx = ctx
        self.value: bool | None = None
        self.message: discord.Message | None = None

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user == self.ctx.author:
            return True
        embed = discord.Embed(
            description=f"{emojis.warn} {interaction.user.mention}: Your interaction is not allowed",
            color=color.base,
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
            "DELETE FROM clownboard_entries WHERE guild_id = $1", guild_id
        )
        await self.ctx.bot.db.execute(
            "DELETE FROM clownboard WHERE guild_id = $1", guild_id
        )
        embed = discord.Embed(
            description=f"{emojis.approve} {self.ctx.author.mention}: clownboard has been **reset**",
            color=color.base,
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


class Clownboard(commands.Cog):
    """Showcase the worst messages in your server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @hybrid(
        name="clownboard",
        description="Showcase the worst messages in your server",
        guild_only=True,
    )
    async def clownboard(self, ctx: Context) -> None:
        """Main clownboard command group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @clownboard.command(name="threshold")
    @describe(threshold="Amount of reactions needed to post")
    @requires_clownboard()
    async def clownboard_threshold(self, ctx: Context, threshold: int) -> None:
        """Sets the default amount clowns needed to post."""
        await self.bot.db.execute(
            "UPDATE clownboard SET threshold = $1 WHERE guild_id = $2",
            threshold,
            ctx.guild.id,
        )
        await ctx.success(f"**clownboard** threshold has been set to `{threshold}`")

    @clownboard.command(name="unlock")
    @requires_clownboard()
    async def clownboard_unlock(self, ctx: Context) -> None:
        """Enables/unlocks clownboard from operating."""
        locked = await self.bot.db.fetchval(
            "SELECT lock FROM clownboard WHERE guild_id = $1", ctx.guild.id
        )
        if not locked:
            return await ctx.fail(
                f"**clownboard** is **already unlocked**, use `{ctx.prefix}clownboard lock` to lock"
            )
        await self.bot.db.execute(
            "UPDATE clownboard SET lock = $1 WHERE guild_id = $2", False, ctx.guild.id
        )
        await ctx.success(
            f"**clownboard** has been **unlocked**, use `{ctx.prefix}clownboard lock` to revert"
        )

    @clownboard.command(name="lock")
    @requires_clownboard()
    async def clownboard_lock(self, ctx: Context) -> None:
        """Disables/locks clownboard from operating."""
        locked = await self.bot.db.fetchval(
            "SELECT lock FROM clownboard WHERE guild_id = $1", ctx.guild.id
        )
        if locked:
            return await ctx.fail(
                f"**clownboard** is **already locked**, use `{ctx.prefix}clownboard unlock` to unlock"
            )
        await self.bot.db.execute(
            "UPDATE clownboard SET lock = $1 WHERE guild_id = $2", True, ctx.guild.id
        )
        await ctx.success(
            f"**clownboard** has been **locked**, use `{ctx.prefix}clownboard unlock` to revert"
        )

    @clownboard.command(name="ignore")
    @describe(target="Channel, member, or role to ignore")
    @requires_clownboard()
    async def clownboard_ignore(
        self,
        ctx: Context,
        target: discord.Member | discord.Role | discord.TextChannel | discord.Thread,
    ) -> None:
        """Ignore a channel, member, or role for reactions."""
        stored = await self.bot.db.fetchval(
            "SELECT ignore_entries FROM clownboard WHERE guild_id = $1", ctx.guild.id
        )
        entries: list[int] = json.loads(stored or "[]")
        if target.id not in entries:
            entries.append(target.id)
            option = f"**clownboard** will now **ignore** {target.mention}"
        else:
            entries.remove(target.id)
            option = f"**clownboard** will no longer ignore {target.mention}"
        await self.bot.db.execute(
            "UPDATE clownboard SET ignore_entries = $1 WHERE guild_id = $2",
            json.dumps(entries),
            ctx.guild.id,
        )
        await ctx.success(option)

    @clownboard.command(name="ignore list")
    @requires_clownboard()
    async def clownboard_ignore_list(self, ctx: Context) -> None:
        """View ignored roles, members and channels for clownboard."""
        stored = await self.bot.db.fetchval(
            "SELECT ignore_entries FROM clownboard WHERE guild_id = $1", ctx.guild.id
        )
        entries: list[int] = json.loads(stored or "[]")
        if not entries:
            return await ctx.fail(
                "**clownboard** has no ignored **roles**, **members**, or **channels**"
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
        
        embed = discord.Embed(color=color.base, title="Clownboard Blacklists")
        for i in range(0, len(rows), 10):
            chunk = rows[i:i+10]
            embed.add_field(name=f"Page {i//10 + 1}", value="\n".join(chunk), inline=False)
        await ctx.send(embed=embed)

    @clownboard.command(name="set")
    @describe(channel="Channel where clownboard messages will be sent", emoji="Emoji that triggers clownboard", threshold="Reactions needed")
    async def clownboard_set(
        self,
        ctx: Context,
        channel: discord.TextChannel | discord.Thread | None = None,
        emoji: str = "🤡",
        threshold: int = 1,
    ) -> None:
        """Sets the channel where clownboard messages will be sent to."""
        channel = channel or ctx.channel
        if await self.bot.db.fetchrow(
            "SELECT * FROM clownboard WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.fail(
                f"**clownboard** has already been setup. Use `{ctx.prefix}clownboard reset` to reset"
            )
        try:
            await ctx.message.add_reaction(emoji)
        except discord.HTTPException:
            return await ctx.fail(f"**{emoji}** is not a valid emoji")
        note = "" if threshold == 1 else f"with a threshold of `{threshold}`"
        await self.bot.db.execute(
            "INSERT INTO clownboard (guild_id, channel_id, emoji, threshold) "
            "VALUES ($1, $2, $3, $4)",
            ctx.guild.id,
            channel.id,
            emoji,
            threshold,
        )
        await ctx.success(
            f"**clownboard** channel has been set to {channel.mention} using **{emoji}** {note}"
        )

    @clownboard.command(name="timestamp")
    @describe(setting="Enable or disable timestamp")
    @requires_clownboard()
    async def clownboard_timestamp(self, ctx: Context, setting: bool) -> None:
        """Allow a timestamp to appear on a Clownboard post."""
        await self.bot.db.execute(
            "INSERT INTO clownboard (guild_id, ts) VALUES($1, $2) "
            "ON CONFLICT(guild_id) DO UPDATE SET ts = excluded.ts",
            ctx.guild.id,
            setting,
        )
        await ctx.success(
            f"successfully **{'enabled' if setting else 'disabled'}** clownboard timestamps"
        )

    @clownboard.command(name="reset")
    @requires_clownboard()
    async def clownboard_reset(self, ctx: Context) -> None:
        """Resets guild's configuration for clownboard."""
        embed = discord.Embed(
            description=f"{emojis.warn} {ctx.author.mention}: Are you sure you want to **reset** your clownboard settings?",
            color=color.base,
        )
        view = ResetConfirm(ctx)
        view.message = await ctx.send(embed=embed, view=view)
        await view.wait()
        if view.value is None:
            await view.message.delete()

    @clownboard.command(name="attachments")
    @describe(setting="Enable or disable attachments")
    @requires_clownboard()
    async def clownboard_attachments(self, ctx: Context, setting: bool) -> None:
        """Allow attachments to appear on a Clownboard post."""
        await self.bot.db.execute(
            "INSERT INTO clownboard (guild_id, attachments) VALUES($1, $2) "
            "ON CONFLICT(guild_id) DO UPDATE SET attachments = excluded.attachments",
            ctx.guild.id,
            setting,
        )
        await ctx.success(
            f"successfully **{'enabled' if setting else 'disabled'}** clownboard attachments"
        )

    @clownboard.command(name="selfstar")
    @describe(setting="Enable or disable self-star")
    @requires_clownboard()
    async def clownboard_selfstar(self, ctx: Context, setting: bool) -> None:
        """Allow an author to star their own message."""
        await self.bot.db.execute(
            "UPDATE clownboard SET self_star = $1 WHERE guild_id = $2",
            setting,
            ctx.guild.id,
        )
        await ctx.success(f"**clownboard** selfstar has been set to `{setting}`")

    @clownboard.command(name="config")
    @requires_clownboard()
    async def clownboard_config(self, ctx: Context) -> None:
        """View the settings for clownboard in guild."""
        clownboard = await self.bot.db.fetchrow(
            "SELECT * FROM clownboard WHERE guild_id = $1", ctx.guild.id
        )
        if not clownboard:
            return await ctx.fail(
                "**clownboard** hasn't been setup using `{ctx.prefix}clownboard set`"
            )

        description = f"**Locked:** {_toggle_emoji(clownboard['lock'])}"

        channel_mention = f"<#{clownboard['channel_id']}>" if clownboard['channel_id'] else "No channel set"
        color_display = f"`#{clownboard['color']}`" if clownboard.get('color') else "Author color"
        general_value = (
            f"**Channel:** {channel_mention}\n"
            f"**Color:** {color_display}\n"
            f"**Threshold:** {clownboard['threshold']}\n"
            f"**Emoji:** {clownboard['emoji']}"
        )
        options_value = (
            f"**Show Attachments:** {_toggle_emoji(clownboard.get('attachments', False))}\n"
            f"**Show Timestamps:** {_toggle_emoji(clownboard.get('ts', False))}\n"
            f"**Show Jump URL:** {_toggle_emoji(clownboard.get('jump', False))}\n"
            f"**Self Star:** {_toggle_emoji(clownboard.get('self_star', True))}"
        )

        roles = channels = members = 0
        if clownboard.get("ignore_entries"):
            for snowflake in json.loads(clownboard["ignore_entries"]):
                if ctx.guild.get_channel(snowflake):
                    channels += 1
                elif ctx.guild.get_member(snowflake):
                    members += 1
                elif ctx.guild.get_role(snowflake):
                    roles += 1

        count_value = (
            f"**Blacklisted Channels:** {channels}\n"
            f"**Blacklisted Users:** {members}\n"
            f"**Blacklisted Roles:** {roles}"
        )
        embed = discord.Embed(
            color=color.base,
            title="Clownboard configuration",
            description=description,
        )
        embed.add_field(name="General", value=general_value, inline=True)
        embed.add_field(name="Options", value=options_value, inline=True)
        embed.add_field(name="Count", value=count_value, inline=True)
        await ctx.send(embed=embed)

    @clownboard.command(name="color")
    @describe(color="Default color for clownboard posts")
    @requires_clownboard()
    async def clownboard_color(self, ctx: Context, color: HexColor) -> None:
        """Set default color for clownboard posts."""
        await self.bot.db.execute(
            "UPDATE clownboard SET color = $1 WHERE guild_id = $2",
            str(color),
            ctx.guild.id,
        )
        await ctx.success(f"successfully set the clownboard color to `#{str(color)}`")

    @clownboard.command(name="jumpurl")
    @describe(setting="Enable or disable jump URL")
    @requires_clownboard()
    async def clownboard_jumpurl(self, ctx: Context, setting: bool) -> None:
        """Allow the jump URL to appear on a Clownboard post."""
        await self.bot.db.execute(
            "INSERT INTO clownboard (guild_id, jump) VALUES($1, $2) "
            "ON CONFLICT(guild_id) DO UPDATE SET jump = excluded.jump",
            ctx.guild.id,
            setting,
        )
        await ctx.success(
            f"successfully **{'enabled' if setting else 'disabled'}** clownboard jump urls on embeds"
        )

    @clownboard.command(name="emoji")
    @describe(emoji="Emoji that triggers clownboard messages")
    @requires_clownboard()
    async def clownboard_emoji(self, ctx: Context, emoji: str) -> None:
        """Sets the emoji that triggers the clownboard messages."""
        await self.bot.db.execute(
            "INSERT INTO clownboard (guild_id, emoji) VALUES($1, $2) "
            "ON CONFLICT(guild_id) DO UPDATE SET emoji = excluded.emoji",
            ctx.guild.id,
            str(emoji),
        )
        await ctx.success(f"successfully set the clownboard emoji as {str(emoji)}")


async def setup(bot: commands.Bot):
    """Load the Clownboard cog."""
    await bot.add_cog(Clownboard(bot))
