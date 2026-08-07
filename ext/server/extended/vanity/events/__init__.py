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

        settings = await Settings.fetch(self.bot, guild)
        if not settings.role_ids and not settings.channel_id:
            return

        code = guild.vanity_url_code.lower()
        strict = settings.strict
        before_on = vanity_matches(before_status, code, strict=strict)
        after_on = vanity_matches(after_status, code, strict=strict)

        if before_on == after_on:
            return

        log.info(
            "vanity presence guild=%s member=%s before=%r after=%r on=%s→%s",
            guild.id,
            after.id,
            before_status,
            after_status,
            before_on,
            after_on,
        )

        
        
        await self._apply_vanity_state(
            after, settings, repping=after_on, notify=after_on
        )

    async def _apply_vanity_state(
        self,
        member: Member,
        settings: Settings,
        *,
        repping: bool,
        notify: bool,
    ) -> None:
        """Grant/remove vanity roles and optionally send the notification."""
        
        candidates = settings.grantable_roles
        has = [role for role in candidates if role in member.roles]
        miss = [role for role in candidates if role not in member.roles]
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
                    "vanity add_roles failed member=%s guild=%s roles=%s: %s "
                    "(bot role must be ABOVE vanity roles; Manage Roles required)",
                    member.id,
                    member.guild.id,
                    [r.id for r in miss],
                    exc,
                )
                
                for role in miss:
                    try:
                        await member.add_roles(
                            role,
                            reason=f"vanity /{code} now in status",
                        )
                    except Exception as e2:
                        log.warning(
                            "vanity add_role failed role=%s member=%s: %s",
                            role.id,
                            member.id,
                            e2,
                        )
        elif not candidates and settings.role_ids:
            log.warning(
                "vanity roles configured but none found in guild=%s role_ids=%s",
                member.guild.id,
                settings.role_ids,
            )

        
        if notify:
            try:
                await settings.dispatch(member)
            except Exception:
                log.exception(
                    "vanity dispatch raised member=%s guild=%s",
                    member.id,
                    member.guild.id,
                )

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
        
        await self._apply_vanity_state(
            member, settings, repping=repping, notify=bool(notify and repping)
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
            candidates = settings.grantable_roles
            has = any(r in member.roles for r in candidates)
            will_grant = repping and candidates and not has
            await self._apply_vanity_state(
                member,
                settings,
                repping=repping,
                notify=bool(notify and will_grant),
            )
        return count
