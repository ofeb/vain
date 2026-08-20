from __future__ import annotations

import contextlib

import discord

from core.discord.package import Package
from ..settings import Settings


class VoiceMasterEvents:
    @Package.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle voice state updates for VoiceMaster."""
        if before.channel == after.channel:
            return

        if before.channel is not None:
            await self._handle_leave(member, before.channel)

        if after.channel is None:
            return

        await self._handle_join2unmute(member, after.channel)

        config = await Settings.fetch_voice_config(self.bot.db, member.guild.id)
        if not config or config["channel_id"] != after.channel.id:
            return

        ban_info = await Settings.check_ban(self.bot.db, member.guild.id, member.id)
        if ban_info:
            ban_owner_id = ban_info.get("banned_by") if hasattr(ban_info, "get") else None
            if ban_owner_id and member.id == ban_owner_id:
                pass
            else:
                with contextlib.suppress(discord.HTTPException):
                    await member.move_to(None, reason="VoiceMaster: banned from voicemaster")
                return

        cooldown_key = f"vm_create:{member.id}"
        if self._get_cooldown(cooldown_key, 1, 10):
            with contextlib.suppress(discord.HTTPException):
                await member.move_to(None)
            return

        await self._create_member_channel(member, config, after.channel)

    async def _handle_join2unmute(self, member: discord.Member, channel: discord.VoiceChannel):
        """Auto-unmute server-muted users joining a join2unmute channel."""
        if not member.guild_permissions.mute_members:
            pass
        row = await Settings.check_join2unmute(self.bot.db, member.guild.id, channel.id)
        if not row:
            return
        if member.voice is None or member.voice.channel != channel:
            return
        if not member.is_timed_out() and not any(
            r.name.lower() == "muted" for r in member.roles
        ):
            return
        muted_role = discord.utils.get(member.guild.roles, name="Muted")
        if muted_role and muted_role in member.roles:
            with contextlib.suppress(discord.HTTPException):
                await member.remove_roles(muted_role, reason="VoiceMaster: join2unmute")
        if member.is_timed_out():
            with contextlib.suppress(discord.HTTPException):
                await member.timeout(None, reason="VoiceMaster: join2unmute")

    async def _handle_leave(self, member: discord.Member, channel: discord.VoiceChannel):
        """Handle user leaving a voice channel."""
        config = await Settings.fetch_voice_config(self.bot.db, member.guild.id)

        if config and (role_id := config.get("role_id")):
            role = member.guild.get_role(role_id)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="VoiceMaster: Left voice channel")
                except discord.HTTPException:
                    pass

        human_members = [m for m in channel.members if not m.bot]
        if human_members:
            return

        owner_id = await Settings.delete_channel(self.bot.db, channel.id)

        if owner_id:
            try:
                await channel.delete(reason="VoiceMaster: Empty channel")
            except discord.HTTPException:
                pass
