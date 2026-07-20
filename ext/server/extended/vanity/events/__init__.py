from __future__ import annotations

import contextlib
import logging

import discord
from discord import HTTPException, Member

from core.discord.package import Package

from ..settings import Settings, get_status, vanity_matches

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
        if before_on == after_on:
            return

        assignable = settings.assignable_roles
        has = [role for role in assignable if role in after.roles]
        miss = [role for role in assignable if role not in after.roles]

        with contextlib.suppress(HTTPException, discord.Forbidden):
            if not after_on and has:
                log.debug("removing vanity roles from %s in %s", after, guild.name)
                await after.remove_roles(
                    *has,
                    reason=f"vanity /{guild.vanity_url_code} no longer in status",
                    atomic=False,
                )
            elif after_on:
                if miss:
                    log.debug("adding vanity roles to %s in %s", after, guild.name)
                    await after.add_roles(
                        *miss,
                        reason=f"vanity /{guild.vanity_url_code} now in status",
                        atomic=False,
                    )
                # Always notify when they start repping (default message if unset)
                await settings.dispatch(before, after)
