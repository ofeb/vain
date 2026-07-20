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

        before_on = member_repping_tag(before, after.guild)
        after_on = member_repping_tag(after, after.guild)
        if before_on == after_on:
            return

        settings = await Settings.fetch(self.bot, after.guild)
        if not settings:
            return

        with contextlib.suppress(HTTPException, discord.Forbidden):
            has = [role for role in settings.roles if role in after.roles]
            miss = [role for role in settings.roles if role not in after.roles]

            if not after_on and has:
                log.debug("removing tag roles from %s in %s", after, after.guild.name)
                await after.remove_roles(
                    *has,
                    reason="guild tag no longer displayed",
                    atomic=False,
                )
            elif after_on and miss:
                log.debug("adding tag roles to %s in %s", after, after.guild.name)
                await after.add_roles(
                    *miss,
                    reason="guild tag (primary guild) displayed",
                    atomic=False,
                )
                await settings.dispatch(before, after)
