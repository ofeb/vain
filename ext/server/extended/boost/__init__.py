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


def _boost_type_label(is_second: bool) -> str:
    return "two-boosts" if is_second else "first-boost"


class BoostCommands(Package):
    """boost message setup commands

    Rules:
    - Exactly **one** first-boost message and **one** two-boosts message per channel.
    - Adding when a slot is taken forces edit or remove (no silent overwrite).
    - Every detected boost (premium_since change) fires **all** configured messages
      for the guild — one message per boost event, not one message covering two boosts.
    - Flag ``--twoboosts`` (aliases: ``2ndboost``, ``tb``, ``2``, ``secondboost``)
      targets the second-boost slot; omit the flag for the first-boost slot.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.boost_locks = defaultdict(Lock)

    async def cog_load(self) -> None:
        await self._ensure_schema()

    async def _ensure_schema(self) -> None:
        """Migrate boost_messages to support first + two-boosts slots per channel."""
        statements = [
            "ALTER TABLE boost_messages ADD COLUMN IF NOT EXISTS is_second BOOLEAN NOT NULL DEFAULT FALSE",
            # Drop old PK if present and recreate unique on (guild, channel, is_second)
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'boost_messages'
                      AND constraint_type = 'PRIMARY KEY'
                      AND constraint_name = 'boost_messages_pkey'
                ) THEN
                    ALTER TABLE boost_messages DROP CONSTRAINT boost_messages_pkey;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END $$;
            """,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'boost_messages_guild_channel_second_key'
                ) THEN
                    ALTER TABLE boost_messages
                        ADD CONSTRAINT boost_messages_guild_channel_second_key
                        UNIQUE (guild_id, channel_id, is_second);
                END IF;
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END $$;
            """,
        ]
        for sql in statements:
            try:
                await self.db.execute(sql)
            except Exception:
                pass

    def _is_second(self, ctx) -> bool:
        flags = getattr(ctx, "flags", None)
        if flags is None:
            return False
        return bool(getattr(flags, "twoboosts", False) or (isinstance(flags, dict) and flags.get("twoboosts")))

    @group(
        name="boosts",
        example=",boosts add #general thanks {user.mention}!  |  ,boosts add thanks! --twoboosts",
        aliases=["boost"],
        invoke_without_command=True,
        description="Manage boost messages (one first-boost + one two-boosts message per channel)",
    )
    @has_permissions(manage_guild=True)
    async def boosts(self, ctx) -> Message:
        """manage boost messages"""
        return await ctx.send_help()

    @boosts.command(
        name="add",
        example=",boosts add #general thanks {user.mention}!  |  ,boosts add Thanks for the 2nd boost! --twoboosts",
        aliases=["create", "set"],
        flags=Parameters,
        description="Add a boost message (defaults to current channel). Use --twoboosts for the second-boost slot.",
        usage="[channel] <script> [--self_destruct <seconds>] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_add(
        self, ctx, channel: Optional[TextChannel] = None, *, message: EmbedConverter
    ) -> Message:
        """add a boost channel message (first or two-boosts slot)"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only set boost messages in text channels")

        is_second = self._is_second(ctx)
        slot = _boost_type_label(is_second)

        timer = None
        flags = getattr(ctx, "flags", None)
        if flags is not None:
            timer = getattr(flags, "self_destruct", None) if not isinstance(flags, dict) else flags.get("self_destruct")
        if timer:
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
        if exists:
            return await ctx.fail(
                f"there's already a **{slot}** message for {channel.mention}\n"
                f"remove it first with `{ctx.clean_prefix}boosts remove{' --twoboosts' if is_second else ''}` "
                f"or edit with `{ctx.clean_prefix}boosts edit{' --twoboosts' if is_second else ''}`"
            )

        try:
            await self.db.execute(
                """INSERT INTO boost_messages (guild_id, channel_id, message, self_destruct, is_second)
                   VALUES ($1, $2, $3, $4, $5)""",
                ctx.guild.id,
                channel.id,
                message.script,
                timer,
                is_second,
            )
        except UniqueViolationError:
            return await ctx.fail(
                f"there's already a **{slot}** message for {channel.mention}, "
                f"remove it first or use `{ctx.clean_prefix}boosts edit{' --twoboosts' if is_second else ''}`"
            )

        extra = f"\nmessages will delete after `{timer}` seconds" if timer else ""
        return await ctx.success(
            f"**{slot}** message set for {channel.mention}{extra}"
        )

    @boosts.command(
        name="edit",
        aliases=["change", "update"],
        example=",boosts edit #general thanks {user.mention}!  |  ,boosts edit Thanks again! --twoboosts",
        flags=Parameters,
        description="Edit the boost script for a channel (defaults to current). Use --twoboosts for the second-boost slot.",
        usage="[channel] <script> [--self_destruct <seconds>] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_edit(
        self, ctx, channel: Optional[TextChannel] = None, *, message: EmbedConverter
    ) -> Message:
        """edit an existing boost message script"""
        channel = channel or ctx.channel
        is_second = self._is_second(ctx)
        slot = _boost_type_label(is_second)

        timer = None
        flags = getattr(ctx, "flags", None)
        if flags is not None:
            timer = getattr(flags, "self_destruct", None) if not isinstance(flags, dict) else flags.get("self_destruct")
        if timer:
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
        if not exists:
            return await ctx.fail(
                f"no **{slot}** message for {channel.mention} — "
                f"use `{ctx.clean_prefix}boosts add{' --twoboosts' if is_second else ''}` first"
            )

        await self.db.execute(
            """UPDATE boost_messages SET message = $1, self_destruct = $2
               WHERE guild_id = $3 AND channel_id = $4 AND is_second = $5""",
            message.script,
            timer,
            ctx.guild.id,
            channel.id,
            is_second,
        )
        extra = f"\nmessages will delete after `{timer}` seconds" if timer else ""
        return await ctx.success(f"updated **{slot}** message for {channel.mention}{extra}")

    @boosts.command(
        name="remove",
        example=",boosts remove #general  |  ,boosts remove --twoboosts",
        aliases=["delete", "del"],
        flags=Parameters,
        description="Remove a boost message from a channel (defaults to current). Use --twoboosts for the second-boost slot.",
        usage="[channel] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_remove(self, ctx, channel: Optional[TextChannel] = None) -> Message:
        """remove a boost channel message"""
        channel = channel or ctx.channel
        is_second = self._is_second(ctx)
        slot = _boost_type_label(is_second)

        deleted = await self.db.fetchval(
            """DELETE FROM boost_messages
               WHERE guild_id = $1 AND channel_id = $2 AND is_second = $3
               RETURNING channel_id""",
            ctx.guild.id,
            channel.id,
            is_second,
        )
        if deleted:
            return await ctx.success(f"removed **{slot}** message for {channel.mention}")
        return await ctx.fail(f"no **{slot}** message set for {channel.mention}")

    @boosts.command(
        name="view",
        example=",boosts view #general  |  ,boosts view --twoboosts",
        aliases=["check"],
        flags=Parameters,
        description="Preview the boost message for a channel (defaults to current). Use --twoboosts for the second-boost slot.",
        usage="[channel] [--twoboosts]",
    )
    @has_permissions(manage_guild=True)
    async def boosts_view(self, ctx, channel: Optional[TextChannel] = None) -> Message:
        """preview boost message"""
        channel = channel or ctx.channel
        is_second = self._is_second(ctx)
        slot = _boost_type_label(is_second)

        msg = await self.db.fetchval(
            """SELECT message FROM boost_messages
               WHERE guild_id = $1 AND channel_id = $2 AND is_second = $3""",
            ctx.guild.id,
            channel.id,
            is_second,
        )
        if not msg:
            return await ctx.fail(f"no **{slot}** message for {channel.mention}")
        await ctx.normal(f"**{slot}** message for {channel.mention}")
        return await self.bot.send_embed(ctx, msg, member=ctx.author)

    @boosts.command(
        name="list",
        example=",boosts list",
        description="List all boost channels and message types in this server",
    )
    @has_permissions(manage_guild=True)
    async def boosts_list(self, ctx) -> Message:
        """list all boost channels"""
        rows = await self.db.fetch(
            """SELECT channel_id, COALESCE(is_second, FALSE) AS is_second
               FROM boost_messages WHERE guild_id = $1
               ORDER BY channel_id, is_second""",
            ctx.guild.id,
        )
        lines = []
        for row in rows:
            ch = ctx.guild.get_channel(row["channel_id"])
            if not ch:
                continue
            slot = _boost_type_label(bool(row["is_second"]))
            lines.append(f"{ch.mention} — **{slot}** (`{ch.id}`)")
        if not lines:
            return await ctx.search("no boost channels set up")
        return await ctx.paginate(Embed(title="Boost Messages"), lines)

    @boosts.command(
        name="variables",
        aliases=["vars"],
        example=",boosts variables",
        description="Show available template variables for boost scripts",
    )
    @has_permissions(manage_guild=True)
    async def boosts_variables(self, ctx) -> Message:
        """show available template vars"""
        return await ctx.normal(
            "check all **variables** at: https://vain.bot/resources/scripting/variables\n"
            "-# Flag: `--twoboosts` / `--2ndboost` / `--tb` / `--2` / `--secondboost` for the second-boost slot",
            emoji=":information_source:",
        )

    async def on_member_boost(self, member: Member) -> None:
        """send boost messages when a member starts boosting

        Fires for **every** boost event (premium_since set/changed).
        Both first-boost and two-boosts messages are sent independently —
        one message per configured slot per boost, not one shared message.
        """
        award_row = await self.bot.db.fetchrow(
            "SELECT award_id FROM booster_roles WHERE guild_id = $1",
            member.guild.id,
        )
        if award_row and award_row.get("award_id"):
            award_role = member.guild.get_role(int(award_row["award_id"]))
            if award_role and award_role not in member.roles:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await member.add_roles(award_role, reason="Booster award role")

        rate = await self.bot.object_cache.ratelimited(
            f"boost_messages:{member.guild.id}", 1, 5
        )
        if rate != 0:
            await sleep(5)

        async with self.boost_locks[f"boost_messages:{member.guild.id}"]:
            for row in await self.bot.db.fetch(
                """SELECT * FROM boost_messages WHERE guild_id = $1""",
                member.guild.id,
            ):
                channel = member.guild.get_channel(row["channel_id"])
                if not channel:
                    continue

                try:
                    builder = await self.create_embed(
                        row["message"] if isinstance(row, dict) else row.message,
                        member=member,
                        user=member,
                    )
                except Exception:
                    continue

                self_destruct = row.get("self_destruct") if isinstance(row, dict) else getattr(row, "self_destruct", None)
                if self_destruct:
                    builder.data["delete_after"] = self_destruct

                try:
                    await builder.send(channel)
                except Exception:
                    continue
