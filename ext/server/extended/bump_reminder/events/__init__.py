from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

import discord

from core.discord.package import Package

from ..proper.constants import (
    BUMP_COOLDOWN,
    DEFAULT_THANKYOU_SCRIPT,
    DISBOARD_ID,
)

if TYPE_CHECKING:
    from core.vain import Vain


_BUMP_DONE_RE = re.compile(r"bump\s+done", re.IGNORECASE)


def _is_disboard_bump(message: discord.Message) -> bool:
    """True when this message is a successful DISBOARD /bump response."""
    author = message.author
    if author is None:
        return False
    
    if int(getattr(author, "id", 0) or 0) != DISBOARD_ID:
        app_id = getattr(message, "application_id", None)
        if app_id is None or int(app_id) != DISBOARD_ID:
            
            wh = getattr(message, "webhook_id", None)
            if wh is None or int(wh) != DISBOARD_ID:
                return False

    
    for emb in message.embeds or []:
        desc = (getattr(emb, "description", None) or "") + "\n" + (
            getattr(emb, "title", None) or ""
        )
        if _BUMP_DONE_RE.search(desc):
            return True
        
        raw = str(getattr(emb, "to_dict", lambda: {})() or "")
        if _BUMP_DONE_RE.search(raw):
            return True

    content = message.content or ""
    if _BUMP_DONE_RE.search(content):
        return True

    
    inter = getattr(message, "interaction", None) or getattr(
        message, "interaction_metadata", None
    )
    if inter is not None:
        name = str(getattr(inter, "name", "") or "").lower()
        if name == "bump" and (message.embeds or _BUMP_DONE_RE.search(content)):
            
            if message.embeds:
                for emb in message.embeds:
                    blob = f"{getattr(emb, 'description', '') or ''} {getattr(emb, 'title', '') or ''}"
                    if _BUMP_DONE_RE.search(blob) or "disboard" in blob.lower():
                        return True
    return False


def _extract_bumper(message: discord.Message) -> discord.abc.User | discord.Member | None:
    """Resolve who ran /bump from interaction metadata."""
    guild = message.guild

    inter = getattr(message, "interaction", None)
    user = getattr(inter, "user", None) if inter is not None else None
    if user is None:
        meta = getattr(message, "interaction_metadata", None)
        user = getattr(meta, "user", None) if meta is not None else None

    if user is None:
        return None

    uid = int(getattr(user, "id", 0) or 0)
    if not uid:
        return None

    if guild is not None:
        member = guild.get_member(uid)
        if member is not None:
            return member
        
        return user
    return user


class BumpReminderEvents:
    bot: Vain

    @Package.listener("on_message")
    async def on_disboard_bump(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        if not _is_disboard_bump(message):
            return

        from ..settings import Settings

        settings = await Settings.fetch(self.bot, message.guild)
        if not settings.enabled or not settings.channel_id:
            return

        now = discord.utils.utcnow()
        next_at = now + datetime.timedelta(seconds=BUMP_COOLDOWN)
        bumper = _extract_bumper(message)
        bumper_id = int(getattr(bumper, "id", 0) or 0) or None

        await settings.upsert(
            last_bump_at=now,
            next_bump_at=next_at,
            last_bumper_id=bumper_id,
            bump_channel_id=message.channel.id,
            
        )

        
        dest = message.channel
        if not isinstance(dest, (discord.TextChannel, discord.Thread)):
            dest = settings.channel
        if dest is None:
            return

        script = (settings.thankyou_message or "").strip() or DEFAULT_THANKYOU_SCRIPT
        await self._send_bump_script(  # type: ignore[attr-defined]
            dest,
            script,
            guild=message.guild,
            bumper=bumper,
            settings=settings,
            next_bump_at=next_at,
            last_bump_at=now,
        )
