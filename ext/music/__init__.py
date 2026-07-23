from __future__ import annotations

import asyncio
import io
import logging
import random
import re
from typing import TYPE_CHECKING

import discord

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from config import color, music as nl, music_enabled

from .events import MusicEvents
from .panel import (
    MusicControlView,
    fetch_image_bytes,
    render_now_playing_card,
)



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


MUSIC_LOG_CHANNEL_ID = 1523010752045256724

_SEARCH_PREFIX_RE = re.compile(r"^[a-z]+search:", re.I)
_URL_HINT_RE = re.compile(
    r"^(?:www\.|(?:open\.)?spotify\.com/|(?:music\.)?youtube\.com/|youtu\.be/|"
    r"soundcloud\.com/|(?:www\.)?deezer\.com/|music\.apple\.com/|"
    r"music\.youtube\.com/)",
    re.I,
)
_PLATFORM_RE = re.compile(
    r"(?:open\.)?spotify\.com/|"
    r"(?:www\.)?deezer\.com/|"
    r"music\.apple\.com/|"
    r"soundcloud\.com/|"
    r"music\.youtube\.com/|"
    r"(?:www\.)?youtube\.com/|"
    r"youtu\.be/",
    re.I,
)
_VIDEO_NOISE_RE = re.compile(
    r"\b(official\s*(music\s*)?video|official\s*video|music\s*video|vevo|"
    r"lyric\s*video|visualizer|mv|4k|8k|hd|remaster(ed)?)\b",
    re.I,
)
_CLEAN_PARENS_RE = re.compile(
    r"\[.*?\]|\(from .*?\)|\(official.*?\)|\(feat\..*?\)|\(ft\..*?\)|"
    r"\(explicit\)|\(audio\)|\(lyrics?\)|\(official\s*visualizer\)|"
    r"\(official\s*music\s*video\)|\(official\s*audio\)|\(visualizer\)",
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
        """Player bound to our nodelink node with a hard play path that actually works."""

        def __init__(self, client, channel, *, node=None):
            if node is None:
                node = _resolve_pool_node()
            super().__init__(client, channel, node=node)
            self._sync_endpoint()
            # Ensure this player is tracked on the node immediately
            try:
                self._node._players[self._guild.id] = self  # type: ignore[attr-defined]
            except Exception:
                pass

        def _sync_endpoint(self) -> None:
            sid = getattr(self._node, "_session_id", None)
            if sid:
                self._player_endpoint_uri = f"sessions/{sid}/players"
            else:
                # Keep a sentinel so we never silently hit sessions/None/...
                self._player_endpoint_uri = "sessions/pending/players"

        def voice_ready(self) -> bool:
            vs = getattr(self, "_voice_state", None) or {}
            if "sessionId" not in vs or "event" not in vs:
                return False
            event = vs.get("event")
            if not isinstance(event, dict):
                return False
            return bool(event.get("token") and event.get("endpoint") and vs.get("sessionId"))

        def _voice_payload(self) -> dict | None:
            """Lavalink voice object (channelId required when updating)."""
            vs = getattr(self, "_voice_state", None) or {}
            event = vs.get("event")
            if not isinstance(event, dict):
                return None
            token = event.get("token")
            endpoint = event.get("endpoint")
            session_id = vs.get("sessionId")
            if not token or not endpoint or not session_id:
                return None
            # Discord sometimes prefixes endpoint with wss:// — strip it
            endpoint = str(endpoint).removeprefix("wss://").removeprefix("ws://")
            data = {
                "token": str(token),
                "endpoint": endpoint,
                "sessionId": str(session_id),
            }
            if self.channel is not None:
                data["channelId"] = str(self.channel.id)
            return data

        async def _force_voice_update(self) -> bool:
            """Push voice state to Lavalink/NodeLink (creates player if missing)."""
            voice = self._voice_payload()
            if not voice:
                return False
            if not getattr(self._node, "_session_id", None):
                return False
            self._sync_endpoint()
            try:
                await self._node.send(
                    method="PATCH",
                    path=self._player_endpoint_uri,
                    guild_id=self._guild.id,
                    data={"voice": voice},
                )
                return True
            except Exception as exc:
                msg = str(exc).lower()
                # 404 player not found on some NodeLink builds: retry with PUT
                if "404" in msg or "player not found" in msg or "session" in msg:
                    try:
                        self._sync_endpoint()
                        await self._node.send(
                            method="PUT",
                            path=self._player_endpoint_uri,
                            guild_id=self._guild.id,
                            data={"voice": voice},
                        )
                        return True
                    except Exception as exc2:
                        log.warning("force voice update failed: %s / put: %s", exc, exc2)
                        return False
                log.warning("force voice update failed: %s", exc)
                return False

        async def wait_until_ready(self, *, timeout: float = 12.0) -> bool:
            """Wait for node session + Discord voice credentials.

            Voice PATCH success is nice-to-have; play() will create the player
            atomically with track+voice. Returning True once voice_ready avoids
            false 'handshake incomplete' when NodeLink 404s voice-only updates.
            """
            self._sync_endpoint()
            deadline = asyncio.get_event_loop().time() + timeout
            voice_ok = False
            while asyncio.get_event_loop().time() < deadline:
                node = self._node
                if (
                    node is not None
                    and getattr(node, "_available", False)
                    and getattr(node, "_session_id", None)
                    and self.voice_ready()
                ):
                    self._sync_endpoint()
                    voice_ok = True
                    # Best-effort create player early; failure is OK
                    await self._force_voice_update()
                    return True
                await asyncio.sleep(0.15)
            self._sync_endpoint()
            if self.voice_ready() and getattr(self._node, "_session_id", None):
                await self._force_voice_update()
                return True
            log.warning(
                "player not ready guild=%s avail=%s session=%s voice_keys=%s voice_ok=%s",
                getattr(self._guild, "id", None),
                getattr(self._node, "_available", None),
                bool(getattr(self._node, "_session_id", None)),
                list((getattr(self, "_voice_state", None) or {}).keys()),
                voice_ok,
            )
            return False

        async def on_voice_server_update(self, data) -> None:
            self._voice_state.update({"event": data})
            if self.voice_ready():
                await self._force_voice_update()

        async def on_voice_state_update(self, data) -> None:
            sid = data.get("session_id")
            if sid:
                self._voice_state.update({"sessionId": sid})
            channel_id = data.get("channel_id")
            if not channel_id:
                # Bot left voice — don't hard-disconnect mid-handshake
                return
            channel = self.guild.get_channel(int(channel_id))
            if channel is None:
                return
            self.channel = channel
            self._is_connected = True
            try:
                self._node._players[self._guild.id] = self  # type: ignore[attr-defined]
            except Exception:
                pass
            if self.voice_ready():
                await self._force_voice_update()

        async def _resolve_encoded(self, track) -> str:
            """Return a playable encoded track id (resolve Spotify/Apple via YT if needed)."""
            encoded = _safe_attr(track, "track_id")
            original = _safe_attr(track, "original")
            search_type = _safe_attr(track, "_search_type")
            info = _safe_attr(track, "info") or {}
            if not isinstance(info, dict):
                info = {}
            source = str(info.get("sourceName", "") or "").lower().replace(" ", "")

            
            playable_sources = {
                "youtube",
                "youtubemusic",
                "ytmusic",
                "soundcloud",
                "http",
                "local",
                "bandcamp",
                "vimeo",
                "twitch",
            }
            if encoded and source in playable_sources:
                return str(encoded)
            if encoded and original is track:
                return str(encoded)
            if encoded and original is not None and original is not track:
                oid = _safe_attr(original, "track_id")
                if oid:
                    return str(oid)
            
            if encoded and source not in {"spotify", "applemusic", "deezer"}:
                return str(encoded)

            
            queries: list[str] = []
            isrc = _safe_attr(track, "isrc")
            st = _safe_attr(search_type, "value") if search_type is not None else None
            if not st and isinstance(search_type, str):
                st = search_type
            st = (st or "ytmsearch").lower()
            if st not in {"ytsearch", "ytmsearch", "scsearch", "spsearch", "amsearch"}:
                st = "ytmsearch"
            if isrc:
                queries.append(f"{st}:{isrc}")
                queries.append(f"ytmsearch:{isrc}")
            title = _safe_attr(track, "title") or ""
            author = _safe_attr(track, "author") or ""
            if title and author:
                queries.append(f"ytmsearch:{title} - {author}")
                queries.append(f"ytsearch:{title} {author} audio")
            elif title:
                queries.append(f"ytmsearch:{title}")
                queries.append(f"ytsearch:{title}")

            for q in queries:
                try:
                    results = await self._node.get_tracks(q, search_type=None)
                except TypeError:
                    try:
                        results = await self._node.get_tracks(q)
                    except Exception:
                        continue
                except Exception:
                    continue
                if not results:
                    continue
                tracks = results.tracks if hasattr(results, "tracks") else results
                if not tracks:
                    continue
                found = tracks[0]
                found_id = _safe_attr(found, "track_id")
                if not found_id:
                    continue
                try:
                    track.original = found
                    track.track_id = found_id
                except Exception:
                    pass
                return str(found_id)

            if encoded:
                return str(encoded)
            raise TrackLoadError("No equivalent track was able to be found.")

        def _play_payloads(
            self,
            encoded: str,
            voice: dict,
            *,
            start: int = 0,
            end: int = 0,
            volume: int = 100,
        ) -> list[dict]:
            """Build candidate play payloads (v4 track object + legacy encodedTrack)."""
            pos = int(start or 0)
            payloads: list[dict] = []

            # Lavalink v4 / NodeLink preferred form
            modern: dict = {
                "track": {"encoded": encoded},
                "position": pos,
                "paused": False,
                "volume": int(volume),
                "voice": voice,
            }
            if end and end > 0:
                modern["endTime"] = int(end)
            payloads.append(modern)

            # Legacy Lavalink form (some forks still expect this)
            legacy: dict = {
                "encodedTrack": encoded,
                "position": str(pos),
                "paused": False,
                "volume": int(volume),
                "voice": voice,
            }
            if end and end > 0:
                legacy["endTime"] = str(int(end))
            payloads.append(legacy)

            # Also try modern without volume (some strict validators)
            modern_min = {
                "track": {"encoded": encoded},
                "voice": voice,
                "paused": False,
            }
            payloads.append(modern_min)
            return payloads

        async def _send_play_request(
            self,
            data: dict,
            *,
            method: str = "PATCH",
            no_replace: bool | None = False,
        ):
            self._sync_endpoint()
            query = None
            if no_replace is not None:
                query = f"noReplace={str(bool(no_replace)).lower()}"
            return await self._node.send(
                method=method,
                path=self._player_endpoint_uri,
                guild_id=self._guild.id,
                data=data,
                query=query,
            )

        async def play(
            self,
            track,
            *,
            start: int = 0,
            end: int = 0,
            ignore_if_playing: bool = False,
        ):
            """Hard play: always send voice + track together; recover from 404 Player not found."""
            ready = await self.wait_until_ready(timeout=15.0)
            if not ready:
                for _ in range(20):
                    if self.voice_ready() and getattr(self._node, "_session_id", None):
                        break
                    await asyncio.sleep(0.25)
                self._sync_endpoint()
                if not self.voice_ready():
                    log.error("play aborted: voice not ready guild=%s", self._guild.id)
                    raise RuntimeError("Voice connection is not ready for playback")
                if not getattr(self._node, "_session_id", None):
                    log.error("play aborted: node has no session guild=%s", self._guild.id)
                    raise RuntimeError("Music node has no active session")

            self._sync_endpoint()
            try:
                self._node._players[self._guild.id] = self  # type: ignore[attr-defined]
            except Exception:
                pass

            # Best-effort pre-create; play payload will create if this 404s
            await self._force_voice_update()

            encoded = await self._resolve_encoded(track)
            voice = self._voice_payload()
            if not voice:
                raise RuntimeError("Voice credentials incomplete for playback")

            volume = int(getattr(self, "_volume", 100) or 100)
            payloads = self._play_payloads(
                encoded,
                voice,
                start=start,
                end=end,
                volume=volume,
            )

            self._current = track
            last_exc: Exception | None = None
            # Prefer replace so a missing player is created (noReplace=true can 404)
            attempts: list[tuple[str, dict, bool | None]] = []
            for data in payloads:
                attempts.append(("PATCH", data, bool(ignore_if_playing)))
                attempts.append(("PATCH", data, False))
                attempts.append(("PUT", data, False))
                attempts.append(("PATCH", data, None))

            for round_i in range(3):
                self._sync_endpoint()
                if not getattr(self._node, "_session_id", None):
                    await asyncio.sleep(0.5)
                    continue

                for method, data, nr in attempts:
                    try:
                        await self._send_play_request(
                            data,
                            method=method,
                            no_replace=nr,
                        )
                        log.info(
                            "playing %r by %r encoded=%s… guild=%s method=%s nr=%s round=%s",
                            getattr(track, "title", "?"),
                            getattr(track, "author", "?"),
                            str(encoded)[:18],
                            self._guild.id,
                            method,
                            nr,
                            round_i + 1,
                        )
                        return track
                    except Exception as exc:
                        last_exc = exc
                        msg = str(exc).lower()
                        log.warning(
                            "play %s failed guild=%s round=%s: %s",
                            method,
                            self._guild.id,
                            round_i + 1,
                            exc,
                        )
                        if "session not found" in msg:
                            # Session died — wait for node reconnect
                            await asyncio.sleep(1.2)
                            self._sync_endpoint()
                            break

                await asyncio.sleep(0.6 + round_i * 0.4)
                await self._force_voice_update()

            log.error(
                "play exhausted retries guild=%s last=%s endpoint=%s session=%s",
                self._guild.id,
                last_exc,
                self._player_endpoint_uri,
                bool(getattr(self._node, "_session_id", None)),
            )
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("Failed to start playback on music node")

    HAS_LYRA = True
except ImportError:
    HAS_LYRA = False
    lyra = None
    URLRegex = None
    VainPlayer = None
    NoNodesAvailable = NodeCreationError = NodeRestException = TrackLoadError = Exception


def _resolve_pool_node():
    """Pick a lava_lyra node for players — prefer our identifier, then any available."""
    if not HAS_LYRA:
        raise NoNodesAvailable("lava_lyra is not installed")
    ident = nl.identifier()
    
    try:
        return lyra.NodePool.get_node(identifier=ident)
    except (NoNodesAvailable, KeyError):
        pass
    
    try:
        return lyra.NodePool.get_node()
    except NoNodesAvailable:
        pass
    
    nodes = getattr(lyra.NodePool, "_nodes", {}) or {}
    if ident in nodes:
        return nodes[ident]
    if nodes:
        return next(iter(nodes.values()))
    raise NoNodesAvailable("There are no nodes available.")


def _node_ready(node) -> bool:
    if node is None:
        return False
    available = bool(getattr(node, "_available", False))
    connected = bool(getattr(node, "is_connected", False))
    if callable(connected):
        try:
            connected = bool(node.is_connected)
        except Exception:
            connected = False
    session = getattr(node, "_session_id", None)
    return available and connected and bool(session)


def _safe_attr(obj, name: str, default=None):
    """Read attrs on lava_lyra Track safely (slots raise if unset; getattr default can fail)."""
    try:
        return object.__getattribute__(obj, name)
    except Exception:
        try:
            return getattr(obj, name, default)
        except Exception:
            return default


class GuildQueue:
    __slots__ = (
        "tracks",
        "current",
        "loop",
        "loop_queue",
        "volume",
        "active_preset",
        "text_channel_id",
        "control_message_id",
        "play_message_id",
        "session_started_at",
    )

    def __init__(self) -> None:
        self.tracks: list = []
        self.current = None
        self.loop = False
        self.loop_queue = False
        self.volume = 100
        self.active_preset: str | None = None
        self.text_channel_id: int | None = None
        self.control_message_id: int | None = None
        self.play_message_id: int | None = None
        self.session_started_at: float = 0.0


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
        
        self._track_meta: dict[str, dict] = {}

    async def music_log(
        self,
        *,
        title: str,
        description: str,
        guild: discord.Guild | None = None,
        user: discord.abc.User | None = None,
        error: bool = False,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        """Post a music diagnostic embed to the music log channel."""
        try:
            channel = self.bot.get_channel(MUSIC_LOG_CHANNEL_ID)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(MUSIC_LOG_CHANNEL_ID)
                except Exception as exc:
                    log.debug("music log channel fetch failed: %s", exc)
                    return
            if channel is None:
                return

            emb = discord.Embed(
                title=title[:256],
                description=(description or "")[:4000],
                color=0xED4245 if error else color.base,
                timestamp=discord.utils.utcnow(),
            )
            if guild is not None:
                emb.add_field(
                    name="Guild",
                    value=f"{guild.name}\n`{guild.id}`",
                    inline=True,
                )
            if user is not None:
                emb.add_field(
                    name="User",
                    value=f"{user} (`{user.id}`)",
                    inline=True,
                )
            for name, value in fields or []:
                emb.add_field(name=str(name)[:256], value=str(value)[:1024], inline=False)
            emb.set_footer(text="music diagnostics")
            await channel.send(embed=emb)
        except Exception:
            log.exception("music_log send failed")

    async def _wait_node_ready(self, node, *, timeout: float = 10.0) -> bool:
        """Wait until the node is available for get_tracks / Player init."""
        if node is None:
            return False
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if _node_ready(node):
                return True
            
            if getattr(node, "is_connected", False) and getattr(node, "_session_id", None):
                
                try:
                    node._available = True  # type: ignore[attr-defined]
                except Exception:
                    pass
                if _node_ready(node):
                    return True
            await asyncio.sleep(0.1)
        return _node_ready(node)

    def _pool_node_raw(self, identifier: str | None = None):
        """Fetch node from pool dict without requiring _available."""
        nodes = getattr(lyra.NodePool, "_nodes", {}) or {}
        if identifier and identifier in nodes:
            return nodes[identifier]
        if identifier is None and nodes:
            return next(iter(nodes.values()))
        return None

    async def _connect_node(self) -> bool:
        if not music_enabled or not HAS_LYRA:
            return False
        if _node_ready(self._node):
            return True
        if not self.bot.is_ready():
            
            pass

        async with self._node_lock:
            if _node_ready(self._node):
                return True

            ident = nl.identifier()
            node = None

            
            try:
                node = lyra.NodePool.get_node(identifier=ident)
            except (NoNodesAvailable, KeyError):
                node = None

            
            if node is None:
                node = self._pool_node_raw(ident)

            if node is not None:
                try:
                    if not getattr(node, "is_connected", False):
                        await node.connect(reconnect=True)
                    elif not getattr(node, "_available", False):
                        
                        try:
                            await node.connect(reconnect=True)
                        except Exception:
                            pass
                except Exception as exc:
                    log.warning("nodelink reconnect failed: %s", exc)
                    node = None
                else:
                    if await self._wait_node_ready(node):
                        self._node = node
                        log.info("nodelink ready (existing node %s)", ident)
                        return True

            
            log.info("connecting to nodelink at %s:%s", nl.host, nl.port)
            try:
                node = await asyncio.wait_for(
                    lyra.NodePool.create_node(
                        bot=self.bot,
                        host=nl.host,
                        port=nl.port,
                        password=nl.password,
                        identifier=ident,
                        fallback=True,
                        secure=False,
                        connect_timeout=15.0,
                        total_timeout=30.0,
                    ),
                    timeout=20,
                )
            except asyncio.TimeoutError:
                log.warning("nodelink connection timed out after 20s")
                node = None
            except NodeCreationError as e:
                if "already exists" in str(e).lower():
                    node = self._pool_node_raw(ident)
                    if node is not None:
                        try:
                            if not getattr(node, "is_connected", False):
                                await node.connect(reconnect=True)
                        except Exception as inner:
                            log.warning("nodelink reconnect after exists failed: %s", inner)
                else:
                    log.warning("nodelink connection failed: %s", e)
                    node = None
            except Exception as e:
                log.warning("nodelink connection failed: %s", e)
                node = None

            if node is not None and await self._wait_node_ready(node, timeout=12.0):
                self._node = node
                log.info("nodelink ready at %s:%s", nl.host, nl.port)
                return True

            
            try:
                node = lyra.NodePool.get_node()
                self._node = node
                log.info("nodelink ready (fallback pool node)")
                return True
            except NoNodesAvailable:
                pass

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
        if not HAS_LYRA:
            await self.music_log(
                title="Play blocked — library missing",
                description="`lava_lyra` is not installed on this process.",
                guild=ctx.guild,
                user=ctx.author,
                error=True,
            )
            await ctx.warn("music library is not installed")
            return None
        if not await self._connect_node():
            await self.music_log(
                title="Play blocked — node offline",
                description=(
                    f"Could not connect to nodelink/lavalink at "
                    f"`{nl.host}:{nl.port}`."
                ),
                guild=ctx.guild,
                user=ctx.author,
                error=True,
                fields=[
                    ("Host", f"`{nl.host}:{nl.port}`"),
                    ("Identifier", f"`{nl.identifier()}`"),
                ],
            )
            await ctx.warn(
                f"nodelink isn't running (expected `{nl.host}:{nl.port}`). "
                "start nodelink/lavalink and try again."
            )
            return None
        if not await self._ensure_voice(ctx):
            await self.music_log(
                title="Play blocked — voice check failed",
                description=(
                    "User not in a voice channel, or bot is already in another channel."
                ),
                guild=ctx.guild,
                user=ctx.author,
                error=True,
            )
            return None
        if not ctx.voice_client:
            try:
                _resolve_pool_node()
                await ctx.author.voice.channel.connect(
                    cls=VainPlayer, self_deaf=True
                )
                await self.music_log(
                    title="Joined voice",
                    description=f"Connected to **{ctx.author.voice.channel}**",
                    guild=ctx.guild,
                    user=ctx.author,
                    fields=[
                        ("Channel", f"<#{ctx.author.voice.channel.id}>"),
                    ],
                )
            except NoNodesAvailable:
                await self.music_log(
                    title="Voice join failed — node not ready",
                    description="Node exists but was not ready for player creation.",
                    guild=ctx.guild,
                    user=ctx.author,
                    error=True,
                )
                await ctx.warn(
                    "music node connected but not ready yet — try again in a second"
                )
                return None
            except Exception as exc:
                log.exception("voice connect failed: %s", exc)
                await self.music_log(
                    title="Voice join failed",
                    description=f"```{exc}```",
                    guild=ctx.guild,
                    user=ctx.author,
                    error=True,
                )
                await ctx.warn(f"couldn't join voice: {exc}")
                return None

        player = ctx.voice_client
        
        if isinstance(player, VainPlayer) or hasattr(player, "wait_until_ready"):
            ok = await player.wait_until_ready(timeout=10.0)
            if not ok:
                log.warning(
                    "voice handshake incomplete guild=%s — play may be silent",
                    ctx.guild.id if ctx.guild else None,
                )
                await self.music_log(
                    title="Voice handshake incomplete",
                    description=(
                        "Joined VC but Discord voice server update was incomplete. "
                        "Playback may be silent."
                    ),
                    guild=ctx.guild,
                    user=ctx.author,
                    error=True,
                    fields=[
                        (
                            "Voice keys",
                            str(list((getattr(player, "_voice_state", None) or {}).keys())),
                        ),
                        (
                            "Node session",
                            str(bool(getattr(getattr(player, "_node", None), "_session_id", None))),
                        ),
                    ],
                )
        return player

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

    @staticmethod
    def _clean_title_artist(title: str, artist: str) -> tuple[str, str]:
        clean_title = _CLEAN_PARENS_RE.sub("", title or "")
        clean_title = _VIDEO_NOISE_RE.sub("", clean_title)
        artist = (artist or "").strip()
        if " - " in clean_title:
            left, right = clean_title.split(" - ", 1)
            if left.strip() and right.strip():
                
                if not artist or left.strip().lower() == artist.lower():
                    artist, clean_title = left.strip(), right.strip()
                else:
                    clean_title = right.strip()
        clean_title = re.sub(r"\s+", " ", clean_title).strip(" -_|")
        artist = re.sub(r"\s+", " ", artist).strip(" -_|")
        return clean_title, artist

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
        if q_tokens:
            hits = sum(1 for token in q_tokens if token in title or token in author)
            score += hits * 15
            if hits == len(q_tokens):
                score += 40

        
        if _VIDEO_NOISE_RE.search(title) or "vevo" in author:
            score -= 80
        if "topic" in author or " - topic" in author:
            score += 50
        if "audio" in title and "video" not in title:
            score += 30

        source = self._track_source(track)
        if source in {"youtube", "youtubemusic", "ytm"}:
            score += 20
        elif source == "soundcloud":
            score -= 30

        
        length = int(getattr(track, "length", 0) or 0)
        if 60_000 <= length <= 8 * 60_000:
            score += 10
        elif length > 15 * 60_000:
            score -= 25

        return score

    def _pick_track(self, results, pick_query: str | None = None):
        if not results:
            return None
        tracks = results.tracks if hasattr(results, "tracks") else results
        if not tracks:
            return None
        if not pick_query or len(tracks) == 1:
            
            ranked = sorted(
                tracks,
                key=lambda t: self._score_track(pick_query or (t.title or ""), t),
                reverse=True,
            )
            return ranked[0]
        ranked = sorted(
            tracks,
            key=lambda track: self._score_track(pick_query, track),
            reverse=True,
        )
        return ranked[0]

    async def _load_results(self, query: str):
        """Return raw get_tracks payload (list / Playlist) or None."""
        node = self._node
        if node is None or not _node_ready(node):
            if not await self._connect_node():
                return None
            node = self._node
        if node is None:
            return None
        try:
            
            
            return await node.get_tracks(query, search_type=None)
        except TypeError:
            
            try:
                return await node.get_tracks(query)
            except TrackLoadError as e:
                log.debug("track load failed for %r: %s", query, e)
                return None
            except Exception as e:
                log.debug("unexpected load error for %r: %s", query, e)
                return None
        except TrackLoadError as e:
            log.debug("track load failed for %r: %s", query, e)
            return None
        except Exception as e:
            log.debug("unexpected load error for %r: %s", query, e)
            return None

    async def _load_query(self, query: str, *, pick_query: str | None = None):
        results = await self._load_results(query)
        return self._pick_track(results, pick_query)

    async def _load_all_tracks(self, query: str) -> list:
        """Load a single track or expand a playlist into a list."""
        results = await self._load_results(query)
        if not results:
            return []
        if hasattr(results, "tracks"):
            return list(results.tracks or [])
        if isinstance(results, (list, tuple)):
            return list(results)
        return [results]

    def _is_platform_url(self, query: str) -> bool:
        q = query.lower()
        return bool(_PLATFORM_RE.search(q))

    def _platform_name(self, query: str) -> str:
        q = query.lower()
        if "spotify.com" in q or q.startswith("spotify:"):
            return "spotify"
        if "deezer.com" in q:
            return "deezer"
        if "music.apple.com" in q:
            return "apple music"
        if "soundcloud.com" in q:
            return "soundcloud"
        if "music.youtube.com" in q:
            return "youtube music"
        if "youtube.com" in q or "youtu.be" in q:
            return "youtube"
        return "link"

    def _ytm_url(self, track) -> str:
        """Prefer a youtube / ytm browse url for display."""
        uri = (getattr(track, "uri", None) or "").strip()
        ident = getattr(track, "identifier", None) or ""
        if "music.youtube.com" in uri:
            return uri
        if "youtube.com" in uri or "youtu.be" in uri:
            
            if "watch?v=" in uri:
                vid = uri.split("watch?v=", 1)[-1].split("&", 1)[0]
                return f"https://music.youtube.com/watch?v={vid}"
            return uri
        if ident and len(ident) >= 6:
            return f"https://music.youtube.com/watch?v={ident}"
        return uri or "https://music.youtube.com"

    @staticmethod
    def _track_key(track) -> str:
        tid = getattr(track, "track_id", None)
        if tid:
            return str(tid)
        ident = getattr(track, "identifier", None)
        if ident:
            return f"id:{ident}"
        return f"obj:{id(track)}"

    def _bind_meta(
        self,
        track,
        *,
        display_title: str | None = None,
        display_author: str | None = None,
        source_url: str | None = None,
        platform: str | None = None,
        from_search: bool = False,
    ) -> None:
        
        key = self._track_key(track)
        self._track_meta[key] = {
            "display_title": display_title or getattr(track, "title", None) or "unknown",
            "display_author": display_author
            or getattr(track, "author", None)
            or "unknown",
            "source_url": source_url,
            "platform": platform,
            "from_search": from_search,
            "play_url": self._ytm_url(track),
        }

    def _meta(self, track) -> dict:
        key = self._track_key(track)
        hit = self._track_meta.get(key)
        if hit is not None:
            return hit
        return {
            "display_title": getattr(track, "title", None) or "unknown",
            "display_author": getattr(track, "author", None) or "unknown",
            "source_url": None,
            "platform": None,
            "from_search": True,
            "play_url": self._ytm_url(track),
        }

    async def _resolve_to_youtube_audio(
        self,
        *,
        title: str,
        artist: str,
        source_url: str | None = None,
        platform: str | None = None,
    ):
        """Search YouTube Music / YouTube for an audio (non-VEVO) match."""
        clean_title, clean_artist = self._clean_title_artist(title, artist)
        pick = f"{clean_title} {clean_artist}".strip()
        queries = []
        if clean_artist and clean_title:
            queries.append(f"{clean_title} {clean_artist}")
            queries.append(f"{clean_artist} - {clean_title}")
        if clean_title:
            queries.append(clean_title)
        queries.append(f"{pick} audio")

        for source in ("ytmsearch", "ytsearch"):
            for q in queries:
                track = await self._load_query(f"{source}:{q}", pick_query=pick)
                if track is None:
                    continue
                self._bind_meta(
                    track,
                    display_title=clean_title or title,
                    display_author=clean_artist or artist,
                    source_url=source_url,
                    platform=platform,
                    from_search=source_url is None,
                )
                log.info(
                    "resolved via %s → %s — %s",
                    source,
                    track.title,
                    track.author,
                )
                return track
        return None

    async def _first_track(self, query: str):
        if self._node is None:
            return None
        query = self._normalize_query(query.strip())
        if not query:
            return None

        
        if self._is_direct_query(query) and (
            query.startswith(("http://", "https://", "spotify:"))
            or self._is_platform_url(query)
        ):
            platform = self._platform_name(query)
            seeded = await self._load_query(query)
            if seeded is not None:
                
                src = self._track_source(seeded)
                if src in {"youtube", "youtubemusic", "ytm"} and not (
                    _VIDEO_NOISE_RE.search(seeded.title or "")
                    or "vevo" in (seeded.author or "").lower()
                ):
                    self._bind_meta(
                        seeded,
                        display_title=seeded.title,
                        display_author=seeded.author,
                        source_url=query,
                        platform=platform,
                        from_search=False,
                    )
                    return seeded

                resolved = await self._resolve_to_youtube_audio(
                    title=seeded.title or query,
                    artist=seeded.author or "",
                    source_url=query,
                    platform=platform,
                )
                if resolved is not None:
                    return resolved
                
                self._bind_meta(
                    seeded,
                    display_title=seeded.title,
                    display_author=seeded.author,
                    source_url=query,
                    platform=platform,
                    from_search=False,
                )
                return seeded
            
            return await self._resolve_to_youtube_audio(
                title=query, artist="", source_url=None, platform=None
            )

        
        if _SEARCH_PREFIX_RE.match(query):
            track = await self._load_query(query, pick_query=query.split(":", 1)[-1])
            if track:
                self._bind_meta(track, from_search=True)
            return track

        for source in nl.search_sources:
            search = f"{source}:{query}"
            log.info("searching %s for %r", source, query)
            track = await self._load_query(search, pick_query=query)
            if track is None:
                continue
            title, artist = self._clean_title_artist(
                track.title or query, track.author or ""
            )
            self._bind_meta(
                track,
                display_title=title,
                display_author=artist,
                from_search=True,
            )
            return track

        log.info("no results for %r (tried %s)", query, ", ".join(nl.search_sources))
        return None

    

    @staticmethod
    def _fmt_ms(ms: int | float | None) -> str:
        try:
            total = max(0, int(ms or 0) // 1000)
        except Exception:
            total = 0
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _progress_bar(position: int, length: int, *, width: int = 14) -> str:
        if length <= 0:
            filled = 0
        else:
            filled = int(round((position / length) * width))
            filled = max(0, min(width, filled))
        return "━" * filled + "●" + "─" * max(0, width - filled)

    def _display_bits(self, track) -> tuple[str, str, str, str | None]:
        meta = self._meta(track)
        title = str(meta.get("display_title") or getattr(track, "title", None) or "unknown")
        artist = str(
            meta.get("display_author") or getattr(track, "author", None) or "unknown"
        )
        source_url = meta.get("source_url")
        play_url = meta.get("play_url") or self._ytm_url(track)
        from_search = bool(meta.get("from_search"))
        link = source_url if (source_url and not from_search) else play_url
        platform = meta.get("platform")
        return title, artist, str(link or ""), platform

    async def _set_vc_status(self, player, track=None) -> None:
        channel = getattr(player, "channel", None)
        if channel is None:
            return
        try:
            if track is None:
                await channel.edit(status=None)
                return
            title, artist, _, _ = self._display_bits(track)
            status = f"now playing: {title} by {artist}"
            if len(status) > 500:
                status = status[:497] + "…"
            await channel.edit(status=status)
        except Exception as exc:
            log.debug("vc status update failed: %s", exc)

    async def _build_panel_payload(
        self, guild_id: int, track, player=None
    ) -> tuple[discord.Embed, discord.File | None, MusicControlView]:
        title, artist, link, platform = self._display_bits(track)
        pos = int(getattr(player, "position", 0) or 0) if player else 0
        length = int(getattr(track, "length", 0) or 0)
        paused = bool(getattr(player, "is_paused", False)) if player else False

        if platform:
            header = f"playing **{platform}**"
        else:
            header = "now playing"

        song_line = (
            f"[**{title}** — **{artist}**]({link})"
            if link
            else f"**{title}** — **{artist}**"
        )
        
        emb = discord.Embed(
            color=color.base,
            description=compose(
                body(header, song_line),
                caption("> -# source: **youtube music**"),
            ),
        )

        art_url = getattr(track, "thumbnail", None)
        art_bytes = await fetch_image_bytes(str(art_url) if art_url else None)
        file = None
        try:
            card = await asyncio.to_thread(
                render_now_playing_card,
                title=title,
                artist=artist,
                position_ms=pos,
                length_ms=length,
                album_art=art_bytes,
                accent=int(color.base),
            )
            file = discord.File(io.BytesIO(card), filename="nowplaying.png")
            emb.set_image(url="attachment://nowplaying.png")
        except Exception:
            log.exception("panel art render failed")
            if art_url:
                try:
                    emb.set_thumbnail(url=str(art_url))
                except Exception:
                    pass

        view = MusicControlView(self, guild_id, paused=paused)
        return emb, file, view

    async def _send_control_panel(self, guild_id: int, player, track) -> None:
        """Delete old panel, send a fresh one (reply to ,play when possible)."""
        state = self._queue(guild_id)
        channel = None
        if state.text_channel_id:
            channel = self.bot.get_channel(state.text_channel_id)
        if channel is None:
            return

        
        await self._set_vc_status(player, track)

        
        if state.control_message_id:
            try:
                old = await channel.fetch_message(state.control_message_id)
                await old.delete()
            except Exception:
                pass
            state.control_message_id = None

        emb, file, view = await self._build_panel_payload(guild_id, track, player)

        
        reference = None
        if state.play_message_id:
            try:
                play_msg = await channel.fetch_message(state.play_message_id)
                reference = play_msg.to_reference(fail_if_not_exists=False)
            except Exception:
                state.play_message_id = None
                reference = None

        kwargs: dict = {
            "embed": emb,
            "view": view,
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if file is not None:
            kwargs["file"] = file
        if reference is not None:
            kwargs["reference"] = reference

        try:
            msg = await channel.send(**kwargs)
            state.control_message_id = msg.id
            view.message = msg
        except Exception:
            
            try:
                kwargs.pop("reference", None)
                emb2, file2, view2 = await self._build_panel_payload(
                    guild_id, track, player
                )
                send_kw = {
                    "embed": emb2,
                    "view": view2,
                    "allowed_mentions": discord.AllowedMentions.none(),
                }
                if file2 is not None:
                    send_kw["file"] = file2
                msg = await channel.send(**send_kw)
                state.control_message_id = msg.id
                view2.message = msg
            except Exception:
                log.exception("failed to send control panel guild=%s", guild_id)

    async def _stop_and_leave(self, guild_id: int, player) -> None:
        state = self._queue(guild_id)
        state.tracks.clear()
        state.current = None
        state.loop = False
        await self._set_vc_status(player, None)
        try:
            await player.stop()
        except Exception:
            pass
        try:
            await player.disconnect(force=True)
        except Exception:
            pass
        self.queues.pop(guild_id, None)

    async def _panel_show_queue(
        self, inter: discord.Interaction, guild_id: int
    ) -> None:
        state = self._queue(guild_id)
        lines: list[str] = []
        if state.current:
            t, a, _, _ = self._display_bits(state.current)
            lines.append(f"**now:** {t} — {a}")
        for i, tr in enumerate(state.tracks[:20], 1):
            t, a, _, _ = self._display_bits(tr)
            lines.append(f"`{i}.` **{t}** — {a}")
        if not lines:
            text = "> queue is empty"
        else:
            text = compose(body(*lines), caption(f"{len(state.tracks)} queued"))
        if inter.response.is_done():
            await inter.followup.send(text, ephemeral=True)
        else:
            await inter.response.send_message(text, ephemeral=True)

    async def _panel_add_track(
        self, inter: discord.Interaction, guild_id: int, query: str
    ) -> None:
        if not query:
            return await inter.response.send_message("give a song or url", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        player = inter.guild.voice_client if inter.guild else None
        if player is None:
            return await inter.followup.send("nothing playing — use `,play` first", ephemeral=True)

        tracks: list = []
        normalized = self._normalize_query(query)
        if self._is_direct_query(normalized) and (
            "playlist" in normalized.lower()
            or "album" in normalized.lower()
            or "/sets/" in normalized.lower()
        ):
            raw = await self._load_all_tracks(normalized)
            if raw:
                platform = self._platform_name(normalized)
                for t in raw:
                    self._bind_meta(
                        t,
                        display_title=getattr(t, "title", None),
                        display_author=getattr(t, "author", None),
                        source_url=normalized,
                        platform=platform,
                        from_search=False,
                    )
                tracks = raw
        if not tracks:
            t = await self._first_track(query)
            if t is None:
                return await inter.followup.send("no results", ephemeral=True)
            tracks = [t]

        state = self._queue(guild_id)
        state.tracks.extend(tracks)
        first = tracks[0]
        title, artist, link, _ = self._display_bits(first)
        extra = f" · +{len(tracks) - 1} more" if len(tracks) > 1 else ""
        await inter.followup.send(
            compose(
                body("queued", f"[**{title}** — **{artist}**]({link})"),
                caption(f"{len(state.tracks)} in queue{extra}"),
            ),
            ephemeral=True,
        )

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

    async def _play_next(
        self, guild_id: int, player, *, force: bool = False, _depth: int = 0
    ) -> None:
        """Start the next track. force=True skips single-track loop (used by skip)."""
        if _depth > 8:
            log.warning("play_next depth exceeded guild=%s", guild_id)
            return
        state = self._queue(guild_id)
        if state.loop and state.current and not force:
            track = state.current
        elif state.tracks:
            track = state.tracks.pop(0)
            if state.loop_queue:
                state.tracks.append(track)
            state.current = track
        else:
            state.current = None
            await self._set_vc_status(player, None)
            
            import time as _time

            age = _time.time() - (state.session_started_at or 0.0)
            await asyncio.sleep(1.5)
            state2 = self._queue(guild_id)
            if (
                state2.current is None
                and not state2.tracks
                and age >= 5.0
                and not getattr(player, "is_playing", False)
            ):
                try:
                    await player.disconnect(force=True)
                except Exception:
                    pass
            return
        try:
            if hasattr(player, "wait_until_ready"):
                await player.wait_until_ready(timeout=15.0)
            await player.play(track)
        except Exception as exc:
            log.exception("auto-advance failed in guild %s", guild_id)
            title, artist, _, _ = self._display_bits(track)
            await self.music_log(
                title="Auto-advance play failed",
                description=f"```{exc}```",
                guild=getattr(player, "guild", None),
                error=True,
                fields=[
                    ("Track", f"{title} — {artist}"),
                    ("Queue remaining", str(len(state.tracks))),
                    ("Depth", str(_depth)),
                ],
            )
            state.current = None
            if state.tracks:
                await self._play_next(
                    guild_id, player, force=True, _depth=_depth + 1
                )
            return
        if state.active_preset:
            try:
                await self._apply_preset(player, state.active_preset)
            except Exception:
                log.exception("preset apply failed guild=%s", guild_id)
        try:
            await self._send_control_panel(guild_id, player, track)
        except Exception:
            pass

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
    async def play(self, ctx: Context, *, query: str, next: bool = False) -> None:
        query, play_next = self._parse_play_flags(query, next=next)
        if not query or not query.strip():
            return await ctx.warn("give a song name or link")

        await self.music_log(
            title="Play requested",
            description=f"Query: `{query[:500]}`",
            guild=ctx.guild,
            user=ctx.author,
            fields=[
                ("Channel", f"<#{ctx.channel.id}>"),
                ("Voice", (
                    f"<#{ctx.author.voice.channel.id}>"
                    if ctx.author.voice and ctx.author.voice.channel
                    else "not in VC"
                )),
                ("Next flag", str(play_next)),
            ],
        )

        player = await self._player(ctx)
        if player is None:
            return

        
        normalized = self._normalize_query(query)
        tracks: list = []
        if self._is_direct_query(normalized) and (
            "playlist" in normalized.lower()
            or "album" in normalized.lower()
            or "/sets/" in normalized.lower()
        ):
            raw = await self._load_all_tracks(normalized)
            if raw:
                platform = self._platform_name(normalized)
                for t in raw:
                    self._bind_meta(
                        t,
                        display_title=getattr(t, "title", None),
                        display_author=getattr(t, "author", None),
                        source_url=normalized,
                        platform=platform,
                        from_search=False,
                    )
                tracks = raw

        if not tracks:
            track = await self._first_track(query)
            if track is None:
                await self.music_log(
                    title="No results",
                    description=f"Search returned nothing for `{query[:500]}`",
                    guild=ctx.guild,
                    user=ctx.author,
                    error=True,
                    fields=[
                        ("Normalized", f"`{normalized[:500]}`"),
                        ("Sources", ", ".join(nl.search_sources)),
                        ("Node ready", str(_node_ready(self._node))),
                    ],
                )
                return await ctx.warn("no results")
            tracks = [track]

        state = self._queue(ctx.guild.id)
        state.text_channel_id = ctx.channel.id
        import time as _time

        if not state.session_started_at:
            state.session_started_at = _time.time()
        if ctx.message is not None:
            state.play_message_id = ctx.message.id
        first = tracks[0]
        title, artist, link, platform = self._display_bits(first)

        try:
            busy = bool(getattr(player, "is_playing", False))
            if busy:
                if play_next:
                    for t in reversed(tracks):
                        state.tracks.insert(0, t)
                else:
                    state.tracks.extend(tracks)
                qmsg = f"[**{title}** — **{artist}**]({link})"
                if platform:
                    qmsg = f"**{platform}** · {qmsg}"
                extra = f" · +{len(tracks) - 1} more" if len(tracks) > 1 else ""
                await self.music_log(
                    title="Track queued",
                    description=qmsg,
                    guild=ctx.guild,
                    user=ctx.author,
                    fields=[
                        ("Queue size", str(len(state.tracks))),
                        ("Tracks added", str(len(tracks))),
                    ],
                )
                return await ctx.send(
                    embed=discord.Embed(
                        color=color.base,
                        description=compose(
                            body("queued", qmsg),
                            caption(f"position `{len(state.tracks)}`{extra}"),
                        ),
                    )
                )

            state.current = first
            if len(tracks) > 1:
                state.tracks.extend(tracks[1:])
            
            await asyncio.sleep(0.6)
            if hasattr(player, "wait_until_ready"):
                ok = await player.wait_until_ready(timeout=15.0)
                if not ok:
                    log.warning(
                        "voice handshake incomplete before play guild=%s",
                        ctx.guild.id,
                    )
                    node = getattr(player, "_node", None)
                    await self.music_log(
                        title="Handshake incomplete before play",
                        description=(
                            "Discord voice and/or node session not ready. "
                            "Will still attempt play."
                        ),
                        guild=ctx.guild,
                        user=ctx.author,
                        error=True,
                        fields=[
                            ("Track", f"{title} — {artist}"),
                            (
                                "Voice ready",
                                str(getattr(player, "voice_ready", lambda: "?")()),
                            ),
                            (
                                "Node session",
                                str(bool(getattr(node, "_session_id", None))),
                            ),
                            (
                                "NodeLink",
                                str(bool(getattr(node, "_is_nodelink", False))),
                            ),
                            (
                                "Endpoint",
                                str(getattr(player, "_player_endpoint_uri", "?")),
                            ),
                        ],
                    )
            try:
                await player.play(first)
            except Exception as exc:
                log.exception("initial play failed: %s", exc)
                node = getattr(player, "_node", None)
                await self.music_log(
                    title="Initial play failed — retrying",
                    description=f"```{exc}```",
                    guild=ctx.guild,
                    user=ctx.author,
                    error=True,
                    fields=[
                        ("Track", f"{title} — {artist}"),
                        ("Encoded", str(_safe_attr(first, "track_id") or "?")[:40]),
                        ("Source", self._track_source(first) or "?"),
                        (
                            "Node session",
                            str(getattr(node, "_session_id", None) or "none")[:32],
                        ),
                        (
                            "Endpoint",
                            str(getattr(player, "_player_endpoint_uri", "?")),
                        ),
                        (
                            "Voice keys",
                            str(list((getattr(player, "_voice_state", None) or {}).keys())),
                        ),
                    ],
                )
                try:
                    player._current = None
                except Exception:
                    pass
                
                await asyncio.sleep(1.0)
                if hasattr(player, "wait_until_ready"):
                    await player.wait_until_ready(timeout=10.0)
                try:
                    await player.play(first)
                except Exception as exc2:
                    state.current = None
                    log.exception("play retry failed: %s", exc2)
                    await self.music_log(
                        title="Play failed after retry",
                        description=f"```{exc2}```",
                        guild=ctx.guild,
                        user=ctx.author,
                        error=True,
                        fields=[
                            ("Query", f"`{query[:500]}`"),
                            ("Track", f"{title} — {artist}"),
                            ("First error", f"```{exc}```"),
                            (
                                "Node",
                                f"`{nl.host}:{nl.port}` ready={_node_ready(self._node)}",
                            ),
                            (
                                "Player channel",
                                str(getattr(getattr(player, "channel", None), "id", None)),
                            ),
                        ],
                    )
                    return await ctx.fail(
                        f"couldn't start playback — check nodelink/lavalink logs ({exc2})"
                    )
            if state.active_preset:
                try:
                    await self._apply_preset(player, state.active_preset)
                except Exception:
                    pass
            await self._send_control_panel(ctx.guild.id, player, first)
            await self.music_log(
                title="Playback started",
                description=f"[**{title}** — **{artist}**]({link})" if link else f"**{title}** — **{artist}**",
                guild=ctx.guild,
                user=ctx.author,
                fields=[
                    ("Platform", platform or "search"),
                    ("Source", self._track_source(first) or "?"),
                    ("Length", self._fmt_ms(getattr(first, "length", 0))),
                    ("Volume", str(getattr(player, "_volume", state.volume))),
                    ("Encoded", str(_safe_attr(first, "track_id") or "?")[:48]),
                ],
            )
            if len(tracks) > 1:
                try:
                    await ctx.send(
                        embed=discord.Embed(
                            color=color.base,
                            description=compose(
                                body(
                                    "playlist loaded",
                                    f"**{len(tracks) - 1}** more tracks queued",
                                ),
                            ),
                        )
                    )
                except Exception:
                    pass
            if ctx.message is not None:
                try:
                    await ctx.message.add_reaction("👍")
                except Exception:
                    pass
        except NodeRestException as exc:
            log.error("play failed for %r: %s", query, exc)
            await self.music_log(
                title="Node REST error",
                description=f"```{exc}```",
                guild=ctx.guild,
                user=ctx.author,
                error=True,
                fields=[("Query", f"`{query[:500]}`")],
            )
            return await ctx.fail(f"failed to play track: {exc}")
        except Exception as exc:
            log.exception("play failed for %r", query)
            await self.music_log(
                title="Play crashed",
                description=f"```{exc}```",
                guild=ctx.guild,
                user=ctx.author,
                error=True,
                fields=[("Query", f"`{query[:500]}`")],
            )
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
        lines: list[str] = []
        if state.current:
            m = self._meta(state.current)
            lines.append(
                f"**now:** {m.get('display_title') or state.current.title} — "
                f"{m.get('display_author') or state.current.author}"
            )
        for i, t in enumerate(state.tracks[:15], 1):
            m = self._meta(t)
            lines.append(
                f"`{i}.` **{m.get('display_title') or t.title}** — "
                f"{m.get('display_author') or t.author}"
            )
        await ctx.send(
            embed=discord.Embed(
                color=color.base,
                description=compose(
                    body(*lines),
                    caption(f"{len(state.tracks)} queued"),
                ),
            )
        )

    @hybrid(
        name="currentlyplaying",
        aliases=["cplay", "current", "currently"],
        guild_only=True,
    )
    async def currentlyplaying(self, ctx: Context) -> None:
        """Show the current track control panel."""
        player = ctx.voice_client
        state = self._queue(ctx.guild.id)
        track = state.current or (player.current if player else None)
        if player is None or track is None:
            return await ctx.warn("nothing playing")
        state.text_channel_id = ctx.channel.id
        if ctx.message is not None:
            state.play_message_id = ctx.message.id
        await self._send_control_panel(ctx.guild.id, player, track)

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
    async def skip(self, ctx: Context) -> None:
        player = ctx.voice_client
        if player is None or not getattr(player, "is_playing", False):
            return await ctx.warn("nothing playing")
        state = self._queue(ctx.guild.id)
        
        try:
            await player.stop()
        except Exception as exc:
            return await ctx.warn(f"couldn't skip: {exc}")
        
        await self._play_next(ctx.guild.id, player, force=True)
        if state.current:
            await ctx.success("skipped")
        else:
            await ctx.success("skipped · queue empty")

    @hybrid(name="pause", guild_only=True)
    async def pause(self, ctx: Context) -> None:
        player = ctx.voice_client
        if player is None or not getattr(player, "is_playing", False):
            return await ctx.warn("nothing playing")
        if getattr(player, "is_paused", False):
            return await ctx.warn("already paused")
        await player.set_pause(True)
        await ctx.success("paused")

    @hybrid(name="resume", guild_only=True)
    async def resume(self, ctx: Context) -> None:
        player = ctx.voice_client
        if player is None:
            return await ctx.warn("nothing playing")
        if not getattr(player, "is_paused", False):
            return await ctx.warn("not paused")
        await player.set_pause(False)
        await ctx.success("resumed")

    @hybrid(name="shuffle", guild_only=True)
    async def shuffle(self, ctx: Context) -> None:
        """Shuffle the upcoming queue (not loop-queue toggle)."""
        state = self._queue(ctx.guild.id)
        if len(state.tracks) < 2:
            return await ctx.warn("not enough tracks")
        random.shuffle(state.tracks)
        await ctx.success("shuffled queue")

    @hybrid(name="loopqueue", aliases=["qloop"], guild_only=True)
    async def loopqueue(self, ctx: Context) -> None:
        state = self._queue(ctx.guild.id)
        state.loop_queue = not state.loop_queue
        await ctx.success(f"queue loop **{'on' if state.loop_queue else 'off'}**")

    @hybrid(name="repeat", guild_only=True)
    @describe(option="on or off")
    async def repeat(self, ctx: Context, option: str | None = None) -> None:
        state = self._queue(ctx.guild.id)
        state.loop = (
            (not state.loop)
            if option is None
            else option.lower() in {"on", "true", "yes", "enable"}
        )
        await ctx.success(f"repeat **{'on' if state.loop else 'off'}**")

    @hybrid(name="volume", guild_only=True)
    @describe(volume="Volume from 0 to 200")
    async def volume(self, ctx: Context, volume: int) -> None:
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
    async def fastforward(self, ctx: Context, position: int) -> None:
        player = ctx.voice_client
        if player is None or player.current is None:
            return await ctx.warn("nothing playing")
        length = int(getattr(player.current, "length", 0) or 0)
        target = min(int(player.position) + position * 1000, length)
        await player.seek(target)
        await ctx.success(f"+{position}s")

    @hybrid(name="rewind", guild_only=True)
    @describe(position="Seconds to rewind")
    async def rewind(self, ctx: Context, position: int) -> None:
        player = ctx.voice_client
        if player is None or player.current is None:
            return await ctx.warn("nothing playing")
        target = max(int(player.position) - position * 1000, 0)
        await player.seek(target)
        await ctx.success(f"-{position}s")

    @hybrid(name="disconnect", aliases=["dc", "leave"], guild_only=True)
    async def disconnect(self, ctx: Context) -> None:
        if ctx.voice_client:
            try:
                await ctx.voice_client.disconnect(force=True)
            except Exception:
                pass
        self.queues.pop(ctx.guild.id, None)
        
        if len(self._track_meta) > 200:
            self._track_meta.clear()
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


def _make_preset_command(preset_name: str):
    async def _preset_cmd(self, ctx: Context, setting: str | None = None) -> None:
        await self._set_preset(ctx, preset_name, setting)

    _preset_cmd.__name__ = f"preset_{preset_name.replace('8d', 'eightd')}"
    _preset_cmd.__qualname__ = f"Music.preset_{preset_name.replace('8d', 'eightd')}"
    return Music.preset.command(
        name=preset_name,
        description=f"Toggle the {preset_name} audio preset",
    )(
        describe(setting="on or off")(_preset_cmd)
    )


for _preset_name in Music.PRESETS:
    _make_preset_command(_preset_name)


async def setup(bot: Vain):
    if not music_enabled:
        return
    await bot.add_cog(Music(bot))
