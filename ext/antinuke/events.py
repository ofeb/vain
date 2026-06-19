from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from discord.ext.commands import Cog

AUDIT_BACKLOG = 8
WINDOW = 60


class Events(Cog):
    """supplementary audit-log listeners that forward events to the Package cog."""

    def __init__(self: "Events", bot: discord.Client):
        self.bot = bot
        self._activity: dict[str, list[datetime]] = {}

    async def _hit_check(
        self,
        guild: discord.Guild,
        user_id: int,
        action: str,
        *,
        limit: int = 5,
        window: int = WINDOW,
    ) -> tuple[bool, str | None]:
        row = await self.bot.db.fetchrow(
            "SELECT * FROM antinuke WHERE guild_id = $1", guild.id
        )
        if not row:
            return False, None

        owner_id = getattr(guild, "owner_id", None)
        admins = set(row.get("admins") or [])
        admins.add(owner_id)
        if user_id in admins:
            return False, None

        mod = row.get(action)
        if not mod or not isinstance(mod, dict) or not mod.get("status"):
            return False, None

        penalty = str(mod.get("punishment", "warn"))
        mod_limit = int(mod.get("threshold", limit))

        now = datetime.now(timezone.utc)
        key = f"{guild.id}:{user_id}:{action}"
        bucket = self._activity.setdefault(key, [])
        bucket.append(now)
        bucket[:] = [t for t in bucket if (now - t).total_seconds() < window]

        if len(bucket) >= mod_limit:
            return True, penalty
        return False, None

    async def _apply(self, member: discord.Member, penalty: str, reason: str) -> None:
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            if penalty == "ban":
                await member.ban(reason=reason)
            elif penalty == "kick":
                await member.kick(reason=reason)

    async def _locate_actor(
        self,
        guild: discord.Guild,
        audit_action: discord.AuditLogAction,
        target_id: int,
    ) -> discord.Member | None:
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            async for entry in guild.audit_logs(limit=AUDIT_BACKLOG, action=audit_action):
                if entry.target and getattr(entry.target, "id", None) == target_id:
                    if isinstance(entry.user, discord.Member):
                        return entry.user
                    if entry.user:
                        m = guild.get_member(entry.user.id)
                        if m:
                            return m
                        with contextlib.suppress(discord.HTTPException):
                            return await guild.fetch_member(entry.user.id)
                    return None
        return None

    @Cog.listener("on_member_ban")
    async def _watch_ban(self, guild: discord.Guild, user: discord.User) -> None:
        actor = await self._locate_actor(guild, discord.AuditLogAction.ban, user.id)
        if actor is None:
            return
        punish, action = await self._hit_check(guild, actor.id, "ban")
        if punish and action:
            await self._apply(actor, action, f"antinuke-events: ban spike ({action})")

    @Cog.listener("on_member_remove")
    async def _watch_kick(self, member: discord.Member) -> None:
        guild = member.guild
        actor = await self._locate_actor(guild, discord.AuditLogAction.kick, member.id)
        if actor is None:
            return
        punish, action = await self._hit_check(guild, actor.id, "kick")
        if punish and action:
            await self._apply(actor, action, f"antinuke-events: kick spike ({action})")

    @Cog.listener("on_guild_role_create")
    async def _watch_role_create(self, role: discord.Role) -> None:
        guild = role.guild
        actor = await self._locate_actor(guild, discord.AuditLogAction.role_create, role.id)
        if actor is None:
            return
        punish, action = await self._hit_check(guild, actor.id, "role")
        if punish and action:
            await self._apply(actor, action, f"antinuke-events: role create ({action})")
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await role.delete(reason="antinuke-events: unauthorised role")

    @Cog.listener("on_guild_channel_create")
    async def _watch_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        guild = channel.guild
        actor = await self._locate_actor(guild, discord.AuditLogAction.channel_create, channel.id)
        if actor is None:
            return
        punish, action = await self._hit_check(guild, actor.id, "channel")
        if punish and action:
            await self._apply(actor, action, f"antinuke-events: channel create ({action})")
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await channel.delete(reason="antinuke-events: unauthorised channel")

    @Cog.listener("on_guild_role_update")
    async def _watch_role_perm(self, before: discord.Role, after: discord.Role) -> None:
        if before.permissions == after.permissions:
            return
        guild = after.guild
        actor = await self._locate_actor(guild, discord.AuditLogAction.role_update, after.id)
        if actor is None:
            return
        punish, action = await self._hit_check(guild, actor.id, "role")
        if punish and action:
            await self._apply(actor, action, f"antinuke-events: role perm ({action})")
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await after.edit(permissions=before.permissions, reason="antinuke-events: perm rollback")


async def setup(bot: discord.Client) -> None:
    await bot.add_cog(Events(bot))
