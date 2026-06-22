from __future__ import annotations

import contextlib

import discord

from core.discord.package import Package


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

        config = await self.bot.db.fetchrow(
            "SELECT * FROM voicemaster_configuration WHERE guild_id = $1",
            member.guild.id,
        )
        if not config or config["channel_id"] != after.channel.id:
            return

        cooldown_key = f"vm_create:{member.id}"
        if self._get_cooldown(cooldown_key, 1, 10):
            with contextlib.suppress(discord.HTTPException):
                await member.move_to(None)
            return

        await self._create_member_channel(member, config, after.channel)

    async def _handle_leave(self, member: discord.Member, channel: discord.VoiceChannel):
        """Handle user leaving a voice channel."""
        config = await self.bot.db.fetchrow(
            "SELECT role_id FROM voicemaster_configuration WHERE guild_id = $1",
            member.guild.id
        )
        
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
        
        owner_id = await self.bot.db.fetchval(
            "DELETE FROM voicemaster_channels WHERE channel_id = $1 RETURNING owner_id",
            channel.id
        )
        
        if owner_id:
            try:
                await channel.delete(reason="VoiceMaster: Empty channel")
            except discord.HTTPException:
                pass

