from __future__ import annotations

import logging

import discord
from discord import HTTPException, Member

from core.discord.package import Package

from ..settings import Settings, get_status, member_repping_vanity, vanity_matches

log = logging.getLogger("vain.vanity")


class VanityEvents:
    @Package.listener("on_presence_update")
    async def vanity_listener(self, before: Member, after: Member) -> None:
        if after.bot:
            return
        guild = after.guild
        if guild is None or not guild.vanity_url_code:
            return

        before_status = get_status(before)
        after_status = get_status(after)
        
        if before_status == after_status:
            return

        settings = await Settings.fetch(self.bot, guild)
        if not settings.role_ids and not settings.channel_id:
            return

        code = guild.vanity_url_code.lower()
        strict = settings.strict
        before_on = vanity_matches(before_status, code, strict=strict)
        after_on = vanity_matches(after_status, code, strict=strict)

        log.debug(
            "vanity presence guild=%s member=%s before=%r after=%r on=%s→%s",
            guild.id,
            after.id,
            before_status,
            after_status,
            before_on,
            after_on,
        )

        if before_on == after_on:
            return

        await self._apply_vanity_state(after, settings, repping=after_on, notify=after_on)

    async def _apply_vanity_state(
        self,
        member: Member,
        settings: Settings,
        *,
        repping: bool,
        notify: bool,
    ) -> None:
        """Grant/remove vanity roles and optionally send the notification."""
        assignable = settings.assignable_roles
        has = [role for role in assignable if role in member.roles]
        miss = [role for role in assignable if role not in member.roles]
        code = member.guild.vanity_url_code or "?"

        if not repping:
            if has:
                try:
                    await member.remove_roles(
                        *has,
                        reason=f"vanity /{code} no longer in status",
                        atomic=False,
                    )
                    log.info(
                        "vanity roles removed member=%s guild=%s roles=%s",
                        member.id,
                        member.guild.id,
                        [r.id for r in has],
                    )
                except (HTTPException, discord.Forbidden) as exc:
                    log.warning(
                        "vanity remove_roles failed member=%s guild=%s: %s",
                        member.id,
                        member.guild.id,
                        exc,
                    )
            return

        
        if miss:
            try:
                await member.add_roles(
                    *miss,
                    reason=f"vanity /{code} now in status",
                    atomic=False,
                )
                log.info(
                    "vanity roles added member=%s guild=%s roles=%s",
                    member.id,
                    member.guild.id,
                    [r.id for r in miss],
                )
            except (HTTPException, discord.Forbidden) as exc:
                log.warning(
                    "vanity add_roles failed member=%s guild=%s: %s "
                    "(check role hierarchy — bot role must be above vanity roles)",
                    member.id,
                    member.guild.id,
                    exc,
                )
        elif not assignable and settings.role_ids:
            log.warning(
                "vanity roles configured but none assignable guild=%s role_ids=%s",
                member.guild.id,
                settings.role_ids,
            )

        if notify:
            await settings.dispatch(member)

    async def sync_member(
        self, member: Member, *, notify: bool = False
    ) -> bool | None:
        """Re-evaluate vanity for one member. Returns repping state or None if N/A."""
        guild = member.guild
        if guild is None or member.bot or not guild.vanity_url_code:
            return None
        settings = await Settings.fetch(self.bot, guild)
        if not settings.role_ids and not settings.channel_id:
            return None
        repping = member_repping_vanity(member, guild, strict=settings.strict)
        assignable = settings.assignable_roles
        has = [r for r in assignable if r in member.roles]
        
        should_notify = notify and repping and bool([r for r in assignable if r not in member.roles])
        
        if repping and not has and assignable:
            should_notify = notify
        elif repping and has and notify:
            
            should_notify = notify
        await self._apply_vanity_state(
            member, settings, repping=repping, notify=should_notify and repping
        )
        return repping

    async def sync_guild(self, guild: discord.Guild, *, notify: bool = False) -> int:
        """Scan cached members and apply vanity roles. Returns count repping."""
        if not guild.vanity_url_code:
            return 0
        settings = await Settings.fetch(self.bot, guild)
        if not settings.role_ids and not settings.channel_id:
            return 0
        count = 0
        for member in list(guild.members):
            if member.bot:
                continue
            repping = member_repping_vanity(member, guild, strict=settings.strict)
            if repping:
                count += 1
            assignable = settings.assignable_roles
            has = any(r in member.roles for r in assignable)
            
            will_grant = repping and assignable and not has
            await self._apply_vanity_state(
                member,
                settings,
                repping=repping,
                notify=bool(notify and will_grant),
            )
        return count
