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


class Settings:
    """Guild-level ticket configuration backed by tickets.settings."""

    def __init__(self, bot, guild: Guild, record: dict[str, Any]):
        self.bot = bot
        self.guild = guild
        self.record = record or {}

    @classmethod
    async def fetch(cls, bot, guild: Guild) -> "Settings":
        row = await bot.db.fetchrow(
            "SELECT * FROM tickets.settings WHERE guild_id = $1",
            guild.id,
        )
        if not row:
            await bot.db.execute(
                "INSERT INTO tickets.settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild.id,
            )
            row = await bot.db.fetchrow(
                "SELECT * FROM tickets.settings WHERE guild_id = $1",
                guild.id,
            )
        return cls(bot, guild, dict(row) if row else {"guild_id": guild.id})

    async def upsert(self, **kwargs) -> None:
        if not kwargs:
            return
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        set_clause = ", ".join(f"{c} = ${i+2}" for i, c in enumerate(cols))
        await self.bot.db.execute(
            f"""
            INSERT INTO tickets.settings (guild_id, {', '.join(cols)})
            VALUES ($1, {', '.join(f'${i+2}' for i in range(len(cols)))})
            ON CONFLICT (guild_id) DO UPDATE SET {set_clause}
            """,
            self.guild.id,
            *vals,
        )
        self.record.update(kwargs)

    @property
    def staff_roles(self) -> list[Role]:
        ids = self.record.get("staff_role_ids") or []
        return [r for rid in ids if (r := self.guild.get_role(rid))]

    @property
    def blacklisted(self) -> list:
        ids = self.record.get("blacklisted_ids") or []
        out = []
        for i in ids:
            if m := self.guild.get_member(i):
                out.append(m)
            elif r := self.guild.get_role(i):
                out.append(r)
        return out

    def is_blacklisted(self, member: Member) -> bool:
        ids = set(self.record.get("blacklisted_ids") or [])
        if member.id in ids:
            return True
        return any(r.id in ids for r in member.roles)

    @property
    def transcript_destinations(self) -> list:
        dests = self.record.get("transcript_destinations") or []
        out = []
        for d in dests:
            if d == "dm":
                out.append("dm")
            else:
                try:
                    ch = self.guild.get_channel(int(d))
                    if isinstance(ch, TextChannel):
                        out.append(ch)
                except (TypeError, ValueError):
                    pass
        return out

    async def fetch_message(self) -> Optional[Message]:
        ch_id = self.record.get("channel_id")
        msg_id = self.record.get("message_id")
        if not ch_id or not msg_id:
            return None
        channel = self.guild.get_channel(ch_id)
        if not isinstance(channel, TextChannel):
            return None
        with suppress(HTTPException):
            return await channel.fetch_message(msg_id)
        return None

    async def fetch_button(self, identifier: str) -> Optional[TicketButton]:
        row = await self.bot.db.fetchrow(
            "SELECT * FROM tickets.button WHERE guild_id = $1 AND id = $2",
            self.guild.id,
            identifier,
        )
        return cast(TicketButton, dict(row)) if row else None

    async def fetch_dropdown_option(
        self, dropdown_id: str, option_id: str
    ) -> Optional[TicketDropdownOption]:
        row = await self.bot.db.fetchrow(
            "SELECT options FROM tickets.dropdown WHERE guild_id = $1 AND id = $2",
            self.guild.id,
            dropdown_id,
        )
        if not row:
            return None
        for o in row["options"] or []:
            if o.get("id") == option_id:
                return cast(TicketDropdownOption, o)
        return None
