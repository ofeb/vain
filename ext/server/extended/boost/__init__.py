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
from lib.classes.flags.guilds import Parameters
from core.managers.permissions import has_permissions


class BoostCommands(Package):
    """Boost messages — one first-boost and one second-boost script per channel."""

    def __init__(self, bot):
        super().__init__(bot)
        self.boost_locks = defaultdict(Lock)
        # guild_id -> user_id -> how many boost events we've already announced
        self._boost_counts: dict[int, dict[int, int]] = defaultdict(dict)

    async def cog_load(self) -> None:
        with contextlib.suppress(Exception):
            await self.db.execute(
                "ALTER TABLE boost_messages ADD COLUMN IF NOT EXISTS is_second BOOLEAN NOT NULL DEFAULT FALSE"
            )
        with contextlib.suppress(Exception):
            # Prefer unique (guild, channel, is_second) if old PK was (guild, channel)
            await self.db.execute(
                """
                DO $$ BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'boost_messages_guild_channel_second_key'
                  ) THEN
                    ALTER TABLE boost_messages
                      DROP CONSTRAINT IF EXISTS boost_messages_pkey;
                    ALTER TABLE boost_messages
                      ADD CONSTRAINT boost_messages_guild_channel_second_key
                      UNIQUE (guild_id, channel_id, is_second);
                  END IF;
                END $$;
                """
            )

    @group(
        name="boosts",
        example=",boosts add #general thanks {user.mention}!",
        aliases=["boost"],
        invoke_without_command=True,
        description="Manage messages sent when a member boosts the server",
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
        if timer is not None:
            if timer < 6:
                return await ctx.warn("self-destruct timer must be at least `6` seconds")
            if timer > 60:
                return await ctx.warn("self-destruct timer must stay under `60` seconds")

        exists = await self.db.fetchval(
            """SELECT 1 FROM boost_messages
               WHERE guild_id = $1 AND channel_id = $2 AND is_second = $3""",
            ctx.guild.id,
            channel.id,
            is_second,
        )
        slot = "second-boost" if is_second else "first-boost"
        if edit:
            if not exists:
                return await ctx.fail(
                    f"no **{slot}** message for {channel.mention} — use "
                    f"`{ctx.clean_prefix}boosts add` first"
                    + (" `--twoboosts`" if is_second else "")
                )
            await self.db.execute(
                """UPDATE boost_messages SET message = $1, self_destruct = $2
                   WHERE guild_id = $3 AND channel_id = $4 AND is_second = $5""",
                script,
                timer,
                ctx.guild.id,
                channel.id,
                is_second,
            )
            verb = "updated"
        else:
            if exists:
                return await ctx.fail(
                    f"already a **{slot}** message in {channel.mention} — "
                    f"use `{ctx.clean_prefix}boosts edit` or `{ctx.clean_prefix}boosts remove`"
                    + (" `--twoboosts`" if is_second else "")
                )
            try:
                await self.db.execute(
                    """INSERT INTO boost_messages
                       (guild_id, channel_id, message, self_destruct, is_second)
                       VALUES ($1, $2, $3, $4, $5)""",
                    ctx.guild.id,
                    channel.id,
                    script,
                    timer,
                    is_second,
                )
            except UniqueViolationError:
                return await ctx.fail(
                    f"already a **{slot}** message in {channel.mention}"
                )
            verb = "set"

        extra = f"\nmessages will delete after `{timer}` seconds" if timer else ""
        return await ctx.success(
            f"**{slot}** message {verb} for {channel.mention}{extra}"
        )

    @boosts.command(
        name="add",
        example=",boosts add #general thanks {user.mention}!  |  ,boosts add thanks again! --twoboosts",
        aliases=["create", "set"],
        flags=Parameters,
        description="Add a boost message (defaults to current channel). Use --twoboosts for the 2nd boost script.",
        usage="[channel] <script> [--self_destruct <seconds>] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_add(
        self, ctx, channel: Optional[TextChannel] = None, *, message: EmbedConverter
    ) -> Message:
        channel = channel or ctx.channel
        timer = ctx.flags.get("self_destruct")
        is_second = bool(ctx.flags.get("twoboosts"))
        return await self._upsert(
            ctx,
            channel,
            message.script,
            timer,
            is_second=is_second,
            edit=False,
        )

    @boosts.command(
        name="edit",
        aliases=["change", "update"],
        example=",boosts edit #general thanks {user.mention} for the boost!",
        flags=Parameters,
        description="Edit an existing boost script (defaults to current channel)",
        usage="[channel] <script> [--self_destruct <seconds>] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_edit(
        self, ctx, channel: Optional[TextChannel] = None, *, message: EmbedConverter
    ) -> Message:
        channel = channel or ctx.channel
        timer = ctx.flags.get("self_destruct")
        is_second = bool(ctx.flags.get("twoboosts"))
        return await self._upsert(
            ctx,
            channel,
            message.script,
            timer,
            is_second=is_second,
            edit=True,
        )

    @boosts.command(
        name="remove",
        example=",boosts remove #general  |  ,boosts remove --twoboosts",
        aliases=["delete", "del"],
        flags=Parameters,
        description="Remove a boost message (defaults to current channel). --twoboosts removes the second-boost slot.",
        usage="[channel] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_remove(
        self, ctx, channel: Optional[TextChannel] = None
    ) -> Message:
        channel = channel or ctx.channel
        is_second = bool(ctx.flags.get("twoboosts"))
        slot = "second-boost" if is_second else "first-boost"
        deleted = await self.db.fetchval(
            """DELETE FROM boost_messages
               WHERE guild_id = $1 AND channel_id = $2 AND is_second = $3
               RETURNING channel_id""",
            ctx.guild.id,
            channel.id,
            is_second,
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
        description="Preview the boost message for a channel",
        usage="[channel] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_view(
        self, ctx, channel: Optional[TextChannel] = None
    ) -> Message:
        channel = channel or ctx.channel
        is_second = bool(ctx.flags.get("twoboosts"))
        msg = await self.db.fetchval(
            """SELECT message FROM boost_messages
               WHERE guild_id = $1 AND channel_id = $2 AND is_second = $3""",
            ctx.guild.id,
            channel.id,
            is_second,
        )
        if not msg:
            slot = "second-boost" if is_second else "first-boost"
            return await ctx.fail(f"no **{slot}** message for {channel.mention}")
        return await self.bot.send_embed(ctx, msg, member=ctx.author)

    @boosts.command(
        name="list",
        example=",boosts list",
        description="List all boost channels in this server",
    )
    @has_permissions(manage_guild=True)
    async def boosts_list(self, ctx) -> Message:
        rows = await self.db.fetch(
            """SELECT channel_id, is_second FROM boost_messages WHERE guild_id = $1""",
            ctx.guild.id,
        )
        lines = []
        for row in rows:
            ch = ctx.guild.get_channel(row["channel_id"])
            if not ch:
                continue
            tag = "2nd" if row.get("is_second") else "1st"
            lines.append(f"{ch.mention} (`{ch.id}`) — **{tag} boost**")
        if not lines:
            return await ctx.search("no boost channels set up")
        return await ctx.paginate(Embed(title="Boost Channels"), lines)

    @boosts.command(
        name="variables",
        aliases=["vars"],
        example=",boosts variables",
        description="Show available template variables for boost scripts",
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

    async def on_member_update(self, before: Member, after: Member) -> None:
        # Fire once per boost event (premium_since changes from None→set or refreshes)
        if before.premium_since == after.premium_since:
            return
        if after.premium_since is None:
            # lost boost — reset counter so next boost is treated as first again
            self._boost_counts.get(after.guild.id, {}).pop(after.id, None)
            return
        if await self.db.get_antiraid_state(after.guild.id):
            return

        # Count successive boosts while they remain a booster
        guild_counts = self._boost_counts[after.guild.id]
        prev = guild_counts.get(after.id, 0)
        # first event while boosting → 1, subsequent premium_since changes → 2+
        count = prev + 1
        guild_counts[after.id] = count
        is_second = count >= 2

        rate = await self.bot.object_cache.ratelimited(
            f"boost_messages:{after.guild.id}", 3, 5
        )
        if rate != 0:
            await sleep(rate)

        async with self.boost_locks[f"boost_messages:{after.guild.id}"]:
            rows = await self.bot.db.fetch(
                """SELECT * FROM boost_messages
                   WHERE guild_id = $1 AND is_second = $2""",
                after.guild.id,
                is_second,
            )
            # Fall back to first-boost script if no dedicated second slot
            if not rows and is_second:
                rows = await self.bot.db.fetch(
                    """SELECT * FROM boost_messages
                       WHERE guild_id = $1 AND is_second = FALSE""",
                    after.guild.id,
                )
            for row in rows:
                ch = after.guild.get_channel(row["channel_id"])
                if not ch:
                    continue
                try:
                    builder = await self.create_embed(
                        row["message"] if isinstance(row, dict) else row.message,
                        member=after,
                        user=after,
                    )
                except Exception:
                    continue
                sd = row["self_destruct"] if isinstance(row, dict) else row.self_destruct
                if sd:
                    builder.data["delete_after"] = sd
                with contextlib.suppress(Exception):
                    await builder.send(ch)
