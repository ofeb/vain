from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, Optional

import discord
from core.discord.package import Package, tasks

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.values import color

if TYPE_CHECKING:
    from core.bleed import Bleed

try:
    import pomice
    HAS_POMICE = True
except ImportError:
    HAS_POMICE = False


class MusicPlayer:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.queue: list[pomice.Track] = []
        self.current: Optional[pomice.Track] = None
        self.loop = False
        self.loop_queue = False
        self.volume = 100

    async def add_track(self, track: pomice.Track) -> None:
        self.queue.append(track)

    def skip(self) -> Optional[pomice.Track]:
        if self.queue:
            return self.queue.pop(0)
        return None

    def clear(self) -> None:
        self.queue.clear()
        self.current = None

    @property
    def is_empty(self) -> bool:
        return not self.current and not self.queue


class Music(Package):
    """Queue, playback, and music controls."""

    def __init__(self, bot: Bleed):
        super().__init__(bot)
        self.players: dict[int, MusicPlayer] = {}
        self.pomice_pool: pomice.NodePool = None

    async def cog_load(self):
        if not HAS_POMICE:
            return
        self.pomice_pool = pomice.NodePool()
        try:
            await self.pomice_pool.create_node(
                bot=self.bot,
                host="127.0.0.1",
                port=2333,
                password="youshallnotpass",
                identifier="bleed-node",
            )
        except Exception:
            pass

    def _get_player(self, ctx: Context) -> Optional[MusicPlayer]:
        return self.players.get(ctx.guild.id)

    async def _ensure_voice(self, ctx: Context) -> bool:
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.fail("You need to be in a voice channel first.")
            return False

        player = self._get_player(ctx)
        if player and player.ctx.voice_client and player.ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.fail("I'm already playing in a different voice channel.")
            return False

        return True

    @group(
        name="play",
        description="Play a song from YouTube or other supported sources",
        invoke_without_command=True,
        aliases=["p"],
    )
    async def play(self, ctx: Context, *, query: str) -> None:
        if not await self._ensure_voice(ctx):
            return

        if not HAS_POMICE:
            await ctx.fail("Lavalink is not available. Music playback requires Lavalink/pomice.")
            return

        try:
            results = await self.pomice_pool.get_tracks(query)
            if not results:
                await ctx.fail("No results found.")
                return

            track = results[0]
            player = self._get_player(ctx)
            if not player:
                player = MusicPlayer(ctx)
                self.players[ctx.guild.id] = player

            if not ctx.voice_client:
                await ctx.author.voice.channel.connect(cls=pomice.Player)
                player.ctx = ctx

            player.add_track(track)

            embed = discord.Embed(
                title="Added to Queue",
                description=f"[{track.title}]({track.uri}) by **{track.author}**",
                color=color.base,
            )
            embed.add_field(name="Duration", value=self._format_duration(track.length), inline=True)
            embed.set_thumbnail(url=track.thumbnail)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.fail(f"Playback error: {str(e)[:100]}")

    @play.command(
        name="now",
        description="Show the currently playing track",
        aliases=["np", "current"],
    )
    async def play_now(self, ctx: Context) -> None:
        player = self._get_player(ctx)
        if not player or not player.current:
            await ctx.fail("Nothing is currently playing.")
            return

        track = player.current
        embed = discord.Embed(
            title="Now Playing",
            description=f"[{track.title}]({track.uri}) by **{track.author}**",
            color=color.base,
        )
        embed.add_field(name="Duration", value=self._format_duration(track.length), inline=True)
        embed.set_thumbnail(url=track.thumbnail)
        await ctx.send(embed=embed)

    @play.command(
        name="queue",
        description="View the music queue",
        aliases=["q"],
    )
    async def play_queue(self, ctx: Context) -> None:
        player = self._get_player(ctx)
        if not player or not player.queue:
            await ctx.fail("The queue is empty.")
            return

        entries = []
        total_duration = 0
        for i, track in enumerate(player.queue[:15], 1):
            total_duration += track.length
            entries.append(f"`{i}.` **{track.title}** — {track.author} ({self._format_duration(track.length)})")

        embed = discord.Embed(
            title=f"Queue ({len(player.queue)} tracks)",
            description="\n".join(entries),
            color=color.base,
        )
        embed.add_field(name="Total Duration", value=self._format_duration(total_duration), inline=True)
        await ctx.send(embed=embed)

    @play.command(
        name="skip",
        description="Skip the current track",
        aliases=["s"],
    )
    async def play_skip(self, ctx: Context) -> None:
        player = self._get_player(ctx)
        if not player or not player.current:
            await ctx.fail("Nothing is playing to skip.")
            return
        await ctx.success("Skipped the current track.")

    @play.command(
        name="stop",
        description="Stop playback and clear the queue",
    )
    async def play_stop(self, ctx: Context) -> None:
        player = self._get_player(ctx)
        if not player:
            await ctx.fail("Nothing is playing.")
            return
        player.clear()
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        self.players.pop(ctx.guild.id, None)
        await ctx.success("Stopped playback and cleared the queue.")

    @play.command(
        name="pause",
        description="Pause or resume playback",
    )
    async def play_pause(self, ctx: Context) -> None:
        player = self._get_player(ctx)
        if not player or not ctx.voice_client:
            await ctx.fail("Nothing is playing.")
            return
        if ctx.voice_client.is_paused():
            await ctx.voice_client.resume()
            await ctx.success("Resumed playback.")
        else:
            await ctx.voice_client.pause()
            await ctx.success("Paused playback.")

    @play.command(
        name="volume",
        description="Set the playback volume (0-200)",
    )
    async def play_volume(self, ctx: Context, level: int) -> None:
        if level < 0 or level > 200:
            await ctx.fail("Volume must be between 0 and 200.")
            return
        player = self._get_player(ctx)
        if player and ctx.voice_client:
            await ctx.voice_client.set_volume(level)
            player.volume = level
        await ctx.success(f"Volume set to **{level}%**.")

    @play.command(
        name="loop",
        description="Toggle track loop",
        aliases=["repeat"],
    )
    async def play_loop(self, ctx: Context) -> None:
        player = self._get_player(ctx)
        if not player:
            await ctx.fail("Nothing is playing.")
            return
        player.loop = not player.loop
        await ctx.success(f"Loop {'enabled' if player.loop else 'disabled'}.")

    @play.command(
        name="shuffle",
        description="Shuffle the queue",
    )
    async def play_shuffle(self, ctx: Context) -> None:
        player = self._get_player(ctx)
        if not player or len(player.queue) < 2:
            await ctx.fail("Not enough tracks in queue to shuffle.")
            return
        import random
        random.shuffle(player.queue)
        await ctx.success("Shuffled the queue.")

    @play.command(
        name="remove",
        description="Remove a track from the queue by position",
        aliases=["rm"],
    )
    async def play_remove(self, ctx: Context, position: int) -> None:
        player = self._get_player(ctx)
        if not player or position < 1 or position > len(player.queue):
            await ctx.fail(f"Invalid position. Queue has {len(player.queue)} tracks.")
            return
        track = player.queue.pop(position - 1)
        await ctx.success(f"Removed **{track.title}** from the queue.")

    def _format_duration(self, ms: int) -> str:
        seconds = math.ceil(ms / 1000)
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m {sec}s"
        return f"{minutes}m {sec}s"


async def setup(bot: Bleed):
    await bot.add_cog(Music(bot))
