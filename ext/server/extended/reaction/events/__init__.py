from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.discord.package import Package

if TYPE_CHECKING:
    from core.discord.ctx import Context

log = logging.getLogger("vain.reaction.events")


def _matches_trigger(content: str, trigger: str, *, strict: bool) -> bool:
    """Local import-free matcher (mirrors autoresponder word boundaries)."""
    import re

    content = (content or "").lower().strip()
    trigger = (trigger or "").lower().strip()
    if not trigger:
        return False
    if strict:
        return content == trigger
    pattern = re.compile(
        r"(?<!\w)" + re.escape(trigger) + r"(?!\w)",
        re.IGNORECASE,
    )
    return pattern.search(content) is not None


class ReactionEvents(Package):
    """Auto-reaction event handlers - mixed into Reaction cog."""

    @Package.listener("on_valid_message")
    async def on_auto_reaction(self, ctx: Context) -> None:
        """Handle auto-reactions on valid guild messages."""
        if ctx.guild is None or ctx.author.bot:
            return
        content = ctx.message.content or ""
        if not content and not ctx.message.attachments:
            
            pass

        try:
            records = await self.bot.db.fetch(
                """
                SELECT trigger, response, strict FROM auto_reactions
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
        except Exception:
            log.exception("auto_reactions fetch failed guild=%s", ctx.guild.id)
            return

        if not records:
            return

        
        records = sorted(
            records,
            key=lambda r: (-len(str(r["trigger"] or "")), str(r["trigger"] or "").lower()),
        )

        channel_id = str(ctx.channel.id)
        applied = 0
        for record in records:
            trigger = str(record["trigger"] or "")
            if not trigger:
                continue

            
            if trigger == channel_id:
                pass  
            elif not content:
                continue
            elif not _matches_trigger(
                content,
                trigger,
                strict=bool(record.get("strict")),
            ):
                continue

            for reaction in record["response"] or []:
                try:
                    await ctx.message.add_reaction(str(reaction))
                    applied += 1
                except Exception:
                    continue

            
            if trigger != channel_id and applied:
                
                break
