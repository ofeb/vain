from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import TYPE_CHECKING

import discord

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.managers.values import color, music as nl, music_enabled

from .events import MusicEvents



def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def c2(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed

def panel_embed(
    *,
    color: int | None = None,
    title: str | None = None,
    author: str | None = None,
    author_icon: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    timestamp: bool = True,
    thumbnail: str | None = None,
    url: str | None = None,
) -> discord.Embed:
    description = compose(
        body(*(lines or [])),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description or None, url=url)
    if title:
        embed.title = title
    if author:
        if author_icon:
            embed.set_author(name=author, icon_url=author_icon)
        else:
            embed.set_author(name=author)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed



log = logging.getLogger("Vain.music")

_SEARCH_PREFIX_RE = re.compile(r"^[a-z]+search:", re.I)
_URL_HINT_RE = re.compile(
    r"^(?:www\.|(?:open\.)?spotify\.com/|(?:music\.)?youtube\.com/|youtu\.be/|"
    r"soundcloud\.com/|(?:www\.)?deezer\.com/|music\.apple\.com/)",
    re.I,
)

if TYPE_CHECKING:
    from core.vain import Vain

try:
    import lava_lyra as lyra
    from lava_lyra.enums import URLRegex
    from lava_lyra.exceptions import (
        NoNodesAvailable,
        NodeCreationError,
        NodeRestException,
        TrackLoadError,
    )

    class VainPlayer(lyra.Player):
        async def play(
            self,
            track,
            *,
            start: int = 0,
            end: int = 0,
            ignore_if_playing: bool = False,
        ):
            if track.original is None and track.track_id:
                track.original = track
            try:
                return await super().play(
                    track,
                    start=start,
                    end=end,
                    ignore_if_playing=ignore_if_playing,
                )
            except NodeRestException as exc:
                if "Invalid query parameters" not in str(exc) or not track.track_id:
                    raise
                log.debug("retrying play with minimal payload after: %s", exc)
                self._current = track
                await self._node.send(
                    method="PATCH",
                    path=self._player_endpoint_uri,
                    guild_id=self._guild.id,
                    data={"track": {"encoded": track.track_id}, "position": start},
                )
                return track

    HAS_LYRA = True
except ImportError:
    HAS_LYRA = False
    lyra = None
    URLRegex = None
    VainPlayer = None
    NoNodesAvailable = NodeCreationError = NodeRestException = TrackLoadError = Exception


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

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self.queues: dict[int, GuildQueue] = {}
        self._node = None
        self._node_lock = asyncio.Lock()

    async def _connect_node(self) -> bool:
        if not music_enabled or not HAS_LYRA:
            return False
        if self._node is not None and self._node.is_connected:
            return True
        if not self.bot.is_ready():
            return False

        async with self._node_lock:
            if self._node is not None and self._node.is_connected:
                return True

            try:
                node = lyra.NodePool.get_node(identifier=nl.identifier())
            except NoNodesAvailable:
                node = None
            else:
                if not node.is_connected:
                    await node.connect()
                self._node = node
                log.info("nodelink connected (existing node)")
                return True

            log.info("connecting to nodelink at %s:%s", nl.host, nl.port)
            try:
                self._node = await asyncio.wait_for(
                    lyra.NodePool.create_node(
                        bot=self.bot,
                        host=nl.host,
                        port=nl.port,
                        password=nl.password,
                        identifier=nl.identifier(),
                        fallback=True,
                        secure=False,
                    ),
                    timeout=15,
                )
                log.info("nodelink connected")
                return True
            except asyncio.TimeoutError:
                log.warning("nodelink connection timed out after 15s")
            except NodeCreationError as e:
                if "already exists" in str(e).lower():
                    try:
                        self._node = lyra.NodePool.get_node(identifier=nl.identifier())
                        if not self._node.is_connected:
                            await self._node.connect()
                        log.info("nodelink connected (existing node)")
                        return True
                    except Exception as inner:
                        log.warning("nodelink reconnect failed: %s", inner)
                else:
                    log.warning("nodelink connection failed: %s", e)
            except Exception as e:
                log.warning("nodelink connection failed: %s", e)

            self._node = None
            return False

    def _queue(self, guild_id: int) -> GuildQueue:
        return self.queues.setdefault(guild_id, GuildQueue())

    async def _ensure_voice(self, ctx: Context) -> bool:
        if ctx.guild is None:
            await ctx.warn("server only")
            return False
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("join a voice channel first")
            return False
        if ctx.voice_client and ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.warn("i'm already in another voice channel")
            return False
        return True

    async def _player(self, ctx: Context):
        if not HAS_LYRA or not await self._connect_node():
            await ctx.warn("nodelink isn't running")
            return None
        if not await self._ensure_voice(ctx):
            return None
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect(cls=VainPlayer, self_deaf=True)
        return ctx.voice_client

    def _normalize_query(self, query: str) -> str:
        query = query.strip()
        if not query:
            return query
        if query.startswith("//"):
            return f"https:{query}"
        if _URL_HINT_RE.match(query) and not query.startswith(("http://", "https://", "spotify:")):
            return f"https://{query}"
        return query

    def _parse_play_flags(self, query: str, *, next: bool) -> tuple[str, bool]:
        q = query.strip()
        if q.lower().startswith("--next "):
            return q[7:].strip(), True
        if q.lower().endswith(" --next"):
            return q[:-7].strip(), True
        return q, next

    def _is_direct_query(self, query: str) -> bool:
        query = self._normalize_query(query)
        if not query:
            return False
        if query.startswith(("http://", "https://", "spotify:")):
            return True
        if _SEARCH_PREFIX_RE.match(query):
            return True
        if HAS_LYRA and URLRegex is not None:
            for pattern in (
                URLRegex.BASE_URL,
                URLRegex.SPOTIFY_URL,
                URLRegex.YOUTUBE_URL,
                URLRegex.YOUTUBE_PLAYLIST_URL,
                URLRegex.SOUNDCLOUD_URL,
                URLRegex.SOUNDCLOUD_PLAYLIST_URL,
                URLRegex.AM_URL,
                URLRegex.BILIBILI_URL,
            ):
                if pattern.match(query) or pattern.search(query):
                    return True
        head = query.split(" ", 1)[0]
        return ":" in head and head.lower().endswith("search")

    @staticmethod
    def _track_source(track) -> str:
        track_type = getattr(track, "track_type", None)
        if track_type is not None:
            value = track_type.value if hasattr(track_type, "value") else str(track_type)
            if value and value.lower() not in {"other"}:
                return value.lower()
        info = getattr(track, "info", None) or {}
        return str(info.get("sourceName", "")).lower()

    def _score_track(self, query: str, track) -> float:
        q = query.lower().strip()
        title = (track.title or "").lower()
        author = (track.author or "").lower()
        combined = f"{title} {author}".strip()
        if not q:
            return 0.0

        score = 0.0
        if q == title or q == combined:
            score += 200
        elif q in combined or combined in q:
            score += 120

        q_tokens = [t for t in q.split() if len(t) >= 2]
        if not q_tokens:
            return score

        hits = sum(1 for token in q_tokens if token in title or token in author)
        score += hits * 15
        if hits == len(q_tokens):
            score += 40

        source = self._track_source(track)
        if source == "deezer":
            score += 25
        elif source == "spotify":
            score -= 10

        return score

    def _pick_track(self, results, pick_query: str | None = None):
        if not results:
            return None
        tracks = results.tracks if hasattr(results, "tracks") else results
        if not tracks:
            return None
        if not pick_query or len(tracks) == 1:
            return tracks[0]
        ranked = sorted(
            tracks,
            key=lambda track: self._score_track(pick_query, track),
            reverse=True,
        )
        best = ranked[0]
        if self._score_track(pick_query, best) <= 0:
            return tracks[0]
        return best

    async def _load_query(self, query: str, *, pick_query: str | None = None):
        try:
            results = await self._node.get_tracks(query)
        except TrackLoadError as e:
            log.debug("track load failed for %r: %s", query, e)
            return None
        except Exception as e:
            log.debug("unexpected load error for %r: %s", query, e)
            return None
        return self._pick_track(results, pick_query)

    async def _resolve_deezer_uri(self, track):
        uri = (getattr(track, "uri", None) or "").strip()
        if "deezer.com/track/" not in uri:
            return track
        direct = await self._load_query(uri)
        if direct:
            log.debug("reloaded deezer track from %s", uri)
            return direct
        return track

    async def _finalize_track(self, track, *, query: str | None = None):
        source = self._track_source(track)
        if source == "deezer":
            return await self._resolve_deezer_uri(track)
        if source == "spotify" and query:
            fallback = await self._load_query(
                f"dzsearch:{track.title} {track.author}",
                pick_query=query,
            )
            if fallback:
                return await self._resolve_deezer_uri(fallback)
        return track

    async def _first_track(self, query: str):
        if self._node is None:
            return None
        query = self._normalize_query(query.strip())
        if not query:
            return None

        if self._is_direct_query(query):
            track = await self._load_query(query)
            if track:
                return await self._finalize_track(track, query=query)
            return None

        for source in nl.search_sources:
            search = f"{source}:{query}"
            log.info("searching %s for %r", source, query)
            track = await self._load_query(search, pick_query=query)
            if track is None:
                continue
            track = await self._finalize_track(track, query=query)
            log.info(
                "resolved %r via %s -> %s — %s (%s)",
                query,
                source,
                track.title,
                track.author,
                track.uri,
            )
            return track

        log.info(
            "no results for %r (tried %s)",
            query,
            ", ".join(nl.search_sources),
        )
        return None

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
        try:
            await player.play(track)
        except NodeRestException:
            log.exception("auto-advance failed in guild %s", guild_id)
            state.current = None
            return
        if state.active_preset:
            await self._apply_preset(player, state.active_preset)

    async def _set_preset(self, ctx: Context, name: str, setting: str | None) -> None:
        player = ctx.voice_client
        if player is None:
            return await ctx.warn("nothing playing")
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
    async def play(self, ctx, *, query: str, next: bool = False) -> None:
        query, play_next = self._parse_play_flags(query, next=next)
        player = await self._player(ctx)
        if player is None:
            return
        track = await self._first_track(query)
        if track is None:
            return await ctx.warn("no results")

        state = self._queue(ctx.guild.id)

        try:
            if player.is_playing or player.current:
                if play_next:
                    state.tracks.insert(0, track)
                else:
                    state.tracks.append(track)
                return await ctx.send(embed=c2(
                    title="queued",
                    message=f"**{track.title}** — {track.author}",
                    color=color.base,
                    timestamp=False,
                ))

            state.current = track
            await player.play(track)
            if state.active_preset:
                await self._apply_preset(player, state.active_preset)
            await ctx.send(embed=c2(
                title="now playing",
                message=f"**{track.title}** — {track.author}",
                color=color.base,
                timestamp=False,
            ))
        except NodeRestException as exc:
            log.error("play failed for %r: %s", query, exc)
            return await ctx.fail(f"failed to play track: {exc}")

    @hybrid(name="queue", description="View all tracks queued", group=True, invoke_without_command=True, guild_only=True)
    async def queue(self, ctx) -> None:
        if ctx.invoked_subcommand is None:
            await self.queue_view(ctx)

    @queue.command(name="view", description="View all tracks queued", aliases=["list"])
    async def queue_view(self, ctx) -> None:
        state = self._queue(ctx.guild.id)
        if not state.tracks and not state.current:
            return await ctx.warn("queue is empty")
        lines = [f"**now:** {state.current.title}"] if state.current else []
        lines.extend(f"`{i}.` **{t.title}** — {t.author}" for i, t in enumerate(state.tracks[:15], 1))
        await ctx.send(embed=panel_embed(
            title=f"queue ({len(state.tracks)})",
            color=color.base,
            lines=lines,
            timestamp=False,
        ))

    @queue.command(name="remove", description="Remove a track from the queue")
    @describe(position="Track position in the queue")
    async def queue_remove(self, ctx, position: int) -> None:
        state = self._queue(ctx.guild.id)
        if position < 1 or position > len(state.tracks):
            return await ctx.warn(f"invalid position ({len(state.tracks)} tracks)")
        track = state.tracks.pop(position - 1)
        await ctx.success(f"removed **{track.title}**")

    @queue.command(name="shuffle", description="Shuffle the queue")
    async def queue_shuffle(self, ctx) -> None:
        state = self._queue(ctx.guild.id)
        if len(state.tracks) < 2:
            return await ctx.warn("not enough tracks")
        random.shuffle(state.tracks)
        await ctx.success("shuffled")

    @queue.command(name="empty", description="Empty the queue", aliases=["clear"])
    async def queue_empty(self, ctx) -> None:
        self._queue(ctx.guild.id).tracks.clear()
        await ctx.success("cleared queue")

    @queue.command(name="move", description="Move a track to a different position in the queue")
    @describe(position="Current position", new_position="New position")
    async def queue_move(self, ctx, position: int, new_position: int) -> None:
        state = self._queue(ctx.guild.id)
        if not (1 <= position <= len(state.tracks) and 1 <= new_position <= len(state.tracks)):
            return await ctx.warn("invalid position")
        track = state.tracks.pop(position - 1)
        state.tracks.insert(new_position - 1, track)
        await ctx.success(f"moved **{track.title}** to `{new_position}`")

    @hybrid(name="skip", guild_only=True)
    async def skip(self, ctx) -> None:
        player = ctx.voice_client
        if player is None or not player.is_playing:
            return await ctx.warn("nothing playing")
        await player.stop()
        await self._play_next(ctx.guild.id, player)
        await ctx.success("skipped")

    @hybrid(name="pause", guild_only=True)
    async def pause(self, ctx) -> None:
        player = ctx.voice_client
        if player is None or not player.is_playing:
            return await ctx.warn("nothing playing")
        await player.pause()
        await ctx.success("paused")

    @hybrid(name="resume", guild_only=True)
    async def resume(self, ctx) -> None:
        player = ctx.voice_client
        if player is None or not player.is_paused:
            return await ctx.warn("not paused")
        await player.resume()
        await ctx.success("resumed")

    @hybrid(name="shuffle", guild_only=True)
    async def shuffle(self, ctx) -> None:
        state = self._queue(ctx.guild.id)
        state.loop_queue = not state.loop_queue
        await ctx.success(f"queue loop **{'on' if state.loop_queue else 'off'}**")

    @hybrid(name="repeat", guild_only=True)
    @describe(option="on or off")
    async def repeat(self, ctx, option: str | None = None) -> None:
        state = self._queue(ctx.guild.id)
        state.loop = (not state.loop) if option is None else option.lower() in {"on", "true", "yes", "enable"}
        await ctx.success(f"repeat **{'on' if state.loop else 'off'}**")

    @hybrid(name="volume", guild_only=True)
    @describe(volume="Volume from 0 to 200")
    async def volume(self, ctx, volume: int) -> None:
        if not 0 <= volume <= 200:
            return await ctx.warn("volume must be 0–200")
        player = ctx.voice_client
        if player is None:
            return await ctx.warn("nothing playing")
        await player.set_volume(volume)
        self._queue(ctx.guild.id).volume = volume
        await ctx.success(f"volume **{volume}%**")

    @hybrid(name="fastforward", guild_only=True)
    @describe(position="Seconds to fast forward")
    async def fastforward(self, ctx, position: int) -> None:
        player = ctx.voice_client
        if player is None or player.current is None:
            return await ctx.warn("nothing playing")
        await player.seek(min(player.position + position * 1000, player.current.length))
        await ctx.success(f"+{position}s")

    @hybrid(name="rewind", guild_only=True)
    @describe(position="Seconds to rewind")
    async def rewind(self, ctx, position: int) -> None:
        player = ctx.voice_client
        if player is None or player.current is None:
            return await ctx.warn("nothing playing")
        await player.seek(max(player.position - position * 1000, 0))
        await ctx.success(f"-{position}s")

    @hybrid(name="disconnect", aliases=["dc", "leave"], guild_only=True)
    async def disconnect(self, ctx) -> None:
        if ctx.voice_client:
            await ctx.voice_client.disconnect(force=True)
        self.queues.pop(ctx.guild.id, None)
        await ctx.success("disconnected")

    @hybrid(name="preset", description="Audio filter presets", group=True, invoke_without_command=True, guild_only=True)
    async def preset(self, ctx) -> None:
        await ctx.send_help(ctx.command)

    @preset.command(name="active", description="Show the active audio preset")
    async def preset_active(self, ctx) -> None:
        active = self._queue(ctx.guild.id).active_preset
        if not active:
            return await ctx.info("no active preset")
        await ctx.info(f"active: **{active}**")


for _preset_name in Music.PRESETS:
    @Music.preset.command(name=_preset_name, description=f"Toggle the {_preset_name} audio preset")
    @describe(setting="on or off")
    async def _preset_cmd(self, ctx, setting: str | None = None, *, _name: str = _preset_name) -> None:
        await self._set_preset(ctx, _name, setting)

    _preset_cmd.__name__ = f"preset_{_preset_name.replace('8d', 'eightd')}"


async def setup(bot: Vain):
    if not music_enabled:
        return
    await bot.add_cog(Music(bot))
