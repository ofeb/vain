from __future__ import annotations

from typing import List, Optional

import discord
from discord import Embed, Message, TextChannel
from discord.ext import commands
from discord.ext.commands import Range, flag

from core.discord.ctx import Context
from core.discord.hybrid import group, describe
from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.tools.convert.status import StatusConvert
from config import color

from .settings import Config


class Flags(commands.FlagConverter, case_insensitive=True, delimiter=" ", prefix="--"):
    threshold: Range[int, 1, 50] = flag(
        aliases=["limit"],
        description="Reactions needed before archiving.",
        default=3,
    )
    self_star: bool = flag(
        aliases=["self"],
        description="Allow authors to star their own messages (true/false).",
        default=True,
    )


class Starboard(Package):
    """Archive popular messages to dedicated channels (multi-emoji)."""

    def __init__(self, bot):
        super().__init__(bot)

    async def cog_load(self) -> None:
        await Config.ensure_schema(self.bot)

    @group(
        name="starboard",
        aliases=["star", "board", "sb"],
        invoke_without_command=True,
        description="Archive popular messages with custom emoji boards",
        example=",starboard add #stars ⭐ --threshold 3",
    )
    @has_permissions(manage_guild=True)
    async def starboard(self, ctx: Context) -> Message:
        return await ctx.send_help(ctx.command)

    @starboard.command(name="add", aliases=["create", "set"])
    @describe(
        channel="Channel that receives starred posts",
        emoji="Emoji that triggers this board",
    )
    @has_permissions(manage_guild=True)
    async def starboard_add(
        self,
        ctx: Context,
        channel: Optional[TextChannel] = None,
        emoji: str = "⭐",
        *,
        flags: Flags,
    ) -> Message:
        """Add or update a starboard for an emoji (channel defaults to here)."""
        channel = channel or ctx.channel  # type: ignore[assignment]
        if not isinstance(channel, TextChannel):
            return await ctx.warn("Provide a **text channel** for the starboard")

        try:
            await ctx.message.add_reaction(emoji)
        except (discord.HTTPException, TypeError):
            return await ctx.warn(
                f"I'm not able to use **{emoji}** - try a server emoji or unicode"
            )

        cfg = await Config.upsert(
            self.bot,
            ctx.guild,
            channel_id=channel.id,
            emoji=str(emoji),
            threshold=int(flags.threshold),
            self_star=bool(flags.self_star),
        )
        return await ctx.success(
            f"Starboard for {cfg.emoji} → {channel.mention} "
            f"(threshold `{cfg.threshold}`, self-star `{cfg.self_star}`)"
        )

    @starboard.command(name="remove", aliases=["delete", "del", "rm"])
    @has_permissions(manage_guild=True)
    async def starboard_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel] = None,
        emoji: str = "⭐",
    ) -> Message:
        """Remove a starboard binding."""
        channel = channel or ctx.channel  # type: ignore[assignment]
        ok = await Config.delete(
            self.bot, ctx.guild, channel_id=channel.id, emoji=str(emoji)
        )
        if not ok:
            return await ctx.warn(
                f"No starboard for **{emoji}** in {channel.mention}"
            )
        return await ctx.success(
            f"Removed starboard for {emoji} in {channel.mention}"
        )

    @starboard.command(name="clear", aliases=["reset", "purge"])
    @has_permissions(manage_guild=True)
    async def starboard_clear(self, ctx: Context) -> Message:
        """Remove every starboard in this server. This can't be undone."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Remove **every** starboard in this server? "
            "This action **can't be undone**."
        )
        if not ok:
            return await ctx.warn("Starboard clear **cancelled**")
        count = await Config.clear(self.bot, ctx.guild)
        if count <= 0:
            return await ctx.warn("No starboards exist for this server")
        return await ctx.success(
            f"Removed **{count}** starboard(s). This action can't be undone."
        )

    @starboard.command(name="list", aliases=["ls", "show", "view", "config"])
    @has_permissions(manage_guild=True)
    async def starboard_list(self, ctx: Context) -> Message:
        """View all starboards configured here."""
        boards = await Config.fetch_all(self.bot, ctx.guild)
        lines: List[str] = []
        for cfg in boards:
            ch = cfg.channel
            mention = ch.mention if ch else f"`{cfg.channel_id}`"
            lines.append(
                f"{mention} - **{cfg.emoji}** · threshold `{cfg.threshold}` · "
                f"self-star `{cfg.self_star}`"
            )
        if not lines:
            return await ctx.warn("No starboards configured - use `,starboard add`")
        embed = Embed(title="Starboards", color=getattr(self.bot, "color", color.base))
        embed.set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(embed, lines)

    @starboard.command(name="threshold", aliases=["limit"])
    @has_permissions(manage_guild=True)
    async def starboard_threshold(
        self, ctx: Context, emoji: str, threshold: Range[int, 1, 50]
    ) -> Message:
        """Change the reaction threshold for one emoji board."""
        cfg = await Config.fetch_emoji(self.bot, ctx.guild, emoji)
        if cfg is None or not cfg.channel_id:
            return await ctx.warn(f"No starboard for **{emoji}**")
        await Config.upsert(
            self.bot,
            ctx.guild,
            channel_id=int(cfg.channel_id),
            emoji=emoji,
            threshold=int(threshold),
            self_star=cfg.self_star,
        )
        return await ctx.success(
            f"Threshold for {emoji} set to **{threshold}**"
        )

    @starboard.command(name="selfstar")
    @has_permissions(manage_guild=True)
    async def starboard_selfstar(
        self, ctx: Context, emoji: str, enabled: StatusConvert
    ) -> Message:
        """Toggle whether authors can star their own messages for a board."""
        cfg = await Config.fetch_emoji(self.bot, ctx.guild, emoji)
        if cfg is None or not cfg.channel_id:
            return await ctx.warn(f"No starboard for **{emoji}**")
        await Config.upsert(
            self.bot,
            ctx.guild,
            channel_id=int(cfg.channel_id),
            emoji=emoji,
            threshold=cfg.threshold,
            self_star=bool(enabled),
        )
        return await ctx.success(
            f"Self-star for {emoji} set to **{bool(enabled)}**"
        )


async def setup(bot) -> None:
    from .events import StarboardEvents

    await bot.add_cog(Starboard(bot))
    await bot.add_cog(StarboardEvents(bot))
