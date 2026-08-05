from __future__ import annotations

from contextlib import suppress

import discord

from core.discord.views.confirm import ConfirmView


async def confirm(_, ctx, prompt, member=None) -> bool:
    """attach a confirmation view to an existing prompt message."""

    view = ConfirmView(ctx, member=member)
    await prompt.edit(view=view)
    await view.wait()
    with suppress(discord.HTTPException):
        await prompt.edit(view=None)
    return bool(view.value)
