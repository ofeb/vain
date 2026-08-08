from __future__ import annotations

import io
from contextlib import suppress
from datetime import datetime, timezone
from secrets import token_urlsafe
from typing import Any, Optional

from discord import Embed, File, Guild, HTTPException, TextChannel, Thread


class Transcript:
    """Lightweight transcript generator – produces a downloadable .txt file."""

    def __init__(
        self,
        *,
        identifier: str,
        guild_id: int,
        channel_id: int,
        user_id: int,
        content: str,
    ) -> None:
        self.id = identifier
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.user_id = user_id
        self.content = content

    @classmethod
    async def build(
        cls,
        bot: Any,
        guild: Guild,
        channel: TextChannel,
        ticket: dict,
        *,
        persist: bool = True,
    ) -> "Transcript":
        """Collect channel history into a Transcript (optionally store a row)."""
        lines: list[str] = [
            f"Ticket Transcript - {channel.name}",
            f"Guild: {guild.name} ({guild.id})",
            f"Channel: #{channel.name} ({channel.id})",
            f"Opened by: {ticket.get('user_id')}",
            f"Claimed by: {ticket.get('claimed_by') or 'unclaimed'}",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "=" * 60,
            "",
        ]

        async for message in channel.history(limit=500, oldest_first=True):
            ts = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{message.author} ({message.author.id})"
            content = message.clean_content or "[no text content]"
            lines.append(f"[{ts}] {author}")
            lines.append(content)
            if message.attachments:
                for att in message.attachments:
                    lines.append(f"  ↳ attachment: {att.url}")
            if message.embeds:
                lines.append(f"  ↳ {len(message.embeds)} embed(s)")
            lines.append("")

        body = "\n".join(lines)
        identifier = token_urlsafe(10)

        if persist:
            await bot.db.execute(
                """
                INSERT INTO tickets.transcript (id, guild_id, channel_id, user_id, messages)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                identifier,
                guild.id,
                channel.id,
                ticket["user_id"],
                "[]",
            )

        return cls(
            identifier=identifier,
            guild_id=guild.id,
            channel_id=channel.id,
            user_id=ticket["user_id"],
            content=body,
        )

    def as_file(self, channel_name: str = "ticket") -> File:
        return File(
            io.BytesIO(self.content.encode("utf-8")),
            filename=f"transcript-{channel_name}-{self.id}.txt",
        )

    @staticmethod
    async def deliver(
        guild: Guild,
        ticket: dict,
        transcript: "Transcript",
        destinations: list,
        *,
        channel_name: str,
        description: str = "Ticket closed. Full log attached.",
    ) -> None:
        """Send an already-built transcript to destinations."""
        embed = Embed(
            title=f"Transcript - {channel_name}",
            description=description,
            color=0xE1D2DE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"ID: {transcript.id}")
        body = transcript.content
        for dest in destinations:
            file = File(
                io.BytesIO(body.encode("utf-8")),
                filename=f"transcript-{channel_name}-{transcript.id}.txt",
            )
            if dest == "dm":
                user = guild.get_member(ticket["user_id"])
                if user:
                    with suppress(HTTPException):
                        await user.send(embed=embed, file=file)
            elif isinstance(dest, (TextChannel, Thread)):
                with suppress(HTTPException):
                    await dest.send(embed=embed, file=file)

    @classmethod
    async def create(
        cls,
        bot: Any,
        guild: Guild,
        channel: TextChannel,
        ticket: dict,
        destinations: list,
        *,
        description: str = "Ticket closed. Full log attached.",
    ) -> Optional["Transcript"]:
        if not destinations:
            return None

        transcript = await cls.build(bot, guild, channel, ticket, persist=True)
        await cls.deliver(
            guild,
            ticket,
            transcript,
            destinations,
            channel_name=channel.name,
            description=description,
        )
        return transcript
