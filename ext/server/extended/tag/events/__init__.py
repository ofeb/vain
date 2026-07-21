from __future__ import annotations

import logging

import discord
from discord import HTTPException, Member, User

from core.discord.package import Package

from ..settings import Settings, member_repping_tag, primary_guild_info

log = logging.getLogger("vain.tag")


class TagEvents:
    @Package.listener("on_user_update")
    async def tag_listener(self, before: User, after: User) -> None:
        """Detect primary guild / server tag changes via user updates.

        Discord exposes tag identity on the User object (primary_guild / clan),
        so member_update alone often never fires for tag adopt/remove.
        """
        if after.bot:
            return

        try:
            fresh_after = await self.bot.fetch_user(after.id)
            after_pg = primary_guild_info(fresh_after)
        except Exception:
            after_pg = primary_guild_info(after)

        before_pg = primary_guild_info(before)

        before_id = before_pg.get("id")
        after_id = after_pg.get("id")
        before_enabled = before_pg.get("identity_enabled")
        after_enabled = after_pg.get("identity_enabled")

        if before_id == after_id and before_enabled == after_enabled:
            return

        for guild in list(self.bot.guilds):
            member = guild.get_member(after.id)
            if member is None:
                continue

            settings = await Settings.fetch(self.bot, guild)
            if not settings.role_ids and not settings.channel_id:
                continue

            was_match = member_repping_tag_from_info(before_pg, guild)
            is_match = member_repping_tag_from_info(after_pg, guild)
            if was_match == is_match:
                continue

            log.info(
                "tag update guild=%s member=%s on=%s→%s",
                guild.id,
                after.id,
                was_match,
                is_match,
            )
            await self._apply_tag_state(
                member, settings, repping=is_match, notify=is_match
            )

    async def _apply_tag_state(
        self,
        member: Member,
        settings: Settings,
        *,
        repping: bool,
        notify: bool,
    ) -> None:
        candidates = settings.grantable_roles
        has = [role for role in candidates if role in member.roles]
        miss = [role for role in candidates if role not in member.roles]

        if not repping:
            if has:
                try:
                    await member.remove_roles(
                        *has,
                        reason="guild tag no longer displayed",
                        atomic=False,
                    )
                except (HTTPException, discord.Forbidden) as exc:
                    log.warning(
                        "tag remove_roles failed member=%s: %s", member.id, exc
                    )
            return

        if miss:
            try:
                await member.add_roles(
                    *miss,
                    reason="guild tag displayed",
                    atomic=False,
                )
            except (HTTPException, discord.Forbidden) as exc:
                log.warning(
                    "tag add_roles failed member=%s: %s "
                    "(bot role must be above tag roles)",
                    member.id,
                    exc,
                )
                for role in miss:
                    try:
                        await member.add_roles(role, reason="guild tag displayed")
                    except Exception as e2:
                        log.warning(
                            "tag add_role failed role=%s member=%s: %s",
                            role.id,
                            member.id,
                            e2,
                        )
        elif not candidates and settings.role_ids:
            log.warning(
                "tag roles configured but none found guild=%s role_ids=%s",
                member.guild.id,
                settings.role_ids,
            )

        if notify:
            try:
                await settings.dispatch(member)
            except Exception:
                log.exception(
                    "tag dispatch raised member=%s guild=%s",
                    member.id,
                    member.guild.id,
                )

    async def sync_member(
        self, member: Member, *, notify: bool = False
    ) -> bool | None:
        guild = member.guild
        if guild is None or member.bot:
            return None
        settings = await Settings.fetch(self.bot, guild)
        if not settings.role_ids and not settings.channel_id:
            return None
        repping = member_repping_tag(member, guild)
        await self._apply_tag_state(
            member, settings, repping=repping, notify=bool(notify and repping)
        )
        return repping

    async def sync_guild(self, guild: discord.Guild, *, notify: bool = False) -> int:
        settings = await Settings.fetch(self.bot, guild)
        if not settings.role_ids and not settings.channel_id:
            return 0
        count = 0
        for member in list(guild.members):
            if member.bot:
                continue
            repping = member_repping_tag(member, guild)
            if repping:
                count += 1
            candidates = settings.grantable_roles
            has = any(r in member.roles for r in candidates)
            will_grant = repping and candidates and not has
            await self._apply_tag_state(
                member,
                settings,
                repping=repping,
                notify=bool(notify and will_grant),
            )
        return count


def member_repping_tag_from_info(info: dict, guild: discord.Guild) -> bool:
    """Whether primary_guild info matches this guild (identity enabled or unknown)."""
    gid = info.get("id")
    if gid is None:
        return False
    try:
        if int(gid) != int(guild.id):
            return False
    except (TypeError, ValueError):
        return False
    enabled = info.get("identity_enabled")
    # Treat missing identity_enabled as a match (Discord sometimes omits it)
    return enabled is not False
