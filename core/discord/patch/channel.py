"""patches TextChannel with helper methods.
adds slow_send and purge_from user shortcuts.
import early to activate"""

import asyncio
import discord


async def _slow_send(self, content: str, delay: float = 1.0, **kw):
    await asyncio.sleep(delay)
    return await self.send(content, **kw)

async def _purge_from(self, user: discord.Member, limit: int = 100) -> int:
    deleted = await self.purge(limit=limit, check=lambda m: m.author.id == user.id)
    return len(deleted)

discord.TextChannel.slow_send = _slow_send
discord.TextChannel.purge_from = _purge_from
