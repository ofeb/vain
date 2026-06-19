from __future__ import annotations

import contextlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from discord.ext.commands import Cog
from asyncio import Lock


class AntiraidEvents(Cog):
    """supplementary antiraid event handlers."""

    def __init__(self: "AntiraidEvents", bot: discord.Client):
        self.bot = bot
        self._locks = defaultdict(Lock)

    async def _evaluate_member(
        self, member: discord.Member, guild: discord.Guild, config: object
    ) -> tuple[bool, str | None, str | None]:
        bypass = set(getattr(config, "whitelist", []) or [])
        active = getattr(config, "raid_active", False)
        puntil = getattr(config, "punish_until", None)

        if active and member.id not in bypass:
            if puntil and datetime.now(timezone.utc) > puntil:
                await self.bot.db.execute(
                    "UPDATE antiraid_config SET raid_active = FALSE, punish_until = NULL WHERE guild_id = $1",
                    guild.id,
                )
            else:
                m_action = getattr(config, "massjoin_action", None) or "ban"
                return True, m_action, "raid in progress"
        if member.id in bypass:
            return False, None, None
        naccts = getattr(config, "newaccounts_enabled", False)
        if naccts and member.created_at < datetime.now(timezone.utc) - timedelta(
            days=getattr(config, "newaccounts_threshold", 7)
        ):
            na_action = getattr(config, "newaccounts_action", None) or "ban"
            return True, na_action, "new account"
        avi = getattr(config, "avatar_enabled", False)
        if avi and not member.avatar:
            av_action = getattr(config, "avatar_action", None) or "kick"
            return True, av_action, "no avatar"

        return False, None, None

    @Cog.listener("on_member_join")
    async def _on_join_eval(self, member: discord.Member) -> None:
        guild = member.guild

        async def _check() -> bool:
            row = await self.bot.db.fetchrow(
                "SELECT * FROM antiraid_config WHERE guild_id = $1", guild.id
            )
            if not row:
                return False
            result = False
            async with self._locks[f"antiraid:{guild.id}"]:
                doit, action, reason = await self._evaluate_member(member, guild, row)
                if doit and action:
                    with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                        if action == "ban":
                            await member.ban(reason=f"antiraid-events: {reason}")
                        else:
                            await member.kick(reason=f"antiraid-events: {reason}")
                    result = True
            return result

        handled = await _check()
        if not handled and not member.pending:
            self.bot.dispatch("member_agree", member)

    @Cog.listener("on_member_update")
    async def _on_accept(self, before: discord.Member, after: discord.Member) -> None:
        if before.pending and not after.pending:
            self.bot.dispatch("member_agree", after)


async def setup(bot: discord.Client) -> None:
    await bot.add_cog(AntiraidEvents(bot))
