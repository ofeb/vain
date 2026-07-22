from __future__ import annotations

from core.discord.package import Package


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
            await self._send_control_panel(player.guild.id, player, track)
        except Exception:
            pass

    @Package.listener("on_lyra_track_end")
    async def _on_track_end(self, player, track, reason) -> None:
        if not player.guild:
            return
        reason_u = str(getattr(reason, "name", reason) or reason).upper().replace(" ", "_")
        # stopped = manual skip/stop (caller advances or clears queue)
        # replaced = play() swapped tracks
        if reason_u in {"REPLACED", "STOPPED", "CLEANUP"}:
            return
        if reason_u not in {"FINISHED", "LOAD_FAILED", "LOADFAILED"}:
            return
        try:
            await self._play_next(player.guild.id, player)
        except Exception:
            pass

    @Package.listener("on_lyra_track_stuck")
    async def _on_track_stuck(self, player, track, threshold) -> None:
        if not player.guild:
            return
        try:
            await self._play_next(player.guild.id, player)
        except Exception:
            pass

    @Package.listener("on_lyra_track_exception")
    async def _on_track_exception(self, player, track, exception) -> None:
        if not player.guild:
            return
        try:
            await self._play_next(player.guild.id, player)
        except Exception:
            pass

    @Package.listener("on_voice_state_update")
    async def _vc_cleanup(self, member, before, after) -> None:
        # Only care when someone leaves a channel the bot is in
        if before.channel is None:
            return
        guild = before.channel.guild
        if guild is None:
            return
        vc = guild.voice_client
        if vc is None or vc.channel is None:
            return
        if vc.channel.id != before.channel.id:
            return
        # Bot alone → disconnect and clear queue
        humans = [m for m in before.channel.members if not m.bot]
        if humans:
            return
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        self.queues.pop(guild.id, None)
