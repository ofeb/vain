from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timezone
from random import sample
from typing import Any

import discord
from discord.ext import commands, tasks
from discord.ext.commands import Cog

from core.managers.values import color

from ..views import (
    EntriesPaginator,
    build_dm_win_view,
    build_entries_pages,
    build_giveaway_panel,
    build_win_announce_panel,
)

DEFAULT_DM_SCRIPT = (
    "{embed}$v{title: You won a giveaway!}$v"
    "{description: **Congratulations** {user.mention}\n\n"
    "> You won **{prize}** in **{guild.name}**\n"
    "-# thanks for entering}$v{color: #A8D8A8}"
)


def _naive_utcnow() -> datetime:
    return datetime.utcnow()


def _as_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class GiveawayEvents(Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._end_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        await self._ensure_tables()
        self.poll_expired_giveaways.start()
        asyncio.create_task(self._reschedule_active())

    async def cog_unload(self) -> None:
        self.poll_expired_giveaways.cancel()
        for task in list(self._end_tasks.values()):
            task.cancel()
        self._end_tasks.clear()

    async def _ensure_tables(self) -> None:
        with suppress(Exception):
            await self.bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS giveaway_settings (
                    guild_id BIGINT PRIMARY KEY,
                    dm_on_win BOOLEAN NOT NULL DEFAULT TRUE,
                    dm_script TEXT
                )
                """
            )
        with suppress(Exception):
            await self.bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS giveaways (
                    guild_id BIGINT,
                    channel_id BIGINT,
                    message_id BIGINT,
                    prize VARCHAR(255),
                    expiration TIMESTAMP,
                    winner_count INT DEFAULT 1,
                    hosts BIGINT[],
                    entries BIGINT[],
                    max_level INT,
                    min_level INT,
                    required_roles BIGINT[],
                    win_message_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (message_id)
                )
                """
            )

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        row = None
        with suppress(Exception):
            row = await self.bot.db.fetchrow(
                "SELECT * FROM giveaway_settings WHERE guild_id = $1",
                guild_id,
            )
        if not row:
            return {"dm_on_win": True, "dm_script": None}
        return {
            "dm_on_win": bool(row.get("dm_on_win", True)),
            "dm_script": row.get("dm_script"),
        }

    async def set_dm_on_win(self, guild_id: int, enabled: bool) -> None:
        await self.bot.db.execute(
            """
            INSERT INTO giveaway_settings (guild_id, dm_on_win)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET dm_on_win = EXCLUDED.dm_on_win
            """,
            guild_id,
            enabled,
        )

    async def set_dm_script(self, guild_id: int, script: str | None) -> None:
        await self.bot.db.execute(
            """
            INSERT INTO giveaway_settings (guild_id, dm_script)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET dm_script = EXCLUDED.dm_script
            """,
            guild_id,
            script,
        )

    def schedule_end(self, message_id: int, end_time: datetime) -> None:
        old = self._end_tasks.pop(message_id, None)
        if old and not old.done():
            old.cancel()

        async def _wait() -> None:
            try:
                target = _as_naive(end_time) or _naive_utcnow()
                delay = (target - _naive_utcnow()).total_seconds()
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

    async def _reschedule_active(self) -> None:
        await self.bot.wait_until_ready()
        with suppress(Exception):
            rows = await self.bot.db.fetch(
                """
                SELECT message_id, expiration FROM giveaways
                WHERE win_message_id IS NULL AND expiration > NOW()
                """
            )
            for row in rows or []:
                self.schedule_end(int(row["message_id"]), row["expiration"])

    @tasks.loop(seconds=5.0)
    async def poll_expired_giveaways(self) -> None:
        with suppress(Exception):
            rows = await self.bot.db.fetch(
                """
                SELECT * FROM giveaways
                WHERE win_message_id IS NULL AND expiration <= NOW()
                LIMIT 25
                """
            )
            for row in rows or []:
                await self.end_giveaway(dict(row))

    @poll_expired_giveaways.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()

    def _guild_icon(self, guild: discord.Guild | None) -> str | None:
        if guild and guild.icon:
            return str(guild.icon.url)
        return None

    def _host_mention(self, record: dict) -> str:
        hosts = record.get("hosts") or []
        if hosts:
            return f"<@{int(hosts[0])}>"
        return "unknown"

    def _jump_url(self, guild_id: int, channel_id: int, message_id: int) -> str:
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    async def rebuild_panel_message(
        self,
        message: discord.Message,
        record: dict,
        *,
        ended: bool = False,
        winner_mentions: str | None = None,
        no_entries: bool = False,
    ) -> None:
        guild = message.guild
        entries = list(record.get("entries") or [])
        panel = build_giveaway_panel(
            message_id=int(record["message_id"]),
            prize=str(record.get("prize") or "Giveaway"),
            end_time=_as_naive(record.get("expiration")),
            winners=int(record.get("winner_count") or 1),
            host_mention=self._host_mention(record),
            entries=len(entries),
            guild_icon=self._guild_icon(guild),
            ended=ended,
            winner_mentions=winner_mentions,
            no_entries=no_entries,
            accent=color.base,
        )
        await message.edit(content=None, embed=None, view=panel)

    async def check_requirements(self, member: discord.Member, requirements: dict) -> bool:
        if requirements.get("required_roles"):
            member_roles = {role.id for role in member.roles}
            required = set(requirements["required_roles"] or [])
            if required and not (member_roles & required):
                return False
        if requirements.get("min_level") is not None:
            level = await self.bot.db.fetchval(
                "SELECT level FROM levels WHERE user_id = $1 AND guild_id = $2",
                member.id,
                member.guild.id,
            )
            if level is not None and level < requirements["min_level"]:
                return False
        if requirements.get("max_level") is not None:
            level = await self.bot.db.fetchval(
                "SELECT level FROM levels WHERE user_id = $1 AND guild_id = $2",
                member.id,
                member.guild.id,
            )
            if level is not None and level > requirements["max_level"]:
                return False
        return True

    @Cog.listener("on_interaction")
    async def on_giveaway_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component:
            return
        data = interaction.data or {}
        cid = str(data.get("custom_id") or "")
        if not cid.startswith("gw:"):
            return
        parts = cid.split(":")
        if len(parts) < 3:
            return
        action, raw_id = parts[1], parts[2]
        if not raw_id.isdigit():
            return
        message_id = int(raw_id)

        if action == "enter":
            await self._handle_enter(interaction, message_id)
        elif action == "entries":
            await self._handle_view_entries(interaction, message_id)

    async def _handle_enter(
        self, interaction: discord.Interaction, message_id: int
    ) -> None:
        if not interaction.guild or not interaction.user:
            return
        row = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
            message_id,
        )
        if not row:
            await interaction.response.send_message(
                "-# this giveaway has **ended** or is invalid", ephemeral=True
            )
            return

        exp = _as_naive(row.get("expiration"))
        if exp and _naive_utcnow() > exp:
            await interaction.response.send_message(
                "-# this giveaway has **ended**", ephemeral=True
            )
            return

        member = interaction.guild.get_member(interaction.user.id) or interaction.user
        if getattr(member, "bot", False):
            return

        requirements = {
            "required_roles": row.get("required_roles"),
            "min_level": row.get("min_level"),
            "max_level": row.get("max_level"),
        }
        if isinstance(member, discord.Member):
            if not await self.check_requirements(member, requirements):
                await interaction.response.send_message(
                    "-# you don't meet the **requirements** for this giveaway",
                    ephemeral=True,
                )
                return

        async with self.locks[f"giveaway:{message_id}"]:
            fresh = await self.bot.db.fetchrow(
                "SELECT * FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
                message_id,
            )
            if not fresh:
                await interaction.response.send_message(
                    "-# this giveaway has **ended**", ephemeral=True
                )
                return
            entries = list(fresh.get("entries") or [])
            uid = interaction.user.id
            if uid in entries:
                entries.remove(uid)
                await self.bot.db.execute(
                    "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                    entries,
                    message_id,
                )
                msg = "-# you **left** the giveaway"
            else:
                entries.append(uid)
                await self.bot.db.execute(
                    "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                    entries,
                    message_id,
                )
                msg = "-# you **entered** the giveaway"

            record = dict(fresh)
            record["entries"] = entries
            
            try:
                if interaction.message:
                    await self.rebuild_panel_message(interaction.message, record)
            except Exception:
                pass

            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    async def _handle_view_entries(
        self, interaction: discord.Interaction, message_id: int
    ) -> None:
        row = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1",
            message_id,
        )
        if not row:
            await interaction.response.send_message(
                "-# giveaway **not found**", ephemeral=True
            )
            return

        guild = interaction.guild
        entries = list(row.get("entries") or [])
        members: list[Any] = []
        for uid in entries:
            m = guild.get_member(uid) if guild else None
            if m is None:
                try:
                    m = await self.bot.fetch_user(uid)
                except Exception:
                    m = type("U", (), {"id": uid, "mention": f"<@{uid}>", "display_name": str(uid), "name": str(uid)})()
            members.append(m)

        pages = build_entries_pages(
            prize=str(row.get("prize") or "Giveaway"),
            members=members,
        )
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
            return
        view = EntriesPaginator(pages, owner_id=interaction.user.id)
        await interaction.response.send_message(
            embed=pages[0], view=view, ephemeral=True
        )

    @Cog.listener("on_giveaway_end")
    async def on_giveaway_end_event(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        giveaway: dict,
    ) -> None:
        await self.end_giveaway(giveaway)

    async def _dm_winner(
        self,
        *,
        member: discord.Member | discord.User,
        guild: discord.Guild,
        prize: str,
        jump_url: str,
        script: str | None,
        reroll: bool = False,
    ) -> bool:
        """Return True if DM succeeded."""
        template = script or DEFAULT_DM_SCRIPT
        if reroll and "reroll" not in template.lower():
            
            pass
        view = build_dm_win_view(jump_url)
        try:
            
            if hasattr(self.bot, "send_embed"):
                msg = await self.bot.send_embed(
                    member,
                    template,
                    user=member,
                    member=member,
                    guild=guild,
                    prize=prize,
                )
                if view and msg:
                    with suppress(Exception):
                        await msg.edit(view=view)
                return True
        except (discord.Forbidden, discord.HTTPException):
            return False
        except Exception:
            pass

        
        try:
            emb = discord.Embed(
                title="You won a giveaway!" if not reroll else "You won a reroll!",
                description=(
                    f"**Congratulations** {member.mention}\n\n"
                    f"> You won **{prize}** in **{guild.name}**\n"
                    f"-# thanks for entering"
                ),
                color=color.base,
            )
            if guild.icon:
                emb.set_thumbnail(url=guild.icon.url)
            await member.send(embed=emb, view=view)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False
        except Exception:
            return False

    async def end_giveaway(
        self, giveaway: dict[str, Any], *, force: bool = False, reroll: bool = False
    ) -> list[discord.Member]:
        message_id = int(giveaway["message_id"])
        async with self.locks[f"giveaway-end:{message_id}"]:
            row = await self.bot.db.fetchrow(
                "SELECT * FROM giveaways WHERE message_id = $1",
                message_id,
            )
            if not row:
                return []
            if row.get("win_message_id") and not force and not reroll:
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

            prize = str(giveaway.get("prize") or "Giveaway")
            entries = list(giveaway.get("entries") or [])
            members = [
                m
                for uid in entries
                if (m := guild.get_member(uid)) is not None and not m.bot
            ]
            winners_count = max(1, int(giveaway.get("winner_count") or 1))
            host_mention = self._host_mention(giveaway)
            jump = self._jump_url(guild.id, channel.id, message_id)

            if not members:
                try:
                    await self.rebuild_panel_message(
                        message, giveaway, ended=True, no_entries=True
                    )
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

            
            try:
                await self.rebuild_panel_message(
                    message,
                    giveaway,
                    ended=True,
                    winner_mentions=mentions,
                )
            except Exception:
                pass

            
            announce = build_win_announce_panel(
                prize=prize,
                winner_mentions=mentions,
                host_mention=host_mention,
                reroll=reroll,
                accent=color.base,
            )
            try:
                win_msg = await message.reply(
                    content=mentions,
                    view=announce,
                    allowed_mentions=discord.AllowedMentions(users=True),
                    mention_author=False,
                )
            except Exception:
                win_msg = await channel.send(
                    content=mentions,
                    view=announce,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )

            await self.bot.db.execute(
                "UPDATE giveaways SET win_message_id = $1, entries = $2 WHERE message_id = $3",
                win_msg.id,
                entries,
                message_id,
            )

            
            settings = await self.get_settings(guild.id)
            if settings.get("dm_on_win", True):
                failed: list[discord.Member] = []
                for winner in winners:
                    ok = await self._dm_winner(
                        member=winner,
                        guild=guild,
                        prize=prize,
                        jump_url=jump,
                        script=settings.get("dm_script"),
                        reroll=reroll,
                    )
                    if not ok:
                        failed.append(winner)
                
                if failed and len(failed) == len(winners):
                    
                    pass
                elif failed:
                    for winner in failed:
                        fallback = build_win_announce_panel(
                            prize=prize,
                            winner_mentions=winner.mention,
                            host_mention=host_mention,
                            reroll=reroll,
                            accent=color.base,
                        )
                        with suppress(Exception):
                            await channel.send(
                                content=winner.mention,
                                view=fallback,
                                allowed_mentions=discord.AllowedMentions(users=True),
                            )

            return winners

    async def reroll_giveaway(
        self,
        giveaway: dict[str, Any],
        *,
        winners_count: int = 1,
        channel: discord.abc.Messageable | None = None,
    ) -> list[discord.Member]:
        
        data = dict(giveaway)
        data["winner_count"] = max(1, int(winners_count or 1))
        return await self.end_giveaway(data, force=True, reroll=True)
