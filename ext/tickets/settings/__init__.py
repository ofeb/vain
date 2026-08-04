from __future__ import annotations

from contextlib import suppress
from typing import Any, Literal, Optional, TypedDict, cast

from discord import Guild, HTTPException, Member, Message, Role, TextChannel, Thread


class Ticket(TypedDict):
    id: str
    guild_id: int
    channel_id: int
    user_id: int


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
    }


class Settings:
    """Per-guild ticket configuration with light in-memory cache."""

    __slots__ = ("bot", "guild", "record")

    def __init__(self, bot: Any, guild: Guild, record: Record) -> None:
        self.bot = bot
        self.guild = guild
        self.record = dict(record)

    def __bool__(self) -> bool:
        return bool(self.record.get("channel_id"))

    @property
    def channel(self) -> Optional[TextChannel]:
        cid = self.record.get("channel_id") or 0
        if not cid:
            return None
        ch = self.guild.get_channel(cid)
        return ch if isinstance(ch, TextChannel) else None

    @property
    def staff_roles(self) -> list[Role]:
        return [
            role
            for rid in (self.record.get("staff_role_ids") or [])
            if (role := self.guild.get_role(rid))
        ]

    @property
    def blacklisted(self) -> list[Role | Member]:
        out: list[Role | Member] = []
        for tid in self.record.get("blacklisted_ids") or []:
            if role := self.guild.get_role(tid):
                out.append(role)
            elif member := self.guild.get_member(tid):
                out.append(member)
        return out

    @property
    def transcript_destinations(self) -> list[TextChannel | Thread | Literal["dm"]]:
        dests: list[TextChannel | Thread | Literal["dm"]] = []
        for d in self.record.get("transcript_destinations") or []:
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
        mid = self.record.get("message_id") or 0
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
        return dict(row) if row else None

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
                return opt
        return None

    @classmethod
    async def fetch(cls, bot: Any, guild: Guild) -> Settings:
        row = await bot.db.fetchrow(
            "SELECT * FROM tickets.settings WHERE guild_id = $1", guild.id
        )
        if row:
            # normalize arrays that may come as None
            data = dict(row)
            data["staff_role_ids"] = list(data.get("staff_role_ids") or [])
            data["blacklisted_ids"] = list(data.get("blacklisted_ids") or [])
            data["transcript_destinations"] = list(
                data.get("transcript_destinations") or []
            )
            return cls(bot, guild, data)
        return cls(bot, guild, _default_record(guild.id))

    async def upsert(self, **kwargs) -> Settings:
        # merge kwargs into current record
        for k, v in kwargs.items():
            self.record[k] = v

        await self.bot.db.execute(
            """
            INSERT INTO tickets.settings (
                guild_id, channel_id, message_id, max_tickets,
                inactivity_timeout, staff_role_ids, blacklisted_ids,
                transcript_destinations
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (guild_id) DO UPDATE SET
                channel_id              = EXCLUDED.channel_id,
                message_id              = EXCLUDED.message_id,
                max_tickets             = EXCLUDED.max_tickets,
                inactivity_timeout      = EXCLUDED.inactivity_timeout,
                staff_role_ids          = EXCLUDED.staff_role_ids,
                blacklisted_ids         = EXCLUDED.blacklisted_ids,
                transcript_destinations = EXCLUDED.transcript_destinations
            """,
            self.guild.id,
            self.record.get("channel_id") or 0,
            self.record.get("message_id") or 0,
            self.record.get("max_tickets"),
            self.record.get("inactivity_timeout"),
            self.record.get("staff_role_ids") or [],
            self.record.get("blacklisted_ids") or [],
            self.record.get("transcript_destinations") or [],
        )
        return self
