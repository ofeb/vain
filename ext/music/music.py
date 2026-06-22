from __future__ import annotations

import random
from typing import TYPE_CHECKING

import discord

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.managers.values import color, music as nl, music_enabled

from .events import MusicEvents

if TYPE_CHECKING:
    from core.bleed import Bleed

try:
    import lava_lyra as lyra

    HAS_LYRA = True
except ImportError:
    HAS_LYRA = False
    lyra = None


class GuildQueue:
    __slots__ = ("tracks", "current", "loop", "loop_queue", "volume", "active_preset")

    def __init__(self) -> None:
        self.tracks: list = []
        self.current = None
        self.loop = False
        self.loop_queue = False
        self.volume = 100
        self.active_preset: str | None = None


class Music(MusicEvents, Package):
    PRESETS = (
        "vaporwave", "karaoke", "nightcore", "boost", "flat",
        "chipmunk", "piano", "metal", "vibrato", "8d", "soft",
    )

    def __init__(self, bot: Bleed):
        super().__init__(bot)
        self.queues: dict[int, GuildQueue] = {}
        self._node = None

    async def cog_load(self) -> None:
        if not music_enabled or not HAS_LYRA:
            return
        try:
            self._node = await lyra.NodePool.create_node(
                bot=self.bot,
                host=nl.host,
                port=nl.port,
                password=nl.password,
                identifier=nl.identifier,
                fallback=True,
            )
        except Exception:
            self._node = None

    def _queue(self, guild_id: int) -> GuildQueue:
        return self.queues.setdefault(guild_id, GuildQueue())

    async def _ensure_voice(self, ctx: Context) -> bool:
        if ctx.guild is None:
            await ctx.fail("server only")
            return False
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.fail("join a voice channel first")
            return False
        if ctx.voice_client and ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.fail("already in another voice channel")
            return False
        return True

    async def _player(self, ctx: Context):
        if not HAS_LYRA or self._node is None:
            await ctx.fail("nodelink isn't running")
            return None
        if not await self._ensure_voice(ctx):
            return None
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect(cls=lyra.Player, self_deaf=True)
        return ctx.voice_client

    def _search_query(self, query: str) -> str:
        query = query.strip()
        if query.startswith(("http://", "https://")) or ":" in query.split(" ", 1)[0]:
            return query
        prefix = nl.search_source.strip()
        if prefix and not query.lower().startswith(prefix.lower()):
            return f"{prefix}:{query}"
        return query

    async def _first_track(self, query: str):
        if self._node is None:
            return None
        results = await self._node.get_tracks(self._search_query(query))
        if not results:
            return None
        tracks = results.tracks if hasattr(results, "tracks") else results
        return tracks[0] if tracks else None

    async def _apply_preset(self, player, preset: str) -> None:
        if not HAS_LYRA:
            return
        preset = preset.lower()
        if preset == "flat":
            await player.remove_filters()
            return
        if preset == "nightcore":
            f = lyra.Timescale(tag="nightcore", speed=1.2, pitch=1.2, rate=1.0)
        elif preset == "vaporwave":
            f = lyra.Timescale(tag="vaporwave", speed=0.85, pitch=0.9, rate=1.0)
        elif preset == "chipmunk":
            f = lyra.Timescale(tag="chipmunk", speed=1.3, pitch=1.4, rate=1.0)
        elif preset == "boost":
            f = lyra.Equalizer(tag="boost", levels=[(0, 0.2), (1, 0.15), (2, 0.1)])
        elif preset == "soft":
            f = lyra.Equalizer(tag="soft", levels=[(0, -0.1), (1, -0.05)])
        else:
            f = lyra.Timescale(tag=preset, speed=1.0, pitch=1.0, rate=1.0)
        await player.add_filter(f)

    async def _play_next(self, guild_id: int, player) -> None:
        state = self._queue(guild_id)
        if state.loop and state.current:
            track = state.current
        elif state.tracks:
            track = state.tracks.pop(0)
            if state.loop_queue:
                state.tracks.append(track)
            state.current = track
        else:
            state.current = None
            return
        await player.play(track)
        if state.active_preset:
            await self._apply_preset(player, state.active_preset)

    async def _set_preset(self, ctx: Context, name: str, setting: str | None) -> None:
        player = ctx.voice_client
        if player is None:
            return await ctx.fail("nothing playing")
        state = self._queue(ctx.guild.id)
        if setting and setting.lower() in {"off", "disable", "false", "none"}:
            state.active_preset = None
            await player.remove_filters()
            return await ctx.success(f"disabled **{name}**")
        state.active_preset = name
        await self._apply_preset(player, name)
        await ctx.success(f"enabled **{name}**")

    @hybrid(name="play", aliases=["p"], guild_only=True)
    @describe(query="Song name or URL", next="Play after the current track")
    async def play(self, ctx: Context, query: str, next: bool = False) -> None:
        player = await self._player(ctx)
        if player is None:
            return
        track = await self._first_track(query)
        if track is None:
            return await ctx.fail("no results")

        state = self._queue(ctx.guild.id)

        if player.is_playing or player.current:
            if next:
                state.tracks.insert(0, track)
            else:
                state.tracks.append(track)
            return await ctx.send(embed=discord.Embed(
                title="queued",
                description=f"**{track.title}** — {track.author}",
                color=color.base,
            ))

        state.current = track
        await player.play(track)
        if state.active_preset:
            await self._apply_preset(player, state.active_preset)
        await ctx.send(embed=discord.Embed(
            title="now playing",
            description=f"**{track.title}** — {track.author}",
            color=color.base,
        ))

    @hybrid(name="queue", description="View all tracks queued", group=True, invoke_without_command=True, guild_only=True)
    async def queue(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await self.queue_view(ctx)

    @queue.command(name="view", description="View all tracks queued", aliases=["list"])
    async def queue_view(self, ctx: Context) -> None:
        state = self._queue(ctx.guild.id)
        if not state.tracks and not state.current:
            return await ctx.fail("queue is empty")
        lines = [f"**now:** {state.current.title}"] if state.current else []
        lines.extend(f"`{i}.` **{t.title}** — {t.author}" for i, t in enumerate(state.tracks[:15], 1))
        await ctx.send(embed=discord.Embed(
            title=f"queue ({len(state.tracks)})",
            description="\n".join(lines),
            color=color.base,
        ))

    @queue.command(name="remove", description="Remove a track from the queue")
    @describe(position="Track position in the queue")
    async def queue_remove(self, ctx: Context, position: int) -> None:
        state = self._queue(ctx.guild.id)
        if position < 1 or position > len(state.tracks):
            return await ctx.fail(f"invalid position ({len(state.tracks)} tracks)")
        track = state.tracks.pop(position - 1)
        await ctx.success(f"removed **{track.title}**")

    @queue.command(name="shuffle", description="Shuffle the queue")
    async def queue_shuffle(self, ctx: Context) -> None:
        state = self._queue(ctx.guild.id)
        if len(state.tracks) < 2:
            return await ctx.fail("not enough tracks")
        random.shuffle(state.tracks)
        await ctx.success("shuffled")

    @queue.command(name="empty", description="Empty the queue", aliases=["clear"])
    async def queue_empty(self, ctx: Context) -> None:
        self._queue(ctx.guild.id).tracks.clear()
        await ctx.success("cleared queue")

    @queue.command(name="move", description="Move a track to a different position in the queue")
    @describe(position="Current position", new_position="New position")
    async def queue_move(self, ctx: Context, position: int, new_position: int) -> None:
        state = self._queue(ctx.guild.id)
        if not (1 <= position <= len(state.tracks) and 1 <= new_position <= len(state.tracks)):
            return await ctx.fail("invalid position")
        track = state.tracks.pop(position - 1)
        state.tracks.insert(new_position - 1, track)
        await ctx.success(f"moved **{track.title}** to `{new_position}`")

    @hybrid(name="skip", guild_only=True)
    async def skip(self, ctx: Context) -> None:
        player = ctx.voice_client
        if player is None or not player.is_playing:
            return await ctx.fail("nothing playing")
        await player.stop()
        await self._play_next(ctx.guild.id, player)
        await ctx.success("skipped")

    @hybrid(name="pause", guild_only=True)
    async def pause(self, ctx: Context) -> None:
        player = ctx.voice_client
        if player is None or not player.is_playing:
            return await ctx.fail("nothing playing")
        await player.pause()
        await ctx.success("paused")

    @hybrid(name="resume", guild_only=True)
    async def resume(self, ctx: Context) -> None:
        player = ctx.voice_client
        if player is None or not player.is_paused:
            return await ctx.fail("not paused")
        await player.resume()
        await ctx.success("resumed")

    @hybrid(name="shuffle", guild_only=True)
    async def shuffle(self, ctx: Context) -> None:
        state = self._queue(ctx.guild.id)
        state.loop_queue = not state.loop_queue
        await ctx.success(f"queue loop **{'on' if state.loop_queue else 'off'}**")

    @hybrid(name="repeat", guild_only=True)
    @describe(option="on or off")
    async def repeat(self, ctx: Context, option: str | None = None) -> None:
        state = self._queue(ctx.guild.id)
        state.loop = (not state.loop) if option is None else option.lower() in {"on", "true", "yes", "enable"}
        await ctx.success(f"repeat **{'on' if state.loop else 'off'}**")

    @hybrid(name="volume", guild_only=True)
    @describe(volume="Volume from 0 to 200")
    async def volume(self, ctx: Context, volume: int) -> None:
        if not 0 <= volume <= 200:
            return await ctx.fail("volume must be 0–200")
        player = ctx.voice_client
        if player is None:
            return await ctx.fail("nothing playing")
        await player.set_volume(volume)
        self._queue(ctx.guild.id).volume = volume
        await ctx.success(f"volume **{volume}%**")

    @hybrid(name="fastforward", guild_only=True)
    @describe(position="Seconds to fast forward")
    async def fastforward(self, ctx: Context, position: int) -> None:
        player = ctx.voice_client
        if player is None or player.current is None:
            return await ctx.fail("nothing playing")
        await player.seek(min(player.position + position * 1000, player.current.length))
        await ctx.success(f"+{position}s")

    @hybrid(name="rewind", guild_only=True)
    @describe(position="Seconds to rewind")
    async def rewind(self, ctx: Context, position: int) -> None:
        player = ctx.voice_client
        if player is None or player.current is None:
            return await ctx.fail("nothing playing")
        await player.seek(max(player.position - position * 1000, 0))
        await ctx.success(f"-{position}s")

    @hybrid(name="disconnect", aliases=["dc", "leave"], guild_only=True)
    async def disconnect(self, ctx: Context) -> None:
        if ctx.voice_client:
            await ctx.voice_client.disconnect(force=True)
        self.queues.pop(ctx.guild.id, None)
        await ctx.success("disconnected")

    @group(name="preset", description="Audio filter presets", invoke_without_command=True, guild_only=True)
    async def preset(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @preset.command(name="active", description="Show the active audio preset")
    async def preset_active(self, ctx: Context) -> None:
        active = self._queue(ctx.guild.id).active_preset
        if not active:
            return await ctx.info("no active preset")
        await ctx.info(f"active: **{active}**")


for _preset_name in Music.PRESETS:
    @Music.preset.command(name=_preset_name, description=f"Toggle the {_preset_name} audio preset")
    @describe(setting="on or off")
    async def _preset_cmd(self, ctx: Context, setting: str | None = None, *, _name: str = _preset_name) -> None:
        await self._set_preset(ctx, _name, setting)

    _preset_cmd.__name__ = f"preset_{_preset_name.replace('8d', 'eightd')}"


async def setup(bot: Bleed):
    if not music_enabled:
        return
    await bot.add_cog(Music(bot))
