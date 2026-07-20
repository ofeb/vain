from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from random import sample
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands, tasks
from discord.ext.commands import Cog

from core.managers.values import color

if TYPE_CHECKING:
    from core.vain import Vain


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def build_giveaway_embed(
    *,
    prize: str,
    end_time: datetime | None = None,
    winners: int = 1,
    host: str | None = None,
    requirements: list[str] | None = None,
    ended: bool = False,
    winner_mentions: str | None = None,
    no_entries: bool = False,
) -> discord.Embed:
    """Minimal giveaway panel using **bold** and -# captions."""
    prize = (prize or "Giveaway").strip() or "Giveaway"

    if ended:
        if no_entries:
            desc = "-# ended · **no valid entries**"
        elif winner_mentions:
            desc = f"-# ended · {winner_mentions} won **{prize}**"
        else:
            desc = "-# ended"
    else:
        ends = (
            discord.utils.format_dt(end_time, style="R")
            if end_time is not None
            else "soon"
        )
        wlabel = f"**{winners}** winner" if winners == 1 else f"**{winners}** winners"
        host_bit = f" · hosted by {host}" if host else ""
        desc = f"-# react with 🎉 · ends {ends} · {wlabel}{host_bit}"
        if requirements:
            desc += "\n" + "\n".join(f"-# {line}" for line in requirements)

    return discord.Embed(title=prize, description=desc, color=color.base)


def build_winner_embed(*, prize: str, winner_mentions: str, reroll: bool = False) -> discord.Embed:
    label = "rerolled" if reroll else "won"
    return discord.Embed(
        title=prize,
        description=f"-# {winner_mentions} {label} **{prize}**",
        color=color.base,
    )


class GiveawayEvents(Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._end_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        self.poll_expired_giveaways.start()
        
        asyncio.create_task(self._reschedule_active())

    async def cog_unload(self) -> None:
        self.poll_expired_giveaways.cancel()
        for task in list(self._end_tasks.values()):
            task.cancel()
        self._end_tasks.clear()

    async def _reschedule_active(self) -> None:
        await self.bot.wait_until_ready()
        try:
            rows = await self.bot.db.fetch(
                """
                SELECT message_id, expiration FROM giveaways
                WHERE win_message_id IS NULL AND expiration > NOW()
                """
            )
        except Exception:
            return
        for row in rows or []:
            self.schedule_end(int(row["message_id"]), row["expiration"])

    def schedule_end(self, message_id: int, end_time: datetime) -> None:
        """Fire end_giveaway at *end_time* (cancels any prior schedule for this id)."""
        old = self._end_tasks.pop(message_id, None)
        if old and not old.done():
            old.cancel()

        async def _wait() -> None:
            try:
                delay = (_as_aware(end_time) - _utcnow()).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
                row = await self.bot.db.fetchrow(
                    "SELECT * FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
                    message_id,
                )
                if row:
                    await self.end_giveaway(dict(row))
            except asyncio.CancelledError:
                return
            except Exception:
                pass
            finally:
                self._end_tasks.pop(message_id, None)

        self._end_tasks[message_id] = asyncio.create_task(_wait())

    @tasks.loop(seconds=5.0)
    async def poll_expired_giveaways(self) -> None:
        """Backup for restarts / missed schedules — keep the interval short."""
        try:
            rows = await self.bot.db.fetch(
                """
                SELECT * FROM giveaways
                WHERE win_message_id IS NULL
                  AND expiration <= NOW()
                LIMIT 25
                """
            )
        except Exception:
            return
        for row in rows or []:
            await self.end_giveaway(dict(row))

    @poll_expired_giveaways.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def check_requirements(self, member: discord.Member, requirements: dict) -> bool:
        if requirements.get("required_roles"):
            member_roles = {role.id for role in member.roles}
            required = set(requirements["required_roles"] or [])
            if required and not (member_roles & required):
                return False

        if requirements.get("min_level"):
            level = await self.bot.db.fetchval(
                "SELECT level FROM levels WHERE user_id = $1 AND guild_id = $2",
                member.id,
                member.guild.id,
            )
            if level is not None and level < requirements["min_level"]:
                return False

        if requirements.get("max_level"):
            level = await self.bot.db.fetchval(
                "SELECT level FROM levels WHERE user_id = $1 AND guild_id = $2",
                member.id,
                member.guild.id,
            )
            if level is not None and level > requirements["max_level"]:
                return False

        return True

    @Cog.listener("on_raw_reaction_add")
    async def on_giveaway_entry(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) != "🎉":
            return

        giveaway = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
            payload.message_id,
        )
        if not giveaway:
            return

        exp = _as_aware(giveaway.get("expiration"))
        if exp and _utcnow() > exp:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        requirements = {
            "required_roles": giveaway.get("required_roles"),
            "min_level": giveaway.get("min_level"),
            "max_level": giveaway.get("max_level"),
        }
        if not await self.check_requirements(member, requirements):
            
            channel = guild.get_channel(payload.channel_id) or self.bot.get_channel(
                payload.channel_id
            )
            if channel:
                try:
                    msg = await channel.fetch_message(payload.message_id)
                    await msg.remove_reaction(payload.emoji, member)
                except Exception:
                    pass
            return

        async with self.locks[f"giveaway:{payload.message_id}"]:
            row = await self.bot.db.fetchrow(
                "SELECT entries FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
                payload.message_id,
            )
            if not row:
                return
            entries = list(row.get("entries") or [])
            if member.id in entries:
                return
            entries.append(member.id)
            await self.bot.db.execute(
                "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                entries,
                payload.message_id,
            )

    @Cog.listener("on_raw_reaction_remove")
    async def on_giveaway_leave(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) != "🎉":
            return
        giveaway = await self.bot.db.fetchrow(
            "SELECT entries, win_message_id FROM giveaways WHERE message_id = $1",
            payload.message_id,
        )
        if not giveaway or giveaway.get("win_message_id"):
            return

        async with self.locks[f"giveaway:{payload.message_id}"]:
            entries = list(giveaway.get("entries") or [])
            if payload.user_id not in entries:
                return
            entries.remove(payload.user_id)
            await self.bot.db.execute(
                "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                entries,
                payload.message_id,
            )

    @Cog.listener("on_giveaway_end")
    async def on_giveaway_end_event(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        giveaway: dict,
    ) -> None:
        await self.end_giveaway(giveaway)

    async def end_giveaway(self, giveaway: dict[str, Any], *, force: bool = False) -> list[discord.Member]:
        """End a giveaway: edit panel, pick winners, reply with ping + embed."""
        message_id = int(giveaway["message_id"])
        async with self.locks[f"giveaway-end:{message_id}"]:
            
            row = await self.bot.db.fetchrow(
                "SELECT * FROM giveaways WHERE message_id = $1",
                message_id,
            )
            if not row:
                return []
            if row.get("win_message_id") and not force:
                return []
            giveaway = dict(row)

            guild = self.bot.get_guild(int(giveaway["guild_id"]))
            if not guild:
                return []
            channel = guild.get_channel(int(giveaway["channel_id"])) or self.bot.get_channel(
                int(giveaway["channel_id"])
            )
            if channel is None:
                return []

            try:
                message = await channel.fetch_message(message_id)
            except (discord.NotFound, discord.HTTPException):
                return []

            prize = giveaway.get("prize") or "Giveaway"
            entries = list(giveaway.get("entries") or [])
            
            if not entries and message.reactions:
                for reaction in message.reactions:
                    if str(reaction.emoji) == "🎉":
                        try:
                            async for user in reaction.users():
                                if not user.bot:
                                    entries.append(user.id)
                        except Exception:
                            pass
                        break

            members = [
                m
                for uid in entries
                if (m := guild.get_member(uid)) is not None and not m.bot
            ]
            winners_count = max(1, int(giveaway.get("winner_count") or 1))

            if not members:
                ended = build_giveaway_embed(prize=prize, ended=True, no_entries=True)
                try:
                    await message.edit(embed=ended)
                except Exception:
                    pass
                
                await self.bot.db.execute(
                    "UPDATE giveaways SET win_message_id = $1, entries = $2 WHERE message_id = $3",
                    message.id,
                    entries,
                    message_id,
                )
                return []

            winners = sample(members, min(winners_count, len(members)))
            mentions = ", ".join(w.mention for w in winners)

            ended = build_giveaway_embed(
                prize=prize,
                ended=True,
                winner_mentions=mentions,
            )
            try:
                await message.edit(embed=ended)
            except Exception:
                pass

            win_embed = build_winner_embed(prize=prize, winner_mentions=mentions)
            try:
                win_msg = await message.reply(
                    content=mentions,
                    embed=win_embed,
                    allowed_mentions=discord.AllowedMentions(users=True),
                    mention_author=False,
                )
            except Exception:
                win_msg = await channel.send(
                    content=mentions,
                    embed=win_embed,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )

            await self.bot.db.execute(
                "UPDATE giveaways SET win_message_id = $1, entries = $2 WHERE message_id = $3",
                win_msg.id,
                entries,
                message_id,
            )
            return winners

    async def reroll_giveaway(
        self,
        giveaway: dict[str, Any],
        *,
        winners_count: int = 1,
        channel: discord.abc.Messageable | None = None,
    ) -> list[discord.Member]:
        message_id = int(giveaway["message_id"])
        guild = self.bot.get_guild(int(giveaway["guild_id"]))
        if not guild:
            return []
        channel = channel or guild.get_channel(int(giveaway["channel_id"]))
        if channel is None:
            return []

        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.HTTPException):
            return []

        prize = giveaway.get("prize") or "Giveaway"
        entries = list(giveaway.get("entries") or [])
        members = [
            m
            for uid in entries
            if (m := guild.get_member(uid)) is not None and not m.bot
        ]
        if not members:
            return []

        count = max(1, min(int(winners_count or 1), len(members)))
        winners = sample(members, count)
        mentions = ", ".join(w.mention for w in winners)

        ended = build_giveaway_embed(
            prize=prize,
            ended=True,
            winner_mentions=mentions,
        )
        try:
            await message.edit(embed=ended)
        except Exception:
            pass

        win_embed = build_winner_embed(
            prize=prize, winner_mentions=mentions, reroll=True
        )
        try:
            win_msg = await message.reply(
                content=mentions,
                embed=win_embed,
                allowed_mentions=discord.AllowedMentions(users=True),
                mention_author=False,
            )
        except Exception:
            win_msg = await channel.send(
                content=mentions,
                embed=win_embed,
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        await self.bot.db.execute(
            "UPDATE giveaways SET win_message_id = $1 WHERE message_id = $2",
            win_msg.id,
            message_id,
        )
        return winners
