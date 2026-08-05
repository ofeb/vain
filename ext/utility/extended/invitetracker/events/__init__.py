from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks

from core.discord.package import Package
from core.tools.embed import Script

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("vain.invitetracker.events")


def _invite_word(count: int) -> str:
    return "invite" if count == 1 else "invites"


def _fix_invite_plural(text: str, count: int) -> str:
    """Replace hardcoded 'invites' with correct plural form in rendered text."""
    import re
    word = _invite_word(count)
    return re.sub(r'\binvites\b', word, text)


class InviteTrackerEvents(Package):
    """invite tracking event listeners"""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._invite_cache: dict[int, dict[str, int]] = {}

    async def cog_load(self) -> None:
        asyncio.create_task(self._populate_cache())
        if not self._cache_refresh.is_running():
            with contextlib.suppress(RuntimeError):
                self._cache_refresh.start()

    def cog_unload(self) -> None:
        if self._cache_refresh.is_running():
            self._cache_refresh.cancel()

    @tasks.loop(minutes=5)
    async def _cache_refresh(self) -> None:
        """Periodically refresh invite cache to prevent stale data."""
        if not self.bot.is_ready():
            return
        for guild in self.bot.guilds:
            try:
                invites = await self._snapshot_invites(guild)
                if invites:
                    self._invite_cache[guild.id] = invites
            except Exception:
                pass

    @_cache_refresh.before_loop
    async def _before_cache_refresh(self) -> None:
        await self.bot.wait_until_ready()

    async def _populate_cache(self) -> None:
        """Snapshot invite uses for all guilds on startup."""
        try:
            await self.bot.wait_until_ready()
            for guild in self.bot.guilds:
                try:
                    invites = await self._snapshot_invites(guild)
                    if invites:
                        self._invite_cache[guild.id] = invites
                        log.debug("Cached %d invites for %s", len(invites), guild.name)
                except Exception as e:
                    log.error("Failed to cache invites for %s: %s", guild.name, e)
        except Exception as e:
            log.error("Invite cache population failed: %s", e)

    async def _snapshot_invites(self, guild: discord.Guild) -> dict[str, int]:
        """Fetch current invite uses as {code: uses}"""
        try:
            invites = await guild.invites()
            return {invite.code: invite.uses for invite in invites}
        except discord.Forbidden:
            log.warning("Missing permissions to fetch invites in %s (%s)", guild.name, guild.id)
            return {}
        except discord.HTTPException as e:
            log.warning("Failed to fetch invites in %s: %s", guild.name, e)
            return {}

    async def _get_config(self, guild_id: int) -> dict:
        from ..settings import Settings as InviteSettings

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return dict(InviteSettings.COLUMNS)
        settings = await InviteSettings.fetch(self.bot, guild)
        return {
            "enabled": bool(settings.enabled),
            "channel_id": settings.channel_id,
            "message": settings.message,
            "leave_message": settings.leave_message,
            "fake_remove": settings.fake_remove,
        }

    async def _find_used_invite(
        self,
        before: dict[str, int],
        after: dict[str, int],
        member: discord.Member,
    ) -> discord.Invite | None:
        """Compare invite snapshots to find which invite was used"""
        for code, uses in after.items():
            old_uses = before.get(code, 0)
            if uses > old_uses:
                try:
                    invite = await self.bot.fetch_invite(code)
                    return invite
                except discord.HTTPException:
                    continue
        return None

    async def _get_net_invites(self, guild_id: int, user_id: int) -> int:
        """Get net invite count: invites - leaves - fake + bonus"""
        data = await self.db.fetchrow(
            "SELECT * FROM invite_counts WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        if not data:
            return 0
        return data["invites"] - data["leaves"] - data["fake"] + data["bonus"]

    @Package.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild

        before = self._invite_cache.get(guild.id, {})
        if not before:
            log.warning("No cached invites for %s — fetching fresh snapshot (detection may be inaccurate)", guild.name)
            before = await self._snapshot_invites(guild)
            if not before:
                log.warning("No invites found in %s, skipping", guild.name)
                return
            
            self._invite_cache[guild.id] = before

        
        await asyncio.sleep(2)

        after = await self._snapshot_invites(guild)

        if after:
            self._invite_cache[guild.id] = after

        invite = await self._find_used_invite(before, after, member)

        if not invite:
            log.debug("No used invite detected for %s in %s", member, guild.name)
            return

        inviter = invite.inviter
        if not inviter:
            log.debug("Invite has no inviter in %s", guild.name)
            return

        
        await self.db.execute(
            """
            INSERT INTO invite_counts (guild_id, user_id, invites, leaves, fake, bonus)
                VALUES ($1, $2, 1, 0, 0, 0)
            ON CONFLICT (guild_id, user_id)
                DO UPDATE SET invites = invite_counts.invites + 1
            """,
            guild.id,
            inviter.id,
        )

        
        await self.db.execute(
            """
            INSERT INTO invite_uses (guild_id, code, inviter_id, uses)
                VALUES ($1, $2, $3, 1)
            ON CONFLICT (guild_id, code)
                DO UPDATE SET uses = invite_uses.uses + 1
            """,
            guild.id,
            invite.code,
            inviter.id,
        )

        
        await self.db.execute(
            """
            INSERT INTO member_invites (guild_id, invitee_id, inviter_id, code)
                VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, invitee_id)
                DO UPDATE SET inviter_id = $3, code = $4, joined_at = CURRENT_TIMESTAMP
            """,
            guild.id,
            member.id,
            inviter.id,
            invite.code,
        )

        config = await self._get_config(guild.id)
        if not config.get("enabled"):
            log.info("[inviter] %s joined %s but invite tracking is disabled", member, guild.name)
            return

        channel = guild.get_channel(config.get("channel_id"))
        if not channel:
            log.warning("[inviter] %s joined %s but no channel configured", member, guild.name)
            return

        total = await self._get_net_invites(guild.id, inviter.id)
        word = _invite_word(total)

        inviter_member = guild.get_member(inviter.id) or inviter

        invite_vars = {
            "inviter": inviter_member,
            "invitee": member,
            "invites": str(total),
            "invite_word": word,
            "code": invite.code,
            "url": invite.url,
            "guild": guild,
        }

        template = config.get(
            "message",
            "{inviter.mention} invited {invitee.mention}. They have **{invites}** {invite_word}.",
        )

        log.info("[inviter] guild=%s template=%r", guild.id, template)

        script = Script(template, user=member)
        rendered = _fix_invite_plural(script.render(**invite_vars), total)

        log.info("[inviter] rendered=%r", rendered)

        await channel.send(rendered)

    @Package.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild

        
        invites = await self._snapshot_invites(guild)
        if invites:
            self._invite_cache[guild.id] = invites

        config = await self._get_config(guild.id)

        
        row = await self.db.fetchrow(
            "SELECT inviter_id FROM member_invites WHERE guild_id = $1 AND invitee_id = $2",
            guild.id,
            member.id,
        )

        inviter_id = row["inviter_id"] if row else None

        
        if inviter_id:
            await self.db.execute(
                """
                INSERT INTO invite_counts (guild_id, user_id, invites, leaves, fake, bonus)
                    VALUES ($1, $2, 0, 1, 0, 0)
                ON CONFLICT (guild_id, user_id)
                    DO UPDATE SET leaves = invite_counts.leaves + 1
                """,
                guild.id,
                inviter_id,
            )

        
        if inviter_id:
            await self.db.execute(
                "DELETE FROM member_invites WHERE guild_id = $1 AND invitee_id = $2",
                guild.id,
                member.id,
            )

        if not config.get("enabled") or not inviter_id:
            return

        channel = guild.get_channel(config.get("channel_id"))
        if not channel:
            return

        inviter = guild.get_member(inviter_id) or self.bot.get_user(inviter_id)
        if not inviter:
            return

        total = await self._get_net_invites(guild.id, inviter_id)
        word = _invite_word(total)

        leave_vars = {
            "inviter": inviter,
            "invitee": member,
            "invites": str(total),
            "invite_word": word,
            "guild": guild,
        }

        template = config.get(
            "leave_message",
            "{invitee} left. {inviter} now has **{invites}** {invite_word}.",
        )

        script = Script(template, user=member)
        rendered = _fix_invite_plural(script.render(**leave_vars), total)

        await channel.send(rendered)
