from __future__ import annotations

import contextlib
from asyncio import Lock, sleep
from collections import defaultdict
from typing import Optional

from asyncpg import UniqueViolationError
import discord
from discord import Embed, Member, Message, TextChannel
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.converters import EmbedConverter
from core.tools.flags.guilds import Parameters
from core.managers.permissions import has_permissions
from core.tools.human.text import humanize_duration

from .settings import Settings


class BoostCommands(Package):
    """Boost messages - one first-boost and one second-boost script per channel."""

    def __init__(self, bot):
        super().__init__(bot)
        self.boost_locks = defaultdict(Lock)
        self._boost_counts: dict[int, dict[int, int]] = defaultdict(dict)

    @staticmethod
    def _parse_boost_flags(ctx, message: str) -> tuple[str, bool, int | None]:
        import re
        cleaned = message
        is_second = bool(re.search(r'(?:^|\s)--twoboosts(?:\s|$)', cleaned))
        cleaned = re.sub(r'\s*--twoboosts\s*', ' ', cleaned).strip()
        timer = ctx.flags.get("self_destruct") if hasattr(ctx, 'flags') else None
        m = re.search(r'--self_destruct\s+(\d+)', cleaned)
        if m:
            timer = int(m.group(1))
            cleaned = re.sub(r'\s*--self_destruct\s+\d+\s*', ' ', cleaned).strip()
        if cleaned.startswith("```") and cleaned.endswith("```") and len(cleaned) > 6:
            cleaned = cleaned[3:-3].strip()
        return cleaned, is_second, timer

    async def cog_load(self) -> None:
        await Settings.ensure_schema(self.db)

    @group(
        name="boosts",
        example=",boosts add #general thanks {user.mention}!",
        aliases=["boost"],
        invoke_without_command=True,
        description="manage messages sent when a member boosts the server",
    )
    @has_permissions(manage_guild=True)
    async def boosts(self, ctx) -> Message:
        return await ctx.send_help()

    async def _upsert(
        self,
        ctx,
        channel: TextChannel,
        script: str,
        timer: int | None,
        *,
        is_second: bool,
        edit: bool,
    ) -> Message:
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only set boost messages in text channels")
        if timer is not None and timer < 6:
            return await ctx.warn("self-destruct timer must be at least `6` seconds")

        exists = await Settings.exists(
            self.db, ctx.guild.id, channel.id, is_second,
        )
        slot = "second-boost" if is_second else "first-boost"
        if edit:
            if not exists:
                return await ctx.fail(
                    f"no **{slot}** message for {channel.mention} - use "
                    f"`{ctx.clean_prefix}boosts add` first"
                    + (" `--twoboosts`" if is_second else "")
                )
            await Settings.upsert_message(
                self.db, ctx.guild.id, channel.id, script, timer, is_second,
            )
            verb = "updated"
        else:
            if exists:
                return await ctx.fail(
                    f"there's already a **{slot}** message in {channel.mention} - "
                    f"use `{ctx.clean_prefix}boosts edit` or `{ctx.clean_prefix}boosts remove`"
                    + (" `--twoboosts`" if is_second else "")
                )
            try:
                await Settings.insert_message(
                    self.db, ctx.guild.id, channel.id, script, timer, is_second,
                )
            except UniqueViolationError:
                return await ctx.fail(
                    f"there's already a **{slot}** message in {channel.mention}"
                )
            verb = "set"

        extra = f"\n> -# **the message will delete itself after {humanize_duration(timer)}**" if timer else ""
        return await ctx.success(
            f"**{slot}** message {verb} for {channel.mention}{extra}"
        )

    @boosts.command(
        name="add",
        example=",boosts add #general thanks {user.mention}!",
        aliases=["create", "set"],
        description="add a boost message (defaults to current channel). use --twoboosts for the 2nd boost script",
        usage="[channel] <script> [--self_destruct <time>] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_add(
        self, ctx, channel: Optional[TextChannel] = None, *, message: str
    ) -> Message:
        channel = channel or ctx.channel
        cleaned, is_second, timer = self._parse_boost_flags(ctx, message)
        script = await EmbedConverter().convert(ctx, cleaned)
        return await self._upsert(
            ctx,
            channel,
            script.script,
            timer,
            is_second=is_second,
            edit=False,
        )

    @boosts.command(
        name="edit",
        aliases=["change", "update"],
        example=",boosts edit #general thanks {user.mention} for the boost!",
        description="edit an existing boost script (defaults to current channel)",
        usage="[channel] <script> [--self_destruct <time>] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_edit(
        self, ctx, channel: Optional[TextChannel] = None, *, message: str
    ) -> Message:
        channel = channel or ctx.channel
        cleaned, is_second, timer = self._parse_boost_flags(ctx, message)
        script = await EmbedConverter().convert(ctx, cleaned)
        return await self._upsert(
            ctx,
            channel,
            script.script,
            timer,
            is_second=is_second,
            edit=True,
        )

    @boosts.command(
        name="remove",
        example=",boosts remove #general",
        aliases=["delete", "del"],
        flags=Parameters,
        description="remove a boost message (defaults to current channel). --twoboosts removes the second-boost slot",
        usage="[channel] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_remove(
        self, ctx, channel: Optional[TextChannel] = None
    ) -> Message:
        channel = channel or ctx.channel
        is_second = bool(ctx.flags.get("twoboosts"))
        slot = "second-boost" if is_second else "first-boost"
        deleted = await Settings.remove_message(
            self.db, ctx.guild.id, channel.id, is_second,
        )
        if deleted:
            return await ctx.success(
                f"removed **{slot}** message for {channel.mention}"
            )
        return await ctx.fail(f"no **{slot}** message set for {channel.mention}")

    @boosts.command(
        name="view",
        example=",boosts view #general",
        aliases=["check"],
        flags=Parameters,
        description="preview the boost message for a channel",
        usage="[channel] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_view(
        self, ctx, channel: Optional[TextChannel] = None
    ) -> Message:
        channel = channel or ctx.channel
        is_second = bool(ctx.flags.get("twoboosts"))
        msg = await Settings.get_message(
            self.db, ctx.guild.id, channel.id, is_second,
        )
        if not msg:
            slot = "second-boost" if is_second else "first-boost"
            return await ctx.fail(f"no **{slot}** message for {channel.mention}")
        return await self.bot.send_embed(ctx, msg, member=ctx.author)

    @boosts.command(
        name="list",
        example=",boosts list",
        description="list all boost channels in this server",
    )
    @has_permissions(manage_guild=True)
    async def boosts_list(self, ctx) -> Message:
        rows = await Settings.get_all(self.db, ctx.guild.id)
        lines = []
        for row in rows:
            ch = ctx.guild.get_channel(row["channel_id"])
            if not ch:
                continue
            tag = "2nd" if row.get("is_second") else "1st"
            lines.append(f"{ch.mention} (`{ch.id}`) - **{tag} boost**")
        if not lines:
            return await ctx.search("no boost channels set up")
        return await ctx.paginate(Embed(title="Boost Channels"), lines)

    @boosts.command(
        name="variables",
        aliases=["vars"],
        example=",boosts variables",
        description="show available template variables for boost scripts",
    )
    @has_permissions(manage_guild=True)
    async def boosts_variables(self, ctx) -> Message:
        return await ctx.normal(
            "Boost scripts support `{embed}` / `{container}` / plain text plus "
            "standard variables (`{user}`, `{guild}`, …).\n"
            "Use `--twoboosts` when adding to target the **second boost** slot.\n"
            "docs: https://vain.bot/resources/scripting/variables",
            emoji=":information_source:",
        )

    async def on_member_boost(self, member: Member) -> None:
        if member.premium_since is None:
            self._boost_counts.get(member.guild.id, {}).pop(member.id, None)
            return
        if await self.db.get_antiraid_state(member.guild.id):
            return

        guild_counts = self._boost_counts[member.guild.id]
        prev = guild_counts.get(member.id, 0)
        count = prev + 1
        guild_counts[member.id] = count
        is_second = count >= 2

        rate = await self.bot.object_cache.ratelimited(
            f"boost_messages:{member.guild.id}", 3, 5
        )
        if rate != 0:
            await sleep(rate)

        async with self.boost_locks[f"boost_messages:{member.guild.id}"]:
            rows = await Settings.fetch_by_second(
                self.bot.db, member.guild.id, is_second,
            )
            if not rows and is_second:
                rows = await Settings.fetch_by_second(
                    self.bot.db, member.guild.id, False,
                )
            for row in rows:
                ch = member.guild.get_channel(row["channel_id"])
                if not ch:
                    continue
                try:
                    builder = await self.create_embed(
                        row["message"] if isinstance(row, dict) else row.message,
                        member=member,
                        user=member,
                    )
                except Exception:
                    continue
                sd = row["self_destruct"] if isinstance(row, dict) else row.self_destruct
                if sd:
                    builder.data["delete_after"] = sd
                with contextlib.suppress(Exception):
                    await builder.send(ch)
