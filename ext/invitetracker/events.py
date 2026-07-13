from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.package import Package
from core.tools.embed import Script

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("vain.invitetracker.events")


class InviteTrackerEvents(Package):
    """invite tracking event listeners"""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._invite_cache: dict[int, dict[str, int]] = {}

    async def cog_load(self) -> None:
        self.bot.loop.create_task(self._populate_cache())

    async def _populate_cache(self) -> None:
        """Snapshot invite uses for all guilds on startup."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            invites = await self._snapshot_invites(guild)
            if invites:
                self._invite_cache[guild.id] = invites
                log.debug("Cached %d invites for %s", len(invites), guild.name)

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
        row = await self.db.fetchrow(
            "SELECT * FROM invite_config WHERE guild_id = $1", guild_id
        )
        if not row:
            return {
                "enabled": False,
                "channel_id": None,
                "message": "{inviter} invited {invitee}. They have **{invites}** invites.",
                "leave_message": "{invitee} left. {inviter} now has **{invites}** invites.",
                "fake_remove": True,
            }
        return dict(row)

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

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild

        # Use cached invites as the "before" snapshot
        before = self._invite_cache.get(guild.id, {})
        if not before:
            log.debug("No cached invites for %s, fetching fresh", guild.name)
            before = await self._snapshot_invites(guild)
            if not before:
                log.debug("No invites found in %s, skipping", guild.name)
                return

        # Wait briefly for Discord to update invite counts
        await asyncio.sleep(2)

        # Snapshot invites AFTER the join
        after = await self._snapshot_invites(guild)

        # Update the cache with post-join state
        if after:
            self._invite_cache[guild.id] = after

        # Find which invite was used
        invite = await self._find_used_invite(before, after, member)

        if not invite:
            log.debug("No used invite detected for %s in %s", member, guild.name)
            return

        inviter = invite.inviter
        if not inviter:
            log.debug("Invite has no inviter in %s", guild.name)
            return

        # Update invite counts
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

        # Track invite use
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

        config = await self._get_config(guild.id)
        if not config.get("enabled"):
            return

        channel = guild.get_channel(config.get("channel_id"))
        if not channel:
            return

        # Get current invite count for inviter
        data = await self.db.fetchrow(
            "SELECT * FROM invite_counts WHERE guild_id = $1 AND user_id = $2",
            guild.id,
            inviter.id,
        )
        total = (data["invites"] - data["fake"] + data["bonus"]) if data else 1

        # Resolve inviter as a Member if possible for proper mention
        inviter_member = guild.get_member(inviter.id) or inviter

        # Build invite variables for template
        invite_vars = {
            "inviter": inviter_member,
            "invitee": member,
            "invites": str(total),
            "code": invite.code,
            "url": invite.url,
            "guild": guild,
        }

        template = config.get(
            "message",
            "{inviter.mention} invited {invitee.mention}. They have **{invites}** invites.",
        )

        script = Script(template, user=member)
        rendered = script.render(**invite_vars)

        await channel.send(rendered)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild

        # Update cache after member leaves
        invites = await self._snapshot_invites(guild)
        if invites:
            self._invite_cache[guild.id] = invites

        config = await self._get_config(guild.id)

        if not config.get("enabled"):
            return

        channel = guild.get_channel(config.get("channel_id"))
        if not channel:
            return

        # Find who invited this member by checking invite_uses
        row = await self.db.fetchrow(
            """SELECT inviter_id, code FROM invite_uses
               WHERE guild_id = $1 AND inviter_id != $2
               ORDER BY uses DESC LIMIT 1""",
            guild.id,
            member.id,
        )

        inviter_id = None
        if row:
            inviter_id = row["inviter_id"]

        # Update leave count for inviter
        if inviter_id:
            data = await self.db.fetchrow(
                "SELECT * FROM invite_counts WHERE guild_id = $1 AND user_id = $2",
                guild.id,
                inviter_id,
            )
            if data and data["invites"] > 0:
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

        if not inviter_id:
            return

        inviter = guild.get_member(inviter_id) or self.bot.get_user(inviter_id)
        if not inviter:
            return

        data = await self.db.fetchrow(
            "SELECT * FROM invite_counts WHERE guild_id = $1 AND user_id = $2",
            guild.id,
            inviter_id,
        )
        total = (data["invites"] - data["fake"] + data["bonus"]) if data else 0

        leave_vars = {
            "inviter": inviter,
            "invitee": member,
            "invites": str(total),
            "guild": guild,
        }

        template = config.get(
            "leave_message",
            "{invitee.mention} left. {inviter.mention} now has **{invites}** invites.",
        )

        script = Script(template, user=member)
        rendered = script.render(**leave_vars)

        await channel.send(rendered)
