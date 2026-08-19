from __future__ import annotations

import contextlib
import re
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

import discord

from core.discord.package import Package
from core.discord.views.embed import c2
from .settings import Settings

if TYPE_CHECKING:
    from core.vain import Vain


class HighlightEvents:
    """Highlight keyword events."""

    def __init__(self, bot: Optional["Vain"] = None, *args, **kwargs):
        if bot is not None and not hasattr(self, "bot"):
            self.bot = bot

    async def _get_config(self, guild_id: int) -> dict:
        return await Settings.get_config(self.bot.db, guild_id)

    async def _is_ignored(self, guild: discord.Guild, owner_id: int, message: discord.Message) -> bool:
        rows = await Settings.fetch_ignores(self.bot.db, guild.id, owner_id)
        if not rows:
            return False
        author = message.author
        channel_id = message.channel.id
        role_ids = {r.id for r in getattr(author, "roles", [])} if isinstance(author, discord.Member) else set()
        for row in rows:
            if row["target_type"] == "user" and row["target_id"] == author.id:
                return True
            if row["target_type"] == "channel" and row["target_id"] == channel_id:
                return True
            if row["target_type"] == "role" and row["target_id"] in role_ids:
                return True
        return False

    def _build_log_embed(
        self,
        *,
        keyword: str,
        message: discord.Message,
        owner: discord.abc.User | None = None,
    ):
        author = message.author
        content = (message.content or "").strip() or "*no text*"
        if len(content) > 900:
            content = content[:897] + "..."
        
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        shown = pattern.sub(lambda m: f"**{m.group(0)}**", content)
        lines = [
            f"**Keyword** `{keyword}` was mentioned",
            f"> -# **author:** {author.mention} (`{author.id}`)",
            f"> -# **channel:** {message.channel.mention}",
            f"> -# **message:** [jump]({message.jump_url})",
            "",
            shown,
        ]
        return c2(
            message="\n".join(lines),
            footer=f"{author}",
            timestamp=True,
        )

    async def _apply_punishment(self, message: discord.Message, cfg: dict) -> None:
        action = (cfg.get("punishment") or "none").lower()
        if action == "none":
            return
        member = message.author
        if not isinstance(member, discord.Member):
            return
        if member.bot or member.guild_permissions.administrator:
            return
        guild = message.guild
        me = guild.me
        if me is None:
            return
        reason = "Highlight keyword punishment"

        try:
            if action == "warn":
                with contextlib.suppress(Exception):
                    await message.channel.send(
                        f"{member.mention} was **warned** for using a highlighted keyword.",
                        delete_after=8,
                    )
            elif action == "timeout":
                secs = int(cfg.get("timeout_seconds") or 60)
                until = datetime.now(timezone.utc) + timedelta(seconds=secs)
                await member.timeout(until, reason=reason)
            elif action == "ban":
                await member.ban(reason=reason, delete_message_days=0)
            elif action == "hardban":
                await member.ban(reason=reason, delete_message_days=7)
            elif action == "softban":
                uid = member.id
                await member.ban(reason=reason, delete_message_days=1)
                await guild.unban(discord.Object(id=uid), reason="Highlight softban")
        except Exception:
            pass

        delete_after = cfg.get("delete_after_seconds")
        if delete_after is not None:
            try:
                import asyncio
                delay = max(0, int(delete_after))
                if delay > 0:
                    await asyncio.sleep(delay)
                await message.delete()
            except Exception:
                pass

    @Package.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return
        
        rows = await Settings.fetch_all_highlights(self.bot.db, message.guild.id)
        if not rows:
            return

        content_lower = message.content.lower()
        
        hits: dict[str, set[int]] = {}
        for row in rows:
            kw = row["keyword"]
            if kw and kw in content_lower:
                hits.setdefault(kw, set()).add(row["user_id"])
        if not hits:
            return

        cfg = await self._get_config(message.guild.id)

        
        notified: set[int] = set()
        for keyword, user_ids in hits.items():
            for uid in user_ids:
                if uid == message.author.id or uid in notified:
                    continue
                if await self._is_ignored(message.guild, uid, message):
                    continue
                notified.add(uid)
                embed = self._build_log_embed(keyword=keyword, message=message)
                if cfg.get("log_type") == "channel" and cfg.get("log_channel_id"):
                    ch = message.guild.get_channel(cfg["log_channel_id"])
                    if ch is not None:
                        with contextlib.suppress(Exception):
                            await ch.send(content=f"<@{uid}>", embed=embed)
                        continue
                
                user = self.bot.get_user(uid)
                if user is None:
                    with contextlib.suppress(Exception):
                        user = await self.bot.fetch_user(uid)
                if user is not None:
                    with contextlib.suppress(Exception):
                        await user.send(embed=embed)

        
        await self._apply_punishment(message, cfg)


__all__: list[str] = ["HighlightEvents"]
