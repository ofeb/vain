from __future__ import annotations

import logging

import discord
from discord import HTTPException, Member

from core.discord.package import Package

from ..settings import Settings, member_repping_tag

log = logging.getLogger("vain.tag")


class TagEvents:
    @Package.listener("on_member_update")
    async def tag_listener(self, before: Member, after: Member) -> None:
        if after.bot or after.guild is None:
            return

        settings = await Settings.fetch(self.bot, after.guild)
        if not settings.role_ids and not settings.channel_id:
            return

        strict = settings.strict
        before_on = member_repping_tag(before, after.guild, strict=strict)
        after_on = member_repping_tag(after, after.guild, strict=strict)
        if before_on == after_on:
            return

        log.info(
            "tag update guild=%s member=%s on=%s→%s",
            after.guild.id,
            after.id,
            before_on,
            after_on,
        )
        await self._apply_tag_state(after, settings, repping=after_on, notify=after_on)

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
        repping = member_repping_tag(member, guild, strict=settings.strict)
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
            repping = member_repping_tag(member, guild, strict=settings.strict)
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
