from __future__ import annotations

import logging

from core.discord.package import Package

log = logging.getLogger("vain.music.events")


class MusicEvents(Package):
    @Package.listener("on_ready")
    async def _connect_nodelink_on_ready(self) -> None:
        try:
            await self._connect_node()
        except Exception:
            pass

    @Package.listener("on_lyra_track_start")
    async def _on_track_start(self, player, track) -> None:
        if not player.guild:
            return
        state = self._queue(player.guild.id)
        state.current = track
        try:
            await self._set_vc_status(player, track)
        except Exception:
            pass
        try:
            await self._send_control_panel(player.guild.id, player, track)
        except Exception:
            log.exception("panel on track_start failed")

    @Package.listener("on_lyra_track_end")
    async def _on_track_end(self, player, track, reason) -> None:
        if not player.guild:
            return
        reason_u = (
            str(getattr(reason, "name", reason) or reason).upper().replace(" ", "_")
        )
        
        if reason_u in {"REPLACED", "STOPPED", "CLEANUP"}:
            return
        if reason_u not in {"FINISHED", "LOAD_FAILED", "LOADFAILED"}:
            return
        try:
            await self._play_next(player.guild.id, player)
        except Exception:
            log.exception("track_end advance failed")

    @Package.listener("on_lyra_track_stuck")
    async def _on_track_stuck(self, player, track, threshold) -> None:
        if not player.guild:
            return
        try:
            await self._play_next(player.guild.id, player, force=True)
        except Exception:
            pass

    @Package.listener("on_lyra_track_exception")
    async def _on_track_exception(self, player, track, exception) -> None:
        if not player.guild:
            return
        log.warning("track exception guild=%s: %s", player.guild.id, exception)
        try:
            await self._play_next(player.guild.id, player, force=True)
        except Exception:
            pass

    @Package.listener("on_voice_state_update")
    async def _vc_cleanup(self, member, before, after) -> None:
        """Leave when the last human leaves the bot's channel — never on bot self-updates."""
        
        if self.bot.user and member.id == self.bot.user.id:
            return
        if member.bot:
            return
        
        if before.channel is None:
            return
        if after.channel is not None and after.channel.id == before.channel.id:
            return

        guild = before.channel.guild
        if guild is None:
            return
        vc = guild.voice_client
        if vc is None or vc.channel is None:
            return
        if vc.channel.id != before.channel.id:
            return

        humans = [m for m in vc.channel.members if not m.bot]
        if humans:
            return
        try:
            await self._set_vc_status(vc, None)
        except Exception:
            pass
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        self.queues.pop(guild.id, None)
