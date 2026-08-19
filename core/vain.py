from __future__ import annotations

import ast
import asyncio
import contextlib
import copy
import datetime
import logging
import time
import traceback

import discord
import config

from pathlib import Path
from discord import app_commands
from discord.ext import commands
from typing import Awaitable, Callable, Iterable, Literal, Optional
from discord.ext.commands import BucketType, CooldownMapping, HybridCommand, HybridGroup

from .patches import cmd as _command_patch  # noqa: F401

from .discord.ctx import Cache, Context
from .discord.help import VainHelp
from .discord.hybrid import rewrite_linked_prefix
from .managers.database.client import Database
from .managers.redis import VainCache, FileVainCache, RedisClient
from .managers.guard import Guard
from .tools.embed import PreparedScript, Script, parse
from .tools.errors import Ratelimited
from .tools.snipe import Snipe
from config import color, database, redis, emojis, music_enabled
from .managers.filetypes import CACHE_REDIS_FILE, ensure_storage_files

from .discord.interaction import patch_interaction

from .discord.views.embed import reply_embed

patch_interaction()


from .tools.convert.channel import patch_discord_channel_converters

patch_discord_channel_converters()

log = logging.getLogger("vain")


_SKIP_DIRS = frozenset({"models", "__pycache__"})


def _has_setup_entry(path: Path) -> bool:
    target = path / "__init__.py" if path.is_dir() else path
    try:
        source = target.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    try:
        tree = ast.parse(source, filename=str(target))
    except SyntaxError:
        return False

    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "setup"
        ):
            return True
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "setup" for alias in node.names):
                return True
        if isinstance(node, ast.Import):
            if any(alias.asname == "setup" for alias in node.names):
                return True
    return False


def _discover_extensions(ext_dir: str = "ext") -> tuple[str, ...]:
    """Scan ext/ (and category subfolders) for loadable extensions.

    Layout supported:
      ext/<package>/__init__.py          → ext.package
      ext/<category>/<package>/…         → ext.category.package
      ext/<category>/<module>.py         → ext.category.module

    Category folders are plain directories (no setup()). Packages with setup() load once.
    """
    base = Path(ext_dir)
    if not base.exists():
        log.warning(f"ext dir not found: {base.resolve()}")
        return ()

    found: list[str] = []

    def _add_package(path: Path) -> None:
        if (path / "__init__.py").exists() and _has_setup_entry(path):
            found.append(".".join(path.relative_to(Path(".")).parts))

    def _add_module(path: Path) -> None:
        if path.suffix == ".py" and path.stem not in {"__init__", *_SKIP_DIRS}:
            if not path.stem.startswith("_") and _has_setup_entry(path):
                found.append(
                    ".".join(path.relative_to(Path(".")).with_suffix("").parts)
                )

    def _scan_dir(directory: Path, *, depth: int = 0) -> None:
        if depth > 4:
            return
        for child in sorted(directory.iterdir()):
            if child.name.startswith("_") or child.name in _SKIP_DIRS:
                continue
            if child.is_dir():
                
                if (child / "__init__.py").exists() and _has_setup_entry(child):
                    _add_package(child)
                    
                    ext_dir = child / "extended"
                    if ext_dir.is_dir():
                        for sub in sorted(ext_dir.iterdir()):
                            if (
                                sub.is_dir()
                                and not sub.name.startswith("_")
                                and sub.name not in _SKIP_DIRS
                                and (sub / "__init__.py").exists()
                                and _has_setup_entry(sub)
                            ):
                                _add_package(sub)
                    
                    for py_file in sorted(child.rglob("*.py")):
                        if py_file.name != "__init__.py" and py_file.parent != child:
                            _add_module(py_file)
                    continue
                
                _scan_dir(child, depth=depth + 1)
                
                for py_file in sorted(child.glob("*.py")):
                    _add_module(py_file)
                continue
            if directory == base:
                _add_module(child)

    _scan_dir(base)
    
    seen: set[str] = set()
    unique: list[str] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    unique.sort()
    if not music_enabled:
        unique = [ext for ext in unique if not ext.endswith(".music") and ".music." not in ext and ext != "ext.music"]
    log.debug(f"discovered {len(unique)} extensions: {', '.join(unique)}")
    return tuple(unique)



class Blacklisted(commands.CheckFailure):
    """User or guild is blacklisted — handlers must stay silent."""
    def __init__(self, reason: str | None = None):
        self.reason = reason
        super().__init__("blacklisted")


_BLACKLIST_SQL = """
    SELECT reason FROM blacklist
    WHERE user_id = $1 OR guild_id = $2
    LIMIT 1
"""

_USER_PREFIX_SQL = "SELECT prefix FROM self_prefix WHERE user_id = $1"

_GUILD_PREFIX_SQL = """
    SELECT COALESCE(
        (SELECT prefixes FROM config WHERE guild_id = $1),
        CASE
            WHEN (SELECT prefix FROM guilds WHERE guild_id = $1) IS NOT NULL
                THEN ARRAY[(SELECT prefix FROM guilds WHERE guild_id = $1)]::TEXT[]
            ELSE ARRAY[$2]::TEXT[]
        END
    )
"""

_SILENCED_SQL = """
    SELECT 1 FROM silenced
    WHERE guild_id = $1 AND user_id = $2
    LIMIT 1
"""

_PREFIX_TTL = 300
_ACCESS_TTL = 60
_MESSAGE_STATE_TTL = 30

_DISABLED_CMD_SQL = """
    SELECT object_ids, object_types FROM disabled_commands
    WHERE guild_id = $1 AND lower(command) = lower($2)
"""

_RESTRICTIONS_SQL = """
    SELECT role_id FROM command_restrictions
    WHERE guild_id = $1 AND command = $2
"""


class Vain(commands.AutoShardedBot):
    def __init__(self) -> None:
        self.color: int = color.base
        self.db = Database()
        self.redis: RedisClient | None = None
        self.object_cache = Cache(self)
        self.guard = Guard()
        self.snipes = Snipe(self)
        self._error_store: dict[str, str] = {}
        self._error_counter: int = 0
        self.started_at = datetime.datetime.now(datetime.timezone.utc)
        self._seen_message_ids: set[int] = set()
        self.global_cooldown: CooldownMapping = CooldownMapping.from_cooldown(
            2, 2.4, BucketType.user
        )
        self.config = {
            "emojis": {
                "success": emojis.approve,
                "fail": emojis.deny,
                "warning": emojis.warn,
                "loading": emojis.loading,
            },
        }

        owner_list = list(
            getattr(config.Bot, "owners", None)
            or getattr(config.bot, "owners", None)
            or []
        )
        super().__init__(
            command_prefix=self._get_prefix,
            intents=discord.Intents.all(),
            owner_ids=set(int(x) for x in owner_list),
            help_command=VainHelp(),
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False, replied_user=False
            ),
            strip_after_prefix=True,
            case_insensitive=True,
            chunk_guilds_at_startup=False,
            max_messages=1000,
        )
        self._vain_help = self.help_command

    @property
    def owners(self) -> set[int]:
        """Owner ids for codebase checks (`bot.owners`). Backed by discord.py owner_ids."""
        ids: set[int] = set(self.owner_ids or ())
        if getattr(self, "owner_id", None):
            ids.add(int(self.owner_id))

        for oid in (
            getattr(config.Bot, "owners", None)
            or getattr(config.bot, "owners", None)
            or []
        ):
            ids.add(int(oid))
        return ids

    async def remember(
        self, key: str, ttl: int, loader: Callable[[], Awaitable[object]]
    ) -> object:
        """small local ttl cache for hot runtime reads"""
        cached = await self.object_cache.get(key)
        if cached is not None:
            return cached["value"]
        try:
            value = await loader()
        except Exception:
            return None
        await self.object_cache.set(key, {"value": value}, ttl=ttl)
        return value

    async def forget(self, *keys: str) -> None:
        for key in keys:
            await self.object_cache.delete(key)

    async def invalidate_prefix_cache(
        self,
        *,
        guild_id: int | None = None,
        user_id: int | None = None,
    ) -> None:
        keys: list[str] = []
        if guild_id is not None:
            keys.append(f"prefix:guild:{guild_id}")
        if user_id is not None:
            keys.append(f"prefix:user:{user_id}")
        if keys:
            await self.forget(*keys)
        
        
        if self.redis is not None and guild_id is not None and user_id is not None:
            with contextlib.suppress(Exception):
                await self.redis.delete(f"prefix:{guild_id}:{user_id}")

    async def invalidate_command_access_cache(
        self, guild_id: int, command_name: str
    ) -> None:
        qualified = command_name.lower()
        await self.forget(
            f"restrict:{guild_id}:{qualified}",
            f"disabled:{guild_id}:{qualified}",
        )

    async def _fetch_user_prefix(self, user_id: int) -> Optional[str]:
        return await self.remember(
            f"prefix:user:{user_id}",
            _PREFIX_TTL,
            lambda: self.db.fetchval(_USER_PREFIX_SQL, user_id),
        )

    async def _fetch_guild_prefixes(self, guild_id: int) -> list[str]:
        result = await self.remember(
            f"prefix:guild:{guild_id}",
            _PREFIX_TTL,
            lambda: self.db.fetchval(_GUILD_PREFIX_SQL, guild_id, config.Bot.prefix),
        )
        return list(result) if result else [config.Bot.prefix]

    async def _fetch_prefixes(self, guild_id: int, user_id: int) -> dict:
        """pull prefix data from individual caches (object_cache + db)."""
        
        
        user_pfx, guild_pfxs = await asyncio.gather(
            self._fetch_user_prefix(user_id),
            self._fetch_guild_prefixes(guild_id),
        )
        return {
            "user": user_pfx,
            "guild": guild_pfxs or [config.Bot.prefix],
        }

    async def _get_prefix(self, _: "Vain", msg: discord.Message) -> Iterable[str]:
        if not msg.guild:
            return commands.when_mentioned_or(config.Bot.prefix)(self, msg)
        data = await self._fetch_prefixes(msg.guild.id, msg.author.id)
        guild_pfxs: list[str] = data["guild"]
        user_pfx: Optional[str] = data["user"]
        for pfx in sorted(guild_pfxs, key=len, reverse=True):
            if msg.content.startswith(pfx):
                return commands.when_mentioned_or(pfx)(self, msg)
        if user_pfx and msg.content.startswith(user_pfx):
            return commands.when_mentioned_or(user_pfx)(self, msg)
        fallback = guild_pfxs[0] if guild_pfxs else config.Bot.prefix
        return commands.when_mentioned_or(fallback)(self, msg)

    def _is_slash(self, cmd: commands.Command) -> bool:
        return (
            isinstance(cmd, (HybridCommand, HybridGroup))
            and bool(getattr(cmd, "app_command", None))
            and cmd.parent is None
            and not getattr(
                getattr(cmd, "cog", None), "__cog_is_app_commands_group__", False
            )
        )

    def add_command(self, cmd: commands.Command, /) -> None:
        commands.GroupMixin.add_command(self, cmd)
        if not self._is_slash(cmd):
            return
        with contextlib.suppress(
            app_commands.CommandAlreadyRegistered, app_commands.CommandLimitReached
        ):
            self.tree.add_command(cmd.app_command)

    async def setup_hook(self) -> None:
        """connect db redis and load all extensions"""
        started = time.perf_counter()
        log.info("setup process started")

        ensure_storage_files()

        log.info("connecting database")
        await self.db.connect()
        log.info("database connected (%.1fs)", time.perf_counter() - started)

        if redis.enabled:
            log.info("connecting redis at %s", redis.url)
            try:
                self.redis = await VainCache.from_url(redis.url)
                log.info("redis connected")
            except Exception as e:
                log.warning(f"redis failed: {e}")
        else:
            log.info("redis disabled, using file store at %s", CACHE_REDIS_FILE)
            self.redis = await FileVainCache.open(CACHE_REDIS_FILE)

        self.add_check(self._global_check)
        self.tree.on_error = self._slash_error
        self.tree.interaction_check = self._slash_check

        log.info("loading extensions")
        extensions_started = time.perf_counter()
        await self.load_extension("jishaku")
        await self._load_extensions()
        log.info(
            "extensions finished (%.1fs)", time.perf_counter() - extensions_started
        )

        from ext.server.extended.pagination.improper.views import (
            PaginationReactionListener,
            register_stored_paginations,
        )

        await register_stored_paginations(self)
        if self.get_cog("PaginationReactionListener") is None:
            await self.add_cog(PaginationReactionListener(self))

        log.info("syncing global slash commands")
        sync_started = time.perf_counter()
        await self._sync_global_commands()
        log.info(
            "global slash sync finished (%.1fs)", time.perf_counter() - sync_started
        )
        log.info("setup_hook complete (%.1fs total)", time.perf_counter() - started)

    async def _load_extensions(self) -> None:
        extensions = _discover_extensions("ext")
        results = await asyncio.gather(
            *[self._try_load(ext) for ext in extensions],
            return_exceptions=True,
        )

        loaded = sum(1 for r in results if r is True)
        failed = len(extensions) - loaded
        if failed:
            log.warning("%d/%d extensions failed to load", failed, len(extensions))

    async def _try_load(self, ext: str) -> bool:
        ext_name = ext.split(".")[-1]
        try:
            await self.load_extension(ext)
            log.info("(+) %s", ext_name)
            return True
        except Exception as e:
            log.warning("(-) %s: %s", ext_name, e)
            log.debug("extension load traceback for %s", ext_name, exc_info=True)
            return False

    def _normalize_extension(self, name: str) -> str:
        """Accept ``utility``, ``ext.utility``, or dotted subpaths."""
        raw = (name or "").strip().strip("`").strip()
        if not raw:
            raise ValueError("missing extension name")
        if raw in ("all", "*", "~"):
            return raw
        if raw.startswith("ext."):
            return raw
        if raw == "jishaku" or raw.startswith("jishaku."):
            return raw
        return f"ext.{raw}"

    async def reload_extension(self, name: str, *, package: str | None = None) -> None:
        """Reload an extension; if setup fails after unload, attempt recovery load."""
        try:
            await super().reload_extension(name, package=package)
            return
        except TypeError:
            try:
                await super().reload_extension(name)
                return
            except Exception as first:
                err = first
        except Exception as first:
            err = first

        if name in self.extensions:
            raise err

        try:
            await super().load_extension(name)
            log.warning("reload of %s failed (%s); recovered via load_extension", name, err)
        except Exception as second:
            raise err from second

    async def safe_reload_extension(self, name: str) -> tuple[bool, str | None]:
        try:
            if name not in self.extensions:
                await self.load_extension(name)
                return True, None
            await self.reload_extension(name)
            return True, None
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"


    async def _sync_global_commands(self) -> None:
        try:
            synced = await self.tree.sync()
            log.info(f"synced {len(synced)} global slash commands")
        except Exception as e:
            log.exception(f"slash sync failed: {e}")

    async def get_context(self, origin, /, *, cls=Context) -> Context:
        if isinstance(origin, discord.Message):
            prefixes = await self._get_prefix(self, origin)
            rewritten = rewrite_linked_prefix(origin.content, prefixes)
            if rewritten is not None:
                origin = copy.copy(origin)
                origin._update({"content": rewritten})
        return await super().get_context(origin, cls=cls)

    @staticmethod
    def _blocked_ids(raw) -> set[int]:
        if raw is None:
            return set()
        if hasattr(raw, "get") and not isinstance(raw, (list, tuple, set)):
            raw = raw.get("object_ids", raw)
        if not raw:
            return set()
        out: set[int] = set()
        for x in raw:
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
        return out

    async def _load_disabled_commands(self, guild_id: int, command_name: str):
        row = await self.db.fetchrow(_DISABLED_CMD_SQL, guild_id, command_name)
        if not row:
            return None
        object_ids = getattr(row, "object_ids", None)
        if object_ids is None and hasattr(row, "get"):
            object_ids = row.get("object_ids")
        object_types = getattr(row, "object_types", None)
        if object_types is None and hasattr(row, "get"):
            object_types = row.get("object_types")
        return {
            "object_ids": [int(x) for x in (object_ids or [])],
            "object_types": list(object_types or []),
        }


    @staticmethod
    def _bot_channel_perms(channel, guild, bot_user=None):
        """Safe permissions snapshot for the bot in a channel.

        Returns None when the channel is not a real guild channel or the
        bot member cannot be resolved (DMs, jsk override, uncached me).
        """
        perms_for = getattr(channel, "permissions_for", None)
        if not callable(perms_for) or guild is None:
            return None
        me = getattr(guild, "me", None)
        if me is None or not hasattr(me, "guild"):
            uid = getattr(bot_user, "id", None)
            me = guild.get_member(uid) if uid is not None else None
        if me is None:
            return None
        try:
            return perms_for(me)
        except Exception:
            return None

    async def _global_check(self, ctx: Context) -> bool:
        """runs before every command"""
        owner = await self.is_owner(ctx.author)
        is_help = False
        if ctx.command is not None:
            is_help = ctx.command.qualified_name.lower() == "help"

        if not owner:
            uid = ctx.author.id
            gid = ctx.guild.id if ctx.guild is not None else None
            user_bl = await self.remember(
                f"blacklist:user:{uid}",
                _ACCESS_TTL,
                lambda: self.db.fetchval(
                    "SELECT COALESCE(reason, '') FROM blacklist WHERE user_id = $1 LIMIT 1",
                    uid,
                ),
            )
            guild_bl = None
            if gid is not None:
                guild_bl = await self.remember(
                    f"blacklist:guild:{gid}",
                    _ACCESS_TTL,
                    lambda: self.db.fetchval(
                        "SELECT COALESCE(reason, '') FROM blacklist WHERE guild_id = $1 LIMIT 1",
                        gid,
                    ),
                )
            if user_bl is not None or guild_bl is not None:
                reason = None
                if isinstance(user_bl, str) and user_bl:
                    reason = user_bl
                elif isinstance(guild_bl, str) and guild_bl:
                    reason = guild_bl
                raise Blacklisted(reason)

        if (
            ctx.command is not None
            and ctx.guild is not None
            and not is_help
            and not owner
        ):
            cmd_name = ctx.command.qualified_name.lower()
            rows = await self.remember(
                f"restrict:{ctx.guild.id}:{cmd_name}",
                _ACCESS_TTL,
                lambda: self.db.fetch(_RESTRICTIONS_SQL, ctx.guild.id, cmd_name),
            )
            if rows:
                allowed = {r.role_id for r in rows}
                member_roles = {r.id for r in getattr(ctx.author, "roles", []) or []}
                if not (allowed & member_roles):
                    raise commands.CheckFailure(
                        f"**you are not allowed** to use the `{cmd_name}`\n\ncommand"
                    )

        if ctx.command is not None and ctx.guild is not None and not is_help:
            cmd_name = ctx.command.qualified_name.lower()
            disabled = await self.remember(
                f"disabled:{ctx.guild.id}:{cmd_name}",
                _ACCESS_TTL,
                lambda: self._load_disabled_commands(ctx.guild.id, cmd_name),
            )
            if disabled:
                object_ids = (
                    disabled.get("object_ids")
                    if isinstance(disabled, dict)
                    else getattr(disabled, "object_ids", None)
                )
                object_types = (
                    disabled.get("object_types")
                    if isinstance(disabled, dict)
                    else getattr(disabled, "object_types", None)
                ) or []
                blocked = self._blocked_ids(object_ids)
                types = list(object_types)

                
                role_ids = {
                    oid
                    for oid, kind in zip(blocked, types)
                    if str(kind).lower() == "role"
                }
                if role_ids:
                    member_roles = {r.id for r in getattr(ctx.author, "roles", []) or []}
                    if not (role_ids & member_roles):
                        raise commands.CheckFailure(
                            f"**you are not allowed** to use the `{cmd_name}`\n\ncommand"
                        )

                if ctx.author.id in blocked:
                    raise commands.CheckFailure(
                        f"**you are not allowed** to use the `{cmd_name}`\n\ncommand"
                    )

                
                guild_blocked = any(
                    str(kind).lower() in {"guild", "server"}
                    for kind in types
                ) or (ctx.guild.id in blocked)
                if guild_blocked:
                    raise commands.CheckFailure(
                        f"> The `{cmd_name}` command is **disabled in this server**"
                    )

                if ctx.channel.id in blocked:
                    raise commands.CheckFailure(
                        f"> The `{cmd_name}` command is **disabled in this channel**"
                    )

            
            cog = getattr(ctx.command, "cog", None)
            module_name = None
            if cog is not None:
                module_name = (
                    getattr(cog, "qualified_name", None)
                    or cog.__class__.__name__
                )
                module_name = str(module_name).lower().replace(" ", "")
            if module_name:
                mod_row = await self.remember(
                    f"disabledmod:{ctx.guild.id}:{module_name}",
                    _ACCESS_TTL,
                    lambda mn=module_name: self.db.fetchrow(
                        """
                        SELECT channel_ids FROM disabled_modules
                        WHERE guild_id = $1 AND lower(module) = lower($2)
                        """,
                        ctx.guild.id,
                        mn,
                    ),
                )
                if mod_row:
                    channel_ids = list(
                        getattr(mod_row, "channel_ids", None)
                        or (mod_row.get("channel_ids") if hasattr(mod_row, "get") else [])
                        or []
                    )
                    label = module_name
                    all_text = [c.id for c in ctx.guild.text_channels]
                    if channel_ids and all(
                        cid in set(int(x) for x in channel_ids) for cid in all_text
                    ):
                        raise commands.CheckFailure(
                            f"> The `{label}` module is **disabled in this server**"
                        )
                    if ctx.channel.id in {int(x) for x in channel_ids}:
                        raise commands.CheckFailure(
                            f"> The `{label}` module is **disabled in this channel**"
                        )

        if ctx.guild is not None:
            my_perms = self._bot_channel_perms(
                getattr(ctx, "channel", None),
                ctx.guild,
                getattr(ctx.bot, "user", None),
            )
            if my_perms is not None:
                need = (
                    ("send_messages",)
                    if is_help
                    else ("send_messages", "embed_links", "attach_files")
                )
                missing = [perm for perm in need if not getattr(my_perms, perm, True)]
                if missing:
                    raise commands.BotMissingPermissions(missing)

        if not owner and not is_help:
            await self.cooldown_check(ctx)

        return True

    @staticmethod
    async def cooldown_check(ctx: Context) -> Literal[True]:
        """global cooldown: 2 commands / 2.4s per user."""
        if await ctx.bot.is_owner(ctx.author):
            return True

        message = getattr(ctx, "message", None)
        if message is None:
            return True

        bucket = ctx.bot.global_cooldown.get_bucket(message)
        if not bucket:
            return True

        retry_after = bucket.update_rate_limit()
        if retry_after:
            raise commands.CommandOnCooldown(bucket, retry_after, BucketType.user)

        return True

    async def _slash_check(self, inter: discord.Interaction) -> bool:
        """global check for slash commands"""
        if inter.type != discord.InteractionType.application_command:
            return True
        ctx = await self.get_context(inter, cls=Context)
        cmd = self._resolve_slash_command(inter)
        if cmd is not None and ctx.command is None:
            ctx.command = cmd
        try:
            await self._global_check(ctx)
        except Blacklisted:
            return False
        except commands.CommandOnCooldown as e:
            cd = getattr(e, "cooldown", None) or app_commands.Cooldown(rate=2, per=2.4)
            raise app_commands.CommandOnCooldown(cd, float(e.retry_after)) from e
        except Ratelimited as e:
            raise app_commands.CommandOnCooldown(
                app_commands.Cooldown(rate=2, per=2.4),
                float(e.retry_after),
            ) from e
        except commands.CheckFailure as e:
            raise app_commands.CheckFailure(str(e)) from e
        except Exception as e:
            log.warning("_slash_check: _global_check error: %s", e)
            raise app_commands.CheckFailure(str(e)) from e
        if cmd is None:
            return True
        try:
            await self._run_command_checks(cmd, ctx)
        except commands.CommandError as e:
            raise app_commands.CheckFailure(str(e)) from e
        except Exception as e:
            raise app_commands.CheckFailure(str(e)) from e
        return True

    @staticmethod
    async def _run_command_checks(
        cmd: commands.Command, ctx: Context
    ) -> None:
        """Run command- and cog-level checks only.

        Unlike ``cmd.can_run(ctx)`` this intentionally **skips** the
        bot-level checks (``Bot._checks``) because the caller
        (``_slash_check``) already executes them once via
        ``_global_check``. Running them a second time through
        ``Bot.can_run`` was causing double-execution and, when the
        second run raised a non-``CommandError``, uncaught exceptions
        that silently broke slash commands for non-owners.
        """
        if not cmd.enabled:
            raise commands.DisabledCommand(cmd.name)

        cog = cmd.cog
        if cog is not None:
            check = getattr(cog.__cog_settings__, "check", None)
            if check is not None and not await check(ctx):
                raise commands.CheckFailure(
                    f"the cog check for {cog.qualified_name!r} failed"
                )

        for check in cmd.checks:
            if not await check(ctx):
                raise commands.CheckFailure("the command checks failed")

    def _format_cooldown(self, retry_after: float) -> str:
        seconds = max(float(retry_after), 0.01)
        if seconds < 1:
            return f"{seconds:.2f} seconds"
        if seconds < 60:
            whole = int(seconds) if seconds == int(seconds) else round(seconds, 1)
            unit = "second" if float(whole) == 1 else "seconds"
            return f"{whole} {unit}"
        minutes, secs = divmod(int(seconds), 60)
        if minutes < 60:
            if secs == 0:
                unit = "minute" if minutes == 1 else "minutes"
                return f"{minutes} {unit}"
            munit = "minute" if minutes == 1 else "minutes"
            sunit = "second" if secs == 1 else "seconds"
            return f"{minutes} {munit} and {secs} {sunit}"
        hours, minutes = divmod(minutes, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours} {'hour' if hours == 1 else 'hours'}")
        if minutes:
            parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        return " and ".join(parts) if parts else f"{int(seconds)} seconds"

    async def _cooldown_reply(
        self, inter: discord.Interaction, retry_after: float
    ) -> None:
        ctx = await self.get_context(inter, cls=Context)
        emoji = await ctx._get_emoji("cooldown")
        color_value = await ctx._get_color("cooldown")
        wait = self._format_cooldown(retry_after)
        embed = reply_embed(
            color=color_value,
            message=(
                f"{emoji} {inter.user.mention}: This command is on cooldown, "
                f"please wait **{wait}**"
            ),
        )
        send = (
            inter.followup.send
            if inter.response.is_done()
            else inter.response.send_message
        )
        with contextlib.suppress(discord.HTTPException):
            await send(embed=embed, ephemeral=True)

    async def _slash_error(
        self, inter: discord.Interaction, err: app_commands.AppCommandError
    ) -> None:
        """handle slash command errors"""
        orig = getattr(err, "original", err)
        if isinstance(orig, Blacklisted) or isinstance(err, Blacklisted):
            return
        if isinstance(orig, discord.NotFound):
            return
        send = (
            inter.followup.send
            if inter.response.is_done()
            else inter.response.send_message
        )
        msg = str(err) or "something went wrong"
        if isinstance(orig, Ratelimited):
            await self._cooldown_reply(inter, orig.retry_after)
            return
        if isinstance(err, app_commands.CommandOnCooldown):
            await self._cooldown_reply(inter, err.retry_after)
            return
        with contextlib.suppress(discord.HTTPException):
            await send(content=msg, ephemeral=True)

    def _resolve_slash_command(
        self, inter: discord.Interaction
    ) -> Optional[commands.Command]:
        """walk interaction data to find the matching prefix command"""
        data = inter.data
        if not data or inter.type is not discord.InteractionType.application_command:
            return None
        parts = [data["name"]]
        opts = data.get("options") or []
        while opts:
            entry = opts[0]
            if entry.get("type") not in (
                discord.AppCommandOptionType.subcommand.value,
                discord.AppCommandOptionType.subcommand_group.value,
            ):
                break
            parts.append(entry["name"])
            opts = entry.get("options") or []
        node = self
        for part in parts:
            getter = getattr(node, "get_command", None)
            if not getter:
                return None
            node = getter(part)
            if node is None:
                return None
        return node if isinstance(node, commands.Command) else None

    async def is_owner(self, user: discord.abc.User) -> bool:
        if user.id in self.owners:
            return True
        return await super().is_owner(user)

    async def on_ready(self) -> None:
        assert self.user
        log.info(f"online as {self.user} in {len(self.guilds)} guilds")

        await self.change_presence(
            status=discord.Status.online,
            activity=discord.CustomActivity(name="🔗 discord.gg/vains"),
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        pass

    async def on_message(self, msg: discord.Message) -> None:
        if msg.author.bot or not self.is_ready():
            return
        if msg.guild:
            perms = self._bot_channel_perms(msg.channel, msg.guild, self.user)
            if perms is not None and not perms.send_messages:
                return
            if not await self.is_owner(msg.author):
                silenced = await self.remember(
                    f"silenced:{msg.guild.id}:{msg.author.id}",
                    _MESSAGE_STATE_TTL,
                    lambda: self.db.fetchval(
                        _SILENCED_SQL, msg.guild.id, msg.author.id
                    ),
                )
                if bool(silenced):
                    with contextlib.suppress(discord.HTTPException):
                        await msg.delete()
                    return
        if msg.id in self._seen_message_ids:
            return
        self._seen_message_ids.add(msg.id)
        if len(self._seen_message_ids) > 5000:
            self._seen_message_ids.clear()
        ctx = await self.get_context(msg)
        if msg.guild:
            self.dispatch("context", ctx)
            if not ctx.valid:
                self.dispatch("valid_message", ctx)
        await self.invoke(ctx)

    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if before.content == after.content or after.author.bot or not self.is_ready():
            return
        ctx = await self.get_context(after)
        await self.invoke(ctx)

    async def on_command_error(self, ctx: Context, err: Exception) -> None:
        err = self._unwrap(err)
        if isinstance(err, (Blacklisted, commands.CommandNotFound)):
            return
        if isinstance(err, commands.MissingRequiredArgument):
            with contextlib.suppress(discord.HTTPException):
                await ctx.send_help(ctx.command)
            return
        if isinstance(err, (Ratelimited, commands.CommandOnCooldown)):
            retry_after = float(getattr(err, "retry_after", 0) or 0)
            if retry_after <= 30:
                with contextlib.suppress(discord.HTTPException, AttributeError):
                    if ctx.message is not None:
                        await ctx.message.add_reaction("⏳")
                return
            wait = self._format_cooldown(retry_after)
            with contextlib.suppress(discord.HTTPException):
                await ctx.cooldown(
                    f"This command is on cooldown, please wait **{wait}**",
                    delete_after=5,
                )
            return

        if isinstance(err, commands.NotOwner):
            return
        cog = getattr(ctx.command, "cog", None) if ctx.command else None
        cog_name = type(cog).__name__ if cog is not None else ""
        qn = (getattr(ctx.command, "qualified_name", None) or "").lower()
        if isinstance(err, commands.CheckFailure) and (
            cog_name in {"Owner", "Jishaku", "Developer", "Manager"}
            or qn.startswith("jsk")
            or qn.startswith("jishaku")
        ):
            return

        if isinstance(err, commands.CommandError):
            msg = str(err).strip() or "you **can't** do that"
            with contextlib.suppress(discord.HTTPException, Exception):
                await ctx.fail(msg)
            return

        self._error_counter += 1
        error_id = str(self._error_counter)
        tb_text = "".join(traceback.format_exception(type(err), err, err.__traceback__))
        self._error_store[error_id] = tb_text
        if len(self._error_store) > 50:
            oldest = min(self._error_store.keys(), key=lambda k: int(k))
            del self._error_store[oldest]

        log.exception(
            "unhandled error in %s: %s",
            getattr(ctx.command, "qualified_name", "?"),
            err,
        )
        with contextlib.suppress(discord.HTTPException, Exception):
            await ctx.fail(f"something went wrong (error #{error_id})")

    async def on_command_completion(self, ctx: Context) -> None:
        if not ctx.guild or not ctx.command:
            return
        with contextlib.suppress(Exception):
            await self.db.execute(
                """INSERT INTO command_usage (guild_id, user_id, command_name, uses)
                   VALUES ($1, $2, $3, 1)
                   ON CONFLICT (guild_id, user_id, command_name)
                   DO UPDATE SET uses = command_usage.uses + 1""",
                ctx.guild.id,
                ctx.author.id,
                ctx.command.qualified_name,
            )

    @staticmethod
    def _unwrap(err: Exception) -> Exception:
        while isinstance(
            err, (commands.CommandInvokeError, commands.HybridCommandError)
        ):
            err = err.original
        if isinstance(err, commands.ConversionError):
            return err.original or err
        return err

    async def create_embed(self, template: str, **kw) -> PreparedScript:
        """prepare a reusable embed payload from vain script text"""
        user = kw.get("user") or kw.get("member")
        if user is None and hasattr(kw.get("ctx"), "author"):
            user = kw["ctx"].author
        script = Script(template, user)
        payload = await script.data(True, **kw)
        return PreparedScript(payload)

    async def send_embed(self, dest, template: str, **kw) -> discord.Message:
        """parse vain embed code, resolve variables, and send it"""
        if "user" not in kw and "member" not in kw and hasattr(dest, "author"):
            kw["user"] = dest.author
        if "guild" not in kw and hasattr(dest, "guild"):
            kw["guild"] = dest.guild
        if "channel" not in kw:
            if hasattr(dest, "channel"):
                kw["channel"] = dest.channel
            elif isinstance(dest, (discord.TextChannel, discord.Thread)):
                kw["channel"] = dest
        builder = await self.create_embed(template, **kw)
        return await builder.send(dest)

    async def send_script(self, dest, template: str, user, **kw) -> discord.Message:
        """legacy helper for sending vain embed code"""
        return await self.send_embed(dest, template, user=user, **kw)

    async def close(self) -> None:
        """Close database, cache, and the discord bot smoothly."""
        await self.db.close()
        if self.redis:
            await self.redis.close()
        with contextlib.suppress(Exception):
            await super().close()
        log.info("Clean shutdown.")
