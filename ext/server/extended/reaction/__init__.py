from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.discord.package import Package
from config import color, emojis
from core.managers.permissions import has_permissions

from .events import ReactionEvents

from core.discord.views.embed import panel_embed

def matches_trigger(content: str, trigger: str, *, strict: bool) -> bool:
    """Same matching rules as autoresponder.

    Strict: entire message equals trigger.
    Not strict: whole-word/phrase match so ``pic`` does not fire on ``suspicious``.
    """
    content = (content or "").lower().strip()
    trigger = (trigger or "").lower().strip()
    if not trigger:
        return False
    if strict:
        return content == trigger
    pattern = re.compile(
        r"(?<!\w)" + re.escape(trigger) + r"(?!\w)",
        re.IGNORECASE,
    )
    return pattern.search(content) is not None

def parse_emojis(raw: str) -> list[str]:
    """Split a space-separated emoji payload into a list."""
    parts = [p.strip() for p in (raw or "").split() if p.strip()]
    return parts

log = logging.getLogger("vain.reaction")

if TYPE_CHECKING:
    from core.vain import Vain

class Reaction(ReactionEvents, Package):
    """Auto-reaction management — same idea as autoresponder, but only emojis."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
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
            for em in parse_emojis(emoji) or [emoji]:
                await message.add_reaction(em)
            await ctx.message.add_reaction(emojis.approve)
        except Exception:
            await ctx.message.add_reaction(emojis.deny)

    @group(
        name="autoreaction",
        aliases=["autoreact", "autoreactions", "reaction", "reactions", "arx"],
        description=(
            "Auto-react to messages matching a trigger (like autoresponder, but emojis). "
            "Use `--strict` for exact match; default is word-boundary match."
        ),
        invoke_without_command=True,
        guild_only=True,
    )
    @has_permissions(manage_expressions=True)
    async def reaction_group(self, ctx: Context) -> None:
        """Auto-reaction management group."""
        return await ctx.send_help(ctx.command)

    @reaction_group.command(
        name="clear",
        description="Removes every reaction trigger in guild",
        aliases=["reset"],
    )
    @has_permissions(manage_expressions=True)
    async def reaction_clear(self, ctx: Context) -> None:
        """Removes every reaction trigger in guild."""
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.success("Cleared all auto reactions")

    @reaction_group.command(
        name="add",
        description="Add an auto reaction trigger (emoji(s) + trigger word/phrase)",
        aliases=["create"],
        example=",autoreaction add 😂 pic --not_strict",
    )
    @describe(emoji="Emoji(s) to react with", trigger="Word/phrase that triggers the reaction")
    @has_permissions(manage_expressions=True)
    async def reaction_add(self, ctx: Context, emoji: str, *, trigger: str) -> None:
        """Add a reaction trigger.

        Usage: `,autoreaction add <emoji(s)> <trigger> [--strict|--not_strict]`

        Default is **not strict** (word-boundary match), so `pic` won't fire on
        words like `suspicious`. Multi-word triggers work: `rep for pic`.
        """
        strict = False
        trigger_raw = trigger.strip()
        
        flag_re = re.compile(
            r"(?:\s+--(?P<flag>strict|not_strict|not-strict))\s*$",
            re.IGNORECASE,
        )
        while True:
            m = flag_re.search(trigger_raw)
            if not m:
                break
            flag = m.group("flag").lower()
            if flag == "strict":
                strict = True
            else:
                strict = False
            trigger_raw = trigger_raw[: m.start()].rstrip()

        trigger_raw = trigger_raw.strip()
        if not trigger_raw:
            return await ctx.warn("expected: emoji(s) and a trigger word/phrase")

        emojis_list = parse_emojis(emoji)
        if not emojis_list:
            return await ctx.warn("give at least one emoji")

        
        for em in emojis_list:
            try:
                await ctx.message.add_reaction(em)
            except Exception:
                return await ctx.fail(f"couldn't use emoji `{em}`")

        await self.bot.db.execute(
            """
            INSERT INTO auto_reactions (guild_id, trigger, response, owner_id, strict)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id, trigger, response)
            DO UPDATE SET
                response = EXCLUDED.response,
                strict = EXCLUDED.strict,
                owner_id = EXCLUDED.owner_id
            """,
            ctx.guild.id,
            trigger_raw,
            emojis_list,
            ctx.author.id,
            strict,
        )
        mode = "strict" if strict else "not strict"
        await ctx.success(
            f"Created auto reaction for **{trigger_raw}** → {' '.join(emojis_list)} ({mode})"
        )

    @reaction_group.command(
        name="delete",
        description="Remove a reaction trigger",
        aliases=["remove", "del"],
    )
    @describe(trigger="Trigger word/phrase to remove")
    @has_permissions(manage_expressions=True)
    async def reaction_delete(self, ctx: Context, *, trigger: str) -> None:
        """Remove all auto reactions for a trigger."""
        trigger = trigger.strip()
        result = await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1 AND LOWER(trigger) = LOWER($2)",
            ctx.guild.id,
            trigger,
        )
        
        if str(result).endswith("0"):
            return await ctx.fail(f"No auto reaction for `{trigger}`")
        await ctx.success(f"Deleted auto reaction for `{trigger}`")

    @reaction_group.command(
        name="strict",
        description="Toggle strict matching for a trigger (on/off)",
        usage="<trigger|all> <on|off>",
    )
    @has_permissions(manage_expressions=True)
    async def reaction_strict(self, ctx: Context, trigger: str, state: str = None) -> None:
        """`,autoreaction strict <name|all> on|off`"""
        if not state:
            return await ctx.warn("Use `on` or `off`")
        low = state.lower().strip()
        if low in {"on", "enable", "true", "yes", "1", "strict"}:
            strict = True
        elif low in {"off", "disable", "false", "no", "0", "loose", "not_strict"}:
            strict = False
        else:
            return await ctx.warn("Use `on` or `off`")

        if trigger.lower() in {"all", "*", "every"}:
            await self.bot.db.execute(
                "UPDATE auto_reactions SET strict = $2 WHERE guild_id = $1",
                ctx.guild.id,
                strict,
            )
            return await ctx.success(
                f"All auto reactions are now **{'strict' if strict else 'not strict'}**"
            )

        await self.bot.db.execute(
            """
            UPDATE auto_reactions SET strict = $3
            WHERE guild_id = $1 AND LOWER(trigger) = LOWER($2)
            """,
            ctx.guild.id,
            trigger,
            strict,
        )
        return await ctx.success(
            f"**{trigger}** is now **{'strict' if strict else 'not strict'}**"
        )

    @reaction_group.group(
        name="messages",
        description="Add or remove auto reaction on every message in a channel",
        guild_only=True,
        invoke_without_command=True,
    )
    @has_permissions(manage_expressions=True)
    async def reaction_messages(self, ctx: Context) -> None:
        """Auto reaction on messages group (channel-wide)."""
        return await ctx.send_help(ctx.command)

    @reaction_messages.command(
        name="add",
        description="Auto-react to every message in a channel",
    )
    @describe(channel="Channel", emoji="Emoji(s) to add")
    @has_permissions(manage_expressions=True)
    async def reaction_messages_add(
        self,
        ctx: Context,
        channel: discord.TextChannel,
        *,
        emoji: str,
    ) -> None:
        emojis_list = parse_emojis(emoji)
        if not emojis_list:
            return await ctx.warn("give at least one emoji")
        for em in emojis_list:
            try:
                await ctx.message.add_reaction(em)
            except Exception:
                return await ctx.fail(f"couldn't use emoji `{em}`")
        await self.bot.db.execute(
            """
            INSERT INTO auto_reactions (guild_id, trigger, response, owner_id, strict)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id, trigger, response)
            DO UPDATE SET response = EXCLUDED.response
            """,
            ctx.guild.id,
            str(channel.id),
            emojis_list,
            ctx.author.id,
            True,
        )
        await ctx.success(f"Every message in {channel.mention} will get {' '.join(emojis_list)}")

    @reaction_messages.command(
        name="remove",
        description="Stop auto-reacting in a channel",
        aliases=["delete", "del"],
    )
    @describe(channel="Channel to clear")
    @has_permissions(manage_expressions=True)
    async def reaction_messages_remove(
        self,
        ctx: Context,
        channel: discord.TextChannel,
    ) -> None:
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1 AND trigger = $2",
            ctx.guild.id,
            str(channel.id),
        )
        await ctx.success(f"Cleared channel auto reactions for {channel.mention}")

    @reaction_messages.command(
        name="list",
        description="List channel auto reactions",
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
            trig = str(record["trigger"])
            if trig.isnumeric():
                ch = ctx.guild.get_channel(int(trig))
                if ch:
                    resp = record["response"] or []
                    rows.append(f"{ch.mention} - {''.join(str(r) for r in resp)}")
        if not rows:
            await ctx.warn("No channel auto reactions found")
            return
        rows = [f"`{i}` {row}" for i, row in enumerate(rows, start=1)]
        embed = panel_embed(
            color=color.base,
            title="Channel Auto Reactions",
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
    async def reaction_deleteall(self, ctx: Context, *, trigger_word: str) -> None:
        """Removes every reaction trigger for a specific word."""
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE LOWER(trigger) = LOWER($1) AND guild_id = $2",
            trigger_word.strip(),
            ctx.guild.id,
        )
        await ctx.success(f"Deleted all auto reactions triggered by `{trigger_word}`")

    @reaction_group.command(
        name="list",
        description="View every reaction trigger in guild",
        aliases=["view", "show", "ls"],
    )
    @has_permissions(manage_expressions=True)
    async def reaction_list(self, ctx: Context) -> None:
        """View a list of every reaction trigger in guild."""
        reactions = await self.bot.db.fetch(
            """
            SELECT trigger, response, strict FROM auto_reactions
            WHERE guild_id = $1
            ORDER BY trigger
            """,
            ctx.guild.id,
        )
        rows = []
        for record in reactions:
            trig = str(record["trigger"])
            
            if trig.isnumeric() and ctx.guild.get_channel(int(trig)):
                continue
            resp = record["response"] or []
            mode = "strict" if record.get("strict") else "not strict"
            rows.append(f"**{trig}** - {''.join(str(r) for r in resp)} ({mode})")
        if not rows:
            return await ctx.warn("No auto reaction triggers found")
        rows = [f"`{i}` {row}" for i, row in enumerate(rows, start=1)]
        embed = panel_embed(
            color=color.base,
            title="Auto Reaction Triggers",
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
    async def reaction_owner(self, ctx: Context, *, trigger_word: str) -> None:
        """Gets the author of a trigger word."""
        owner_id = await self.bot.db.fetchval(
            """
            SELECT owner_id FROM auto_reactions
            WHERE LOWER(trigger) = LOWER($1) AND guild_id = $2
            LIMIT 1
            """,
            trigger_word.strip(),
            ctx.guild.id,
        )
        if not owner_id:
            await ctx.fail(f"No reaction trigger found under `{trigger_word}`")
            return
        user = self.bot.get_user(owner_id)
        if not user:
            user = await self.bot.fetch_user(owner_id)
        await ctx.normal(
            f"Reaction Trigger `{trigger_word}` author is `{str(user)}`",
            emoji="ℹ️",
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(Reaction(bot))
