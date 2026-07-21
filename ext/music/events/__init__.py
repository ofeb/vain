from __future__ import annotations

from core.discord.package import Package


class MusicEvents(Package):
    @Package.listener("on_ready")
    async def _connect_nodelink_on_ready(self) -> None:
        await self._connect_node()

    @Package.listener("on_lyra_track_start")
    async def _on_track_start(self, player, track) -> None:
        if not player.guild:
            return
        await self._send_control_panel(player.guild.id, player, track)

    @Package.listener("on_lyra_track_end")
    async def _on_track_end(self, player, track, reason) -> None:
        if not player.guild:
            return
        reason_u = str(getattr(reason, "name", reason) or reason).upper()
        if reason_u == "REPLACED":
            return
        if reason_u not in {"FINISHED", "LOAD_FAILED"}:
            return
        await self._play_next(player.guild.id, player)

    @Package.listener("on_lyra_track_stuck")
    async def _on_track_stuck(self, player, track, threshold) -> None:
        if player.guild:
            await self._play_next(player.guild.id, player)

    @Package.listener("on_lyra_track_exception")
    async def _on_track_exception(self, player, track, exception) -> None:
        if player.guild:
            await self._play_next(player.guild.id, player)

    @Package.listener("on_voice_state_update")
    async def _vc_cleanup(self, member, before, after) -> None:
        if member.bot and member.id == getattr(self.bot.user, "id", None):
            return
        if before.channel is None:
            return
        guild = before.channel.guild
        vc = guild.voice_client
        if vc is None or vc.channel is None:
            return
        if vc.channel.id != before.channel.id:
            return
        
        humans = [m for m in before.channel.members if not m.bot]
        if not humans:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
            self.queues.pop(guild.id, None)
