from __future__ import annotations

from contextlib import suppress
from typing import Any, Literal, Optional, TypedDict, cast

from discord import Guild, HTTPException, Member, Message, Role, TextChannel, Thread


class Ticket(TypedDict, total=False):
    id: str
    guild_id: int
    channel_id: int
    user_id: int
    claimed_by: Optional[int]
    opened_at: Any


class TicketButton(TypedDict, total=False):
    id: str
    guild_id: int
    category_id: Optional[int]
    template: Optional[str]
    topic: Optional[str]
    style: str
    emoji: Optional[str]
    label: str


class TicketDropdownOption(TypedDict, total=False):
    id: str
    label: str
    emoji: Optional[str]
    description: Optional[str]
    category_id: Optional[int]
    template: Optional[str]
    topic: Optional[str]


class TicketDropdown(TypedDict):
    id: str
    guild_id: int
    placeholder: str
    options: list[TicketDropdownOption]


class Record(TypedDict, total=False):
    guild_id: int
    channel_id: int
    message_id: int
    max_tickets: Optional[int]
    inactivity_timeout: Optional[int]
    staff_role_ids: list[int]
    blacklisted_ids: list[int]
    transcript_destinations: list[str]
    open_embed: Optional[str]


def _default_record(guild_id: int = 0) -> Record:
    return {
        "guild_id": guild_id,
        "channel_id": 0,
        "message_id": 0,
        "max_tickets": None,
        "inactivity_timeout": None,
        "staff_role_ids": [],
        "blacklisted_ids": [],
        "transcript_destinations": [],
        "open_embed": None,
    }


class Settings:
    """Per-guild ticket configuration."""

    __slots__ = ("bot", "guild", "record")

    def __init__(self, bot: Any, guild: Guild, record: Record) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return bool(self.record.get("channel_id"))

    @property
    def channel(self) -> Optional[TextChannel]:
        cid = int(self.record.get("channel_id") or 0)
        if not cid:
            return None
        ch = self.guild.get_channel(cid)
        return ch if isinstance(ch, TextChannel) else None

    @property
    def staff_roles(self) -> list[Role]:
        roles: list[Role] = []
        for rid in list(self.record.get("staff_role_ids") or []):
            role = self.guild.get_role(int(rid))
            if role is not None:
                roles.append(role)
        return roles

    @property
    def blacklisted(self) -> list[Role | Member]:
        out: list[Role | Member] = []
        for tid in list(self.record.get("blacklisted_ids") or []):
            if role := self.guild.get_role(int(tid)):
                out.append(role)
            elif member := self.guild.get_member(int(tid)):
                out.append(member)
        return out

    @property
    def transcript_destinations(self) -> list[TextChannel | Thread | Literal["dm"]]:
        dests: list[TextChannel | Thread | Literal["dm"]] = []
        for d in list(self.record.get("transcript_destinations") or []):
            if d == "dm":
                dests.append("dm")
                continue
            try:
                ch = self.guild.get_channel_or_thread(int(d))
                if isinstance(ch, (TextChannel, Thread)):
                    dests.append(ch)
            except (ValueError, TypeError):
                continue
        return dests

    @property
    def open_embed(self) -> Optional[str]:
        value = self.record.get("open_embed")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def is_blacklisted(self, member: Member) -> bool:
        if member in self.blacklisted:
            return True
        return any(r in member.roles for r in self.blacklisted if isinstance(r, Role))

    def is_staff(self, member: Member) -> bool:
        if member.guild_permissions.manage_channels:
            return True
        return any(r in member.roles for r in self.staff_roles)

    async def fetch_message(self) -> Optional[Message]:
        ch = self.channel
        mid = int(self.record.get("message_id") or 0)
        if not ch or not mid:
            return None
        with suppress(HTTPException, AttributeError):
            return await ch.fetch_message(mid)
        return None

    async def fetch_button(self, identifier: str) -> Optional[TicketButton]:
        row = await self.bot.db.fetchrow(
            "SELECT * FROM tickets.button WHERE guild_id = $1 AND id = $2",
            self.guild.id,
            identifier,
        )
        return cast(Optional[TicketButton], dict(row) if row else None)

    async def fetch_dropdown_option(
        self, identifier: str, option_id: str
    ) -> Optional[TicketDropdownOption]:
        row = await self.bot.db.fetchrow(
            "SELECT options FROM tickets.dropdown WHERE guild_id = $1 AND id = $2",
            self.guild.id,
            identifier,
        )
        if not row:
            return None
        for opt in row["options"] or []:
            if opt.get("id") == option_id:
                return cast(TicketDropdownOption, opt)
        return None

    @classmethod
    async def fetch(cls, bot: Any, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM tickets.settings WHERE guild_id = $1", guild.id
        )
        if row:
            data = dict(row)
            data["staff_role_ids"] = list(data.get("staff_role_ids") or [])
            data["blacklisted_ids"] = list(data.get("blacklisted_ids") or [])
            data["transcript_destinations"] = list(
                data.get("transcript_destinations") or []
            )
            data["open_embed"] = data.get("open_embed")
            return cls(bot, guild, cast(Record, data))
        return cls(bot, guild, _default_record(guild.id))

    async def upsert(self, **kwargs) -> Settings:
        for k, v in kwargs.items():
            self.record[k] = v

        await self.bot.db.execute(
            """
            INSERT INTO tickets.settings (
                guild_id, channel_id, message_id, max_tickets,
                inactivity_timeout, staff_role_ids, blacklisted_ids,
                transcript_destinations, open_embed
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (guild_id) DO UPDATE SET
                channel_id              = EXCLUDED.channel_id,
                message_id              = EXCLUDED.message_id,
                max_tickets             = EXCLUDED.max_tickets,
                inactivity_timeout      = EXCLUDED.inactivity_timeout,
                staff_role_ids          = EXCLUDED.staff_role_ids,
                blacklisted_ids         = EXCLUDED.blacklisted_ids,
                transcript_destinations = EXCLUDED.transcript_destinations,
                open_embed              = EXCLUDED.open_embed
            """,
            self.guild.id,
            self.record.get("channel_id") or 0,
            self.record.get("message_id") or 0,
            self.record.get("max_tickets"),
            self.record.get("inactivity_timeout"),
            self.record.get("staff_role_ids") or [],
            self.record.get("blacklisted_ids") or [],
            self.record.get("transcript_destinations") or [],
            self.record.get("open_embed"),
        )
        return self

    

    @staticmethod
    async def fetch_open_ticket_by_channel(bot: Any, channel_id: int) -> Optional[dict]:
        row = await bot.db.fetchrow(
            "SELECT * FROM tickets.open WHERE channel_id = $1",
            channel_id,
        )
        return dict(row) if row else None

    async def fetch_user_open_ticket(
        self, identifier: str, user_id: int
    ) -> Optional[dict]:
        row = await self.bot.db.fetchrow(
            """
            SELECT channel_id FROM tickets.open
            WHERE id = $1 AND guild_id = $2 AND user_id = $3
            """,
            identifier,
            self.guild.id,
            user_id,
        )
        return dict(row) if row else None

    async def count_open_tickets(self) -> int:
        count = await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM tickets.open WHERE guild_id = $1",
            self.guild.id,
        )
        return int(count) if count is not None else 0

    async def insert_open_ticket(
        self, identifier: str, channel_id: int, user_id: int
    ) -> None:
        await self.bot.db.execute(
            """
            INSERT INTO tickets.open (id, guild_id, channel_id, user_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id, guild_id, user_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id, claimed_by = NULL
            """,
            identifier,
            self.guild.id,
            channel_id,
            user_id,
        )

    async def delete_open_ticket(self, channel_id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM tickets.open WHERE channel_id = $1",
            channel_id,
        )

    async def delete_open_tickets(self, channel_ids: list[int]) -> None:
        await self.bot.db.execute(
            "DELETE FROM tickets.open WHERE channel_id = ANY($1::BIGINT[])",
            channel_ids,
        )

    async def claim_ticket(self, user_id: int, channel_id: int) -> None:
        await self.bot.db.execute(
            "UPDATE tickets.open SET claimed_by = $1 WHERE channel_id = $2",
            user_id,
            channel_id,
        )

    

    async def fetch_buttons(self) -> list[dict]:
        rows = await self.bot.db.fetch(
            "SELECT * FROM tickets.button WHERE guild_id = $1 ORDER BY id",
            self.guild.id,
        )
        return [dict(r) for r in rows]

    async def fetch_button_list(self) -> list[dict]:
        rows = await self.bot.db.fetch(
            "SELECT id, label, style, emoji FROM tickets.button WHERE guild_id = $1",
            self.guild.id,
        )
        return [dict(r) for r in rows]

    async def delete_button(self, identifier: str) -> str:
        result = await self.bot.db.execute(
            "DELETE FROM tickets.button WHERE guild_id = $1 AND id = $2",
            self.guild.id,
            identifier,
        )
        return result

    async def upsert_button(
        self,
        identifier: str,
        *,
        category_id: Optional[int] = None,
        topic: Optional[str] = None,
        style: str = "green",
        emoji: Optional[str] = None,
        label: str = "Open Ticket",
        update_all: bool = True,
    ) -> None:
        if update_all:
            await self.bot.db.execute(
                """
                INSERT INTO tickets.button (id, guild_id, category_id, topic, style, emoji, label)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (guild_id, id) DO UPDATE SET
                    category_id = EXCLUDED.category_id,
                    topic       = EXCLUDED.topic,
                    style       = EXCLUDED.style,
                    emoji       = EXCLUDED.emoji,
                    label       = EXCLUDED.label
                """,
                identifier,
                self.guild.id,
                category_id,
                topic,
                style,
                emoji,
                label[:80],
            )
        else:
            await self.bot.db.execute(
                """
                INSERT INTO tickets.button (id, guild_id, category_id, topic, style, emoji, label)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (guild_id, id) DO UPDATE SET
                    style = EXCLUDED.style,
                    emoji = EXCLUDED.emoji,
                    label = EXCLUDED.label
                """,
                identifier,
                self.guild.id,
                category_id,
                topic,
                style,
                emoji,
                label[:80],
            )

    async def update_button_emoji(
        self, button_id: str, emoji: Optional[str]
    ) -> str:
        result = await self.bot.db.execute(
            """
            UPDATE tickets.button
            SET emoji = $3
            WHERE guild_id = $1 AND id = $2
            """,
            self.guild.id,
            button_id,
            emoji,
        )
        return result

    

    async def fetch_dropdown_options(
        self, identifier: str
    ) -> Optional[list[dict]]:
        row = await self.bot.db.fetchrow(
            "SELECT options FROM tickets.dropdown WHERE guild_id = $1 AND id = $2",
            self.guild.id,
            identifier,
        )
        if not row:
            return None
        return list(row["options"] or [])

    async def upsert_dropdown(
        self, identifier: str, placeholder: str
    ) -> None:
        await self.bot.db.execute(
            """
            INSERT INTO tickets.dropdown (id, guild_id, placeholder, options)
            VALUES ($1, $2, $3, '[]'::jsonb)
            ON CONFLICT (guild_id, id) DO UPDATE SET placeholder = EXCLUDED.placeholder
            """,
            identifier,
            self.guild.id,
            placeholder[:100],
        )

    async def update_dropdown_options(
        self, dropdown_id: str, options_json: str
    ) -> None:
        await self.bot.db.execute(
            "UPDATE tickets.dropdown SET options = $1::jsonb WHERE guild_id = $2 AND id = $3",
            options_json,
            self.guild.id,
            dropdown_id,
        )

    async def delete_dropdown(self, identifier: str) -> str:
        result = await self.bot.db.execute(
            "DELETE FROM tickets.dropdown WHERE guild_id = $1 AND id = $2",
            self.guild.id,
            identifier,
        )
        return result

    async def fetch_all_dropdowns(self) -> list[dict]:
        rows = await self.bot.db.fetch(
            "SELECT * FROM tickets.dropdown WHERE guild_id = $1",
            self.guild.id,
        )
        return [dict(r) for r in rows]

    

    async def fetch_tickets_with_inactivity_timeout(self) -> list[dict]:
        rows = await self.bot.db.fetch(
            """
            SELECT o.channel_id, s.inactivity_timeout
            FROM tickets.open o
            JOIN tickets.settings s ON o.guild_id = s.guild_id
            WHERE s.inactivity_timeout IS NOT NULL
            """
        )
        return [dict(r) for r in rows]
