from __future__ import annotations

from .invitetracker import InviteTracker
from .events import InviteTrackerEvents


async def setup(bot) -> None:
    await bot.add_cog(InviteTracker(bot))
    await bot.add_cog(InviteTrackerEvents(bot))
