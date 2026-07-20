from __future__ import annotations

import contextlib
import logging

import discord
from discord import HTTPException, Member

from core.discord.package import Package

from ..settings import Settings, get_status

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
        status = get_status(after)
        if status == before_status:
            return

        settings = await Settings.fetch(self.bot, guild)
        if not settings:
            return

        code = guild.vanity_url_code.lower()
        with contextlib.suppress(HTTPException, discord.Forbidden):
            has = [role for role in settings.roles if role in after.roles]
            miss = [role for role in settings.roles if role not in after.roles]

            if code not in status and has:
                log.debug("removing vanity roles from %s in %s", after, guild.name)
                await after.remove_roles(
                    *has,
                    reason=f"vanity /{guild.vanity_url_code} no longer in status",
                    atomic=False,
                )
            elif code in status and miss:
                log.debug("adding vanity roles to %s in %s", after, guild.name)
                await after.add_roles(
                    *miss,
                    reason=f"vanity /{guild.vanity_url_code} now in status",
                    atomic=False,
                )
                await settings.dispatch(before, after)
