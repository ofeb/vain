from __future__ import annotations

from core.discord.package import Package


class MusicEvents(Package):
    @Package.listener("on_ready")
    async def _connect_nodelink_on_ready(self) -> None:
        await self._connect_node()

    @Package.listener("on_lyra_track_end")
    async def _on_track_end(self, player, track, reason) -> None:
        if not player.guild:
            return
        if reason.upper() not in {"FINISHED", "LOAD_FAILED"}:
            return
        await self._play_next(player.guild.id, player)

    @Package.listener("on_lyra_track_stuck")
    async def _on_track_stuck(self, player, track, threshold) -> None:
        if player.guild:
            await self._play_next(player.guild.id, player)
