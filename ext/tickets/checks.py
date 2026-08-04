from __future__ import annotations

from typing import Optional, cast

from discord import TextChannel
from discord.ext.commands import CommandError, check

from .settings import Settings, Ticket


class TicketContext:
    """Marker for type checkers – the real context gains .ticket after the check."""

    ticket: Ticket
    channel: TextChannel


def in_ticket():
    """Require that the command is run inside an open ticket channel."""

    async def predicate(ctx) -> bool:
        row = await ctx.bot.db.fetchrow(
            "SELECT * FROM tickets.open WHERE channel_id = $1",
            ctx.channel.id,
        )
        if not row:
            raise CommandError("This command can only be used inside a ticket channel.")
        ctx.ticket = cast(Ticket, dict(row))
        return True

    return check(predicate)


def staff():
    """Require that the author is a configured ticket staff member (or has Manage Channels)."""

    async def predicate(ctx) -> bool:
        settings = await Settings.fetch(ctx.bot, ctx.guild)
        if not settings.is_staff(ctx.author):
            raise CommandError("You need to be a ticket staff member to use this.")
        return True

    return check(predicate)
