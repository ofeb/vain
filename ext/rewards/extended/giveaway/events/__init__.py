from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from random import sample
from typing import Any

import discord
from discord.ext import commands, tasks
from discord.ext.commands import Cog

from config import color

from ..improper.requirements import (
    check_member_requirements,
    format_requirements,
    has_any_requirement,
    requirements_from_record,
)
from ..improper.views import (
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


def _now() -> datetime:
    """Local naive now - matches PostgreSQL ``NOW()`` for TIMESTAMP columns."""
    return datetime.now()


def _as_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        
        return dt.astimezone().replace(tzinfo=None)
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
                    dm_on_win BOOLEAN NOT NULL DEFAULT FALSE,
                    dm_script TEXT,
                    embed_script TEXT,
                    button_label TEXT,
                    button_emoji TEXT,
                    show_entries BOOLEAN NOT NULL DEFAULT TRUE,
                    join_type TEXT NOT NULL DEFAULT 'button',
                    join_reaction TEXT
                )
                """
            )

        for stmt in (
            "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS dm_on_win BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS dm_script TEXT",
            "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS embed_script TEXT",
            "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS button_label TEXT",
            "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS button_emoji TEXT",
            "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS show_entries BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS join_type TEXT NOT NULL DEFAULT 'button'",
            "ALTER TABLE giveaway_settings ADD COLUMN IF NOT EXISTS join_reaction TEXT",
        ):
            with suppress(Exception):
                await self.bot.db.execute(stmt)
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
                    requirements JSONB DEFAULT '{}'::jsonb,
                    win_message_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (message_id)
                )
                """
            )
        for stmt in (
            "ALTER TABLE giveaways ADD COLUMN IF NOT EXISTS requirements JSONB DEFAULT '{}'::jsonb",
            "ALTER TABLE giveaways ADD COLUMN IF NOT EXISTS min_level INT",
            "ALTER TABLE giveaways ADD COLUMN IF NOT EXISTS max_level INT",
            "ALTER TABLE giveaways ADD COLUMN IF NOT EXISTS required_roles BIGINT[]",
        ):
            with suppress(Exception):
                await self.bot.db.execute(stmt)

        for ddl in (
            """
            CREATE TABLE IF NOT EXISTS giveaway_message_stats (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                count BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS giveaway_voice_stats (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                minutes BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS giveaway_participation (
                message_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                count BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (message_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS giveaway_voice_sessions (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                joined_at TIMESTAMP NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """,
        ):
            with suppress(Exception):
                await self.bot.db.execute(ddl)

    def _default_settings(self) -> dict[str, Any]:
        return {
            "dm_on_win": False,
            "dm_script": None,
            "embed_script": None,
            "button_label": None,
            "button_emoji": None,
            "show_entries": True,
            "join_type": "button",
            "join_reaction": None,
        }

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        row = None
        with suppress(Exception):
            row = await self.bot.db.fetchrow(
                "SELECT * FROM giveaway_settings WHERE guild_id = $1",
                guild_id,
                cached=False,
            )
        base = self._default_settings()
        if not row:
            return base
        data = dict(row)
        return {
            "dm_on_win": bool(data.get("dm_on_win", False)),
            "dm_script": data.get("dm_script"),
            "embed_script": data.get("embed_script"),
            "button_label": data.get("button_label"),
            "button_emoji": data.get("button_emoji"),
            "show_entries": bool(data.get("show_entries", True)),
            "join_type": str(data.get("join_type") or "button").lower(),
            "join_reaction": data.get("join_reaction"),
        }

    async def update_settings(self, guild_id: int, **fields: Any) -> dict[str, Any]:
        """Upsert any subset of giveaway_settings columns."""
        current = await self.get_settings(guild_id)
        current.update({k: v for k, v in fields.items() if k in current or k in self._default_settings()})
        await self.bot.db.execute(
            """
            INSERT INTO giveaway_settings (
                guild_id, dm_on_win, dm_script, embed_script,
                button_label, button_emoji, show_entries, join_type, join_reaction
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (guild_id) DO UPDATE SET
                dm_on_win = EXCLUDED.dm_on_win,
                dm_script = EXCLUDED.dm_script,
                embed_script = EXCLUDED.embed_script,
                button_label = EXCLUDED.button_label,
                button_emoji = EXCLUDED.button_emoji,
                show_entries = EXCLUDED.show_entries,
                join_type = EXCLUDED.join_type,
                join_reaction = EXCLUDED.join_reaction
            """,
            guild_id,
            bool(current.get("dm_on_win", False)),
            current.get("dm_script"),
            current.get("embed_script"),
            current.get("button_label"),
            current.get("button_emoji"),
            bool(current.get("show_entries", True)),
            str(current.get("join_type") or "button"),
            current.get("join_reaction"),
        )
        return current

    async def set_dm_on_win(self, guild_id: int, enabled: bool) -> None:
        await self.update_settings(guild_id, dm_on_win=enabled)

    async def set_dm_script(self, guild_id: int, script: str | None) -> None:
        await self.update_settings(guild_id, dm_script=script)

    def schedule_end(
        self,
        message_id: int,
        end_time: datetime | None = None,
        *,
        delay_seconds: float | None = None,
    ) -> None:
        """End giveaway after *delay_seconds*, or when *end_time* is reached.

        Prefer *delay_seconds* (from start command) so we never depend on DB clock skew.
        """
        old = self._end_tasks.pop(message_id, None)
        if old and not old.done():
            old.cancel()

        if delay_seconds is None:
            target = _as_naive(end_time) if end_time is not None else None
            if target is not None:
                delay_seconds = (target - _now()).total_seconds()
            else:
                delay_seconds = 0.0
        delay_seconds = max(0.0, float(delay_seconds))

        async def _wait() -> None:
            try:
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                
                row = await self.bot.db.fetchrow(
                    "SELECT * FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
                    message_id,
                )
                if not row:
                    return
                exp = _as_naive(row.get("expiration"))
                if exp is not None and exp > _now() + timedelta(seconds=1):
                    
                    remaining = (exp - _now()).total_seconds()
                    if remaining > 0:
                        self.schedule_end(message_id, delay_seconds=remaining)
                        return
                await self.end_giveaway(dict(row))
            except asyncio.CancelledError:
                return
            except Exception:
                import logging

                logging.getLogger("vain.giveaway").exception(
                    "giveaway end task failed message_id=%s", message_id
                )
            finally:
                self._end_tasks.pop(message_id, None)

        self._end_tasks[message_id] = asyncio.create_task(_wait())

    async def _reschedule_active(self) -> None:
        await self.bot.wait_until_ready()
        with suppress(Exception):
            rows = await self.bot.db.fetch(
                """
                SELECT message_id, expiration FROM giveaways
                WHERE win_message_id IS NULL
                """
            )
            now = _now()
            for row in rows or []:
                exp = _as_naive(row.get("expiration"))
                if exp is None:
                    continue
                delay = (exp - now).total_seconds()
                if delay <= 0:
                    await self.end_giveaway(
                        dict(
                            await self.bot.db.fetchrow(
                                "SELECT * FROM giveaways WHERE message_id = $1",
                                int(row["message_id"]),
                            )
                            or row
                        )
                    )
                else:
                    self.schedule_end(int(row["message_id"]), delay_seconds=delay)

    @tasks.loop(seconds=3.0)
    async def poll_expired_giveaways(self) -> None:
        """Backup ender - compare expiration in Python to avoid TZ mismatch with NOW()."""
        with suppress(Exception):
            rows = await self.bot.db.fetch(
                """
                SELECT * FROM giveaways
                WHERE win_message_id IS NULL
                LIMIT 50
                """
            )
            now = _now()
            for row in rows or []:
                exp = _as_naive(row.get("expiration"))
                if exp is not None and exp <= now:
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

    def _req_lines_for(self, record: dict, guild: discord.Guild | None) -> list[str]:
        reqs = requirements_from_record(record)
        raw = record.get("requirements")
        if isinstance(raw, dict):
            reqs = requirements_from_record({**reqs, **raw})
        if not has_any_requirement(reqs):
            return []
        return format_requirements(reqs, guild=guild)

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
        settings = await self.get_settings(int(record.get("guild_id") or (guild.id if guild else 0)))
        custom_body = None
        embed_script = settings.get("embed_script")
        if embed_script and guild is not None:
            try:
                from core.tools.embed import Script

                prize = str(record.get("prize") or "Giveaway")
                rendered = Script(embed_script).render(
                    guild=guild,
                    prize=prize,
                    winners=int(record.get("winner_count") or 1),
                    host=self._host_mention(record),
                    entries=len(entries),
                    ends_at=str(record.get("expiration") or ""),
                )

                custom_body = rendered
                if "{embed}" in embed_script.lower() or "$v{" in embed_script:

                    custom_body = (
                        rendered.replace("{embed}", "")
                        .replace("$v", "\n")
                        .strip()
                    ) or None
            except Exception:
                custom_body = None

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
            button_label=settings.get("button_label"),
            button_emoji=settings.get("button_emoji"),
            show_entries=bool(settings.get("show_entries", True)),
            join_type=str(settings.get("join_type") or "button"),
            custom_body=custom_body,
            requirement_lines=self._req_lines_for(record, guild),
        )
        await message.edit(content=None, embed=None, view=panel)

    async def check_requirements(
        self,
        member: discord.Member,
        requirements: dict,
        *,
        giveaway: dict | None = None,
        enforce_participation: bool = True,
    ) -> tuple[bool, str | None]:
        ok, reason = await check_member_requirements(
            self.bot,
            member,
            requirements,
            giveaway=giveaway,
            enforce_participation=enforce_participation,
        )
        return ok, reason

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

    @Cog.listener("on_raw_reaction_add")
    async def on_giveaway_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction_entry(payload, adding=True)

    @Cog.listener("on_raw_reaction_remove")
    async def on_giveaway_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction_entry(payload, adding=False)

    async def _handle_reaction_entry(
        self, payload: discord.RawReactionActionEvent, *, adding: bool
    ) -> None:
        if payload.user_id == getattr(self.bot.user, "id", None):
            return
        if not payload.guild_id:
            return
        row = await self.bot.db.fetchrow(
            "SELECT * FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
            payload.message_id,
        )
        if not row:
            return
        settings = await self.get_settings(int(row["guild_id"]))
        if str(settings.get("join_type") or "button").lower() != "reaction":
            return
        expected = str(settings.get("join_reaction") or "🎉")
        emoji = payload.emoji
        got = str(emoji) if emoji.is_custom_emoji() else (emoji.name or "")
        
        if got != expected and str(emoji) != expected and (emoji.name or "") != expected:
            
            if not (
                emoji.is_custom_emoji()
                and expected.strip("<>").split(":")[-1].rstrip(">") in str(emoji)
            ):
                return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        record = dict(row)
        reqs = requirements_from_record(record)
        if adding:
            ok, _reason = await self.check_requirements(
                member,
                reqs,
                giveaway=record,
                enforce_participation=False,
            )
            if not ok:
                return

        message_id = int(row["message_id"])
        async with self.locks[f"giveaway:{message_id}"]:
            fresh = await self.bot.db.fetchrow(
                "SELECT * FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
                message_id,
            )
            if not fresh:
                return
            entries = list(fresh.get("entries") or [])
            uid = int(member.id)
            if adding:
                if uid not in entries:
                    entries.append(uid)
            else:
                entries = [e for e in entries if int(e) != uid]
            await self.bot.db.execute(
                "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                entries,
                message_id,
            )
            channel = guild.get_channel(int(fresh["channel_id"])) or self.bot.get_channel(
                int(fresh["channel_id"])
            )
            if channel is None:
                return
            try:
                message = await channel.fetch_message(message_id)
            except (discord.NotFound, discord.HTTPException):
                return
            try:
                await self.rebuild_panel_message(message, dict(fresh) | {"entries": entries})
            except Exception:
                pass

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
            await interaction.fail("this giveaway has **ended** or is invalid")
            return

        exp = _as_naive(row.get("expiration"))
        if exp and _now() > exp:
            await interaction.fail("this giveaway has **ended**")
            return

        member = interaction.guild.get_member(interaction.user.id) or interaction.user
        if getattr(member, "bot", False):
            return

        record = dict(row)
        reqs = requirements_from_record(record)
        if isinstance(member, discord.Member):
            
            entries_preview = list(record.get("entries") or [])
            already_in = interaction.user.id in entries_preview
            if not already_in:
                ok, reason = await self.check_requirements(
                    member,
                    reqs,
                    giveaway=record,
                    enforce_participation=False,
                )
                if not ok:
                    await interaction.fail(
                        reason
                        or "you don’t meet the **entry rules** for this giveaway"
                    )
                    return

        async with self.locks[f"giveaway:{message_id}"]:
            fresh = await self.bot.db.fetchrow(
                "SELECT * FROM giveaways WHERE message_id = $1 AND win_message_id IS NULL",
                message_id,
            )
            if not fresh:
                await interaction.fail("this giveaway has **ended**")
                return
            entries = list(fresh.get("entries") or [])
            uid = interaction.user.id
            left = uid in entries
            if left:
                entries.remove(uid)
                await self.bot.db.execute(
                    "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                    entries,
                    message_id,
                )
            else:
                entries.append(uid)
                await self.bot.db.execute(
                    "UPDATE giveaways SET entries = $1 WHERE message_id = $2",
                    entries,
                    message_id,
                )

            if left:
                await interaction.warning("you **left** the giveaway")
            else:
                await interaction.success("you’re **in** - good luck")

            record = dict(fresh)
            record["entries"] = entries
            try:
                if interaction.message:
                    await self.rebuild_panel_message(interaction.message, record)
            except Exception:
                pass

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

    async def _send_winner_announce(
        self,
        message: discord.Message,
        channel: discord.abc.Messageable,
        *,
        prize: str,
        mentions: str,
        host_mention: str,
        reroll: bool = False,
    ) -> discord.Message | None:
        """Reply with C2 win panel; hard-fallback to a classic embed."""
        announce = build_win_announce_panel(
            prize=prize,
            winner_mentions=mentions,
            host_mention=host_mention,
            reroll=reroll,
            accent=color.base,
        )
        am = discord.AllowedMentions(users=True)

        
        try:
            return await message.reply(
                content=mentions,
                view=announce,
                allowed_mentions=am,
                mention_author=False,
            )
        except Exception:
            pass

        
        try:
            return await channel.send(
                content=mentions,
                view=announce,
                reference=message,
                allowed_mentions=am,
            )
        except Exception:
            pass

        
        verb = "rerolled and won" if reroll else "won"
        emb = discord.Embed(
            color=color.base,
            description=(
                f"**{mentions}** {verb} **{prize}**\n"
            ),
        )
        try:
            return await message.reply(
                content=mentions,
                embed=emb,
                allowed_mentions=am,
                mention_author=False,
            )
        except Exception:
            pass
        try:
            return await channel.send(
                content=mentions,
                embed=emb,
                allowed_mentions=am,
            )
        except Exception:
            return None

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
        """Return True if DM succeeded.

        Universal script variables (user, guild, vanity, tag, date, prize, …)
        are resolved even though the destination is a DM channel.
        """
        template = script or DEFAULT_DM_SCRIPT
        view = build_dm_win_view(jump_url)
        try:
            from core.tools.embed import Script

            sc = Script(template, user=member)
            vanity = getattr(guild, "vanity_url_code", None)
            tag = None
            pg = getattr(member, "primary_guild", None)
            if pg is not None:
                tag = getattr(pg, "tag", None)
            payload = await sc.data(
                True,
                user=member,
                member=member,
                guild=guild,
                prize=str(prize),
                jump_url=jump_url,
                host=None,
                vanity=vanity,
                tag=tag,
            )
            if view is not None:
                payload["view"] = view
            
            payload.pop("raw_embed", None)
            await member.send(**{
                k: v
                for k, v in payload.items()
                if k in {"content", "embed", "embeds", "view", "file", "files"}
                and v is not None
            })
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
            reqs = requirements_from_record(giveaway)
            members: list[discord.Member] = []
            for uid in entries:
                m = guild.get_member(uid)
                if m is None or m.bot:
                    continue
                ok, _ = await self.check_requirements(m, reqs, giveaway=giveaway)
                if ok:
                    members.append(m)
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

            win_msg = await self._send_winner_announce(
                message,
                channel,
                prize=prize,
                mentions=mentions,
                host_mention=host_mention,
                reroll=reroll,
            )

            await self.bot.db.execute(
                "UPDATE giveaways SET win_message_id = $1, entries = $2 WHERE message_id = $3",
                win_msg.id if win_msg else message.id,
                entries,
                message_id,
            )

            
            settings = await self.get_settings(guild.id)
            
            if settings.get("dm_on_win", False):
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

    
    
    

    @Cog.listener("on_message")
    async def on_giveaway_message_track(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not message.content and not message.attachments:
            return
        guild_id = message.guild.id
        user_id = message.author.id
        with suppress(Exception):
            await self.bot.db.execute(
                """
                INSERT INTO giveaway_message_stats (guild_id, user_id, count)
                VALUES ($1, $2, 1)
                ON CONFLICT (guild_id, user_id) DO UPDATE
                SET count = giveaway_message_stats.count + 1
                """,
                guild_id,
                user_id,
            )
        
        with suppress(Exception):
            rows = await self.bot.db.fetch(
                """
                SELECT message_id FROM giveaways
                WHERE guild_id = $1 AND win_message_id IS NULL
                """,
                guild_id,
            )
            for row in rows or []:
                mid = int(row["message_id"])
                with suppress(Exception):
                    await self.bot.db.execute(
                        """
                        INSERT INTO giveaway_participation (message_id, user_id, count)
                        VALUES ($1, $2, 1)
                        ON CONFLICT (message_id, user_id) DO UPDATE
                        SET count = giveaway_participation.count + 1
                        """,
                        mid,
                        user_id,
                    )

    @Cog.listener("on_voice_state_update")
    async def on_giveaway_voice_track(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or not member.guild:
            return
        guild_id = member.guild.id
        user_id = member.id
        was_in = before.channel is not None
        now_in = after.channel is not None

        
        if was_in and not now_in:
            with suppress(Exception):
                row = await self.bot.db.fetchrow(
                    """
                    SELECT joined_at FROM giveaway_voice_sessions
                    WHERE guild_id = $1 AND user_id = $2
                    """,
                    guild_id,
                    user_id,
                )
                if row and row.get("joined_at"):
                    joined = row["joined_at"]
                    if getattr(joined, "tzinfo", None) is not None:
                        joined = joined.astimezone().replace(tzinfo=None)
                    delta = max(0, int((_now() - joined).total_seconds() // 60))
                    if delta > 0:
                        await self.bot.db.execute(
                            """
                            INSERT INTO giveaway_voice_stats (guild_id, user_id, minutes)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (guild_id, user_id) DO UPDATE
                            SET minutes = giveaway_voice_stats.minutes + EXCLUDED.minutes
                            """,
                            guild_id,
                            user_id,
                            delta,
                        )
                await self.bot.db.execute(
                    """
                    DELETE FROM giveaway_voice_sessions
                    WHERE guild_id = $1 AND user_id = $2
                    """,
                    guild_id,
                    user_id,
                )
            return

        
        if not was_in and now_in:
            with suppress(Exception):
                await self.bot.db.execute(
                    """
                    INSERT INTO giveaway_voice_sessions (guild_id, user_id, joined_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (guild_id, user_id) DO UPDATE
                    SET joined_at = EXCLUDED.joined_at
                    """,
                    guild_id,
                    user_id,
                    _now(),
                )
            return

        
        return
