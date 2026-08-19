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
    """Auto-reaction management - same idea as autoresponder, but only emojis."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.bot = bot

    @hybrid(
        name="react",
        description="add a reaction(s) to a message",
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
            "Use `--strict` for exact match; default is word-boundary match. "
            "Use `--user` with a member to react to all of their messages (no trigger word)."
        ),
        invoke_without_command=True,
        guild_only=True,
    )
    @has_permissions(manage_expressions=True)
    async def reaction_group(self, ctx: Context, *, payload: str = None) -> None:
        """Auto-reaction management group.

        Supports ``autoreact @user emoji --user`` without the add subcommand.
        """
        if ctx.invoked_subcommand is not None:
            return
        raw = (payload or "").strip()
        if not raw:
            content = (ctx.message.content or "").strip()
            if content:
                parts = content.split(None, 1)
                raw = parts[1].strip() if len(parts) > 1 else ""
        if raw and "--user" in raw.lower():
            return await self._add_user_autoreact(ctx, raw)
        return await ctx.send_help(ctx.command)

    async def _add_user_autoreact(self, ctx: Context, raw: str) -> None:
        """Parse ``@user emoji1 emoji2 --user`` and store a user-targeted rule."""
        cleaned = re.sub(r"(?i)--user\b", " ", raw).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            return await ctx.warn(
                f"expected: member and emoji(s)\n> -# **usage:** `{ctx.cmd('autoreact @user 😂 --user')}`"
            )

        tokens = cleaned.split()
        member = None
        emoji_tokens: list[str] = []
        from discord.ext.commands import MemberConverter

        conv = MemberConverter()
        for take in (1, 2, 3):
            if take > len(tokens):
                break
            candidate = " ".join(tokens[:take])
            try:
                member = await conv.convert(ctx, candidate)
                emoji_tokens = tokens[take:]
                break
            except Exception:
                member = None
        if member is None:
            return await ctx.warn(
                f"member not found\n> -# **usage:** `{ctx.cmd('autoreact @user 😂 🔥 --user')}`"
            )
        emojis_list = parse_emojis(" ".join(emoji_tokens))
        if not emojis_list:
            return await ctx.warn("expected at least one emoji after the member")

        for em in emojis_list:
            try:
                await ctx.message.add_reaction(em)
            except Exception:
                return await ctx.warn(f"invalid emoji: `{em}`")

        trigger_key = f"user:{member.id}"
        await self.bot.db.execute(
            """
            INSERT INTO auto_reactions (guild_id, trigger, response, owner_id, strict, reply)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (guild_id, trigger, response)
            DO UPDATE SET
                owner_id = EXCLUDED.owner_id,
                strict = EXCLUDED.strict,
                reply = EXCLUDED.reply
            """,
            ctx.guild.id,
            trigger_key,
            emojis_list,
            ctx.author.id,
            False,
            False,
        )
        await ctx.success(
            f"Created user auto reaction for **{member.display_name}** → {' '.join(emojis_list)}\n"
            f"> -# reacts to **all** of their messages (no trigger word)"
        )

    @reaction_group.command(
        name="clear",
        description="Removes every reaction trigger in guild. This can't be undone.",
        aliases=["reset"],
    )
    @has_permissions(manage_expressions=True)
    async def reaction_clear(self, ctx: Context) -> None:
        """Removes every reaction trigger in guild. This can't be undone."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Clear **all** auto reactions for this server? "
            "This action **can't be undone**."
        )
        if not ok:
            return await ctx.warn("Auto reaction clear **cancelled**")
        await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.success(
            "Cleared all auto reactions. This action can't be undone."
        )

    @reaction_group.command(
        name="add",
        description="add an auto reaction trigger (emoji(s) + trigger word/phrase)",
        aliases=["create"],
        example=",autoreaction add 😂 pic --not_strict --reply yes",
    )
    @describe(emoji="Emoji(s) to react with", trigger="Word/phrase that triggers the reaction")
    @has_permissions(manage_expressions=True)
    async def reaction_add(self, ctx: Context, emoji: str, *, trigger: str) -> None:
        """Add a reaction trigger.

        Usage: autoreaction add <emoji(s)> <trigger> [--strict|--not_strict] [--reply yes/no]
        User mode: autoreact @user <emojis> --user

        Default is **not strict** (word-boundary match), so `pic` won't fire on
        words like `suspicious`. Multi-word triggers work: `rep for pic`.

        `--reply yes` makes the bot reply to the matching message with the
        emoji(s) as text in addition to adding the reactions.
        """
        strict = False
        reply = False
        user_mode = False
        trigger_raw = trigger.strip()
        
        flag_re = re.compile(
            r"(?:\s+--(?P<flag>strict|not_strict|not-strict|reply|user)"
            r"(?:=(?P<eqval>\S+)|\s+(?P<val>(?!\-\-)\S+))?)\s*$",
            re.IGNORECASE,
        )
        while True:
            m = flag_re.search(trigger_raw)
            if not m:
                break
            flag = m.group("flag").lower()
            if flag == "strict":
                strict = True
            elif flag in {"not_strict", "not-strict"}:
                strict = False
            elif flag == "reply":
                value = m.group("eqval") or m.group("val")
                if value is None:
                    reply = True
                elif value.lower() in {"yes", "true", "on", "1", "y"}:
                    reply = True
                elif value.lower() in {"no", "false", "off", "0", "n"}:
                    reply = False
                else:
                    return await ctx.warn("`--reply` must be `on`/`yes`/`true` or `off`/`no`/`false`")
            elif flag == "user":
                user_mode = True
            trigger_raw = trigger_raw[: m.start()].rstrip()

        if user_mode:
            
            combined = f"{emoji} {trigger_raw}".strip()
            return await self._add_user_autoreact(ctx, combined + " --user")

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
            INSERT INTO auto_reactions (guild_id, trigger, response, owner_id, strict, reply)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (guild_id, trigger, response)
            DO UPDATE SET
                response = EXCLUDED.response,
                strict = EXCLUDED.strict,
                reply = EXCLUDED.reply,
                owner_id = EXCLUDED.owner_id
            """,
            ctx.guild.id,
            trigger_raw,
            emojis_list,
            ctx.author.id,
            strict,
            reply,
        )
        mode = "strict" if strict else "not strict"
        details = [mode]
        if reply:
            details.append("reply")
        await ctx.success(
            f"Created auto reaction for **{trigger_raw}** → {' '.join(emojis_list)} ({', '.join(details)})"
        )

    @reaction_group.command(
        name="delete",
        description="remove a reaction trigger",
        aliases=["remove", "del"],
    )
    @describe(trigger="Trigger word/phrase to remove")
    @has_permissions(manage_expressions=True)
    async def reaction_delete(self, ctx: Context, *, trigger: str) -> None:
        """Remove all auto reactions for a trigger (or a user rule)."""
        trigger = trigger.strip()
        
        if trigger.lower().startswith("user:"):
            key = trigger
        else:
            key = trigger
            try:
                from discord.ext.commands import MemberConverter
                member = await MemberConverter().convert(ctx, trigger)
                key = f"user:{member.id}"
                
                result = await self.bot.db.execute(
                    """
                    DELETE FROM auto_reactions
                    WHERE guild_id = $1 AND (
                        LOWER(trigger) = LOWER($2) OR trigger = $3
                    )
                    """,
                    ctx.guild.id,
                    trigger,
                    key,
                )
                if result and result != "DELETE 0":
                    await ctx.success(f"Deleted auto reaction for **{member.display_name}**")
                    return
            except Exception:
                pass
        result = await self.bot.db.execute(
            "DELETE FROM auto_reactions WHERE guild_id = $1 AND LOWER(trigger) = LOWER($2)",
            ctx.guild.id,
            key if key.startswith("user:") else trigger,
        )
        
        if str(result).endswith("0"):
            return await ctx.fail(f"No auto reaction for `{trigger}`")
        await ctx.success(f"Deleted auto reaction for `{trigger}`")

    @reaction_group.command(
        name="strict",
        description="toggle strict matching for a trigger (on/off)",
        usage="<trigger or all> <on or off>",
    )
    @has_permissions(manage_expressions=True)
    async def reaction_strict(self, ctx: Context, trigger: str, state: str = None) -> None:
        """{ctx.cmd('autoreaction strict <name|all> on|off')}"""
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
        description="add or remove auto reaction on every message in a channel",
        guild_only=True,
        invoke_without_command=True,
    )
    @has_permissions(manage_expressions=True)
    async def reaction_messages(self, ctx: Context) -> None:
        """Auto reaction on messages group (channel-wide)."""
        return await ctx.send_help(ctx.command)

    @reaction_messages.command(
        name="add",
        description="auto-react to every message in a channel",
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
        description="stop auto-reacting in a channel",
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
        description="list channel auto reactions",
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
        description="removes every reaction trigger for a specific word",
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
        description="view every reaction trigger in guild",
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
        description="gets the author of a trigger word",
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
