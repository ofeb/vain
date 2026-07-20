from __future__ import annotations

import contextlib
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

        assignable = settings.assignable_roles
        has = [role for role in assignable if role in after.roles]
        miss = [role for role in assignable if role not in after.roles]

        with contextlib.suppress(HTTPException, discord.Forbidden):
            if not after_on and has:
                log.debug("removing tag roles from %s in %s", after, after.guild.name)
                await after.remove_roles(
                    *has,
                    reason="guild tag no longer displayed",
                    atomic=False,
                )
            elif after_on:
                if miss:
                    log.debug("adding tag roles to %s in %s", after, after.guild.name)
                    await after.add_roles(
                        *miss,
                        reason="guild tag displayed",
                        atomic=False,
                    )
                await settings.dispatch(before, after)
