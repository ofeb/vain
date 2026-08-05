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
from typing import Awaitable, Callable, Iterable, Optional
from discord.ext.commands import HybridCommand, HybridGroup

from .patches import cmd as _command_patch  # noqa: F401

from .discord.ctx import Cache, Context
from .discord.help import VainHelp
from .discord.hybrid import rewrite_linked_prefix
from .managers.database.client import Database
from .managers.redis import VainCache, FileVainCache, RedisClient
from .managers.guard import Guard
from .tools.embed import PreparedScript, Script, parse
from .tools.errors import Ratelimited
from .tools.ratelimit import global_ratelimit
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
    """scan ext/ and return dotted module paths for every loadable extension.
    package-style extensions load once from their top-level folder.
    non-package folders load each top-level python module with a setup entrypoint."""
    base = Path(ext_dir)
    if not base.exists():
        log.warning(f"ext dir not found: {base.resolve()}")
        return ()

    found: list[str] = []
    for child in sorted(base.iterdir()):
        if child.name.startswith("_") or child.name in _SKIP_DIRS:
            continue
        if child.is_dir():
            if (child / "__init__.py").exists():
                if _has_setup_entry(child):
                    found.append(".".join(child.relative_to(Path(".")).parts))
                continue
            for py_file in sorted(child.glob("*.py")):
                if py_file.stem.startswith("_") or py_file.stem in _SKIP_DIRS:
                    continue
                if _has_setup_entry(py_file):
                    found.append(
                        ".".join(py_file.relative_to(Path(".")).with_suffix("").parts)
                    )

            for sub in sorted(child.iterdir()):
                if (
                    not sub.is_dir()
                    or sub.name.startswith("_")
                    or sub.name in _SKIP_DIRS
                ):
                    continue
                if (sub / "__init__.py").exists() and _has_setup_entry(sub):
                    found.append(".".join(sub.relative_to(Path(".")).parts))
            continue
        if child.suffix == ".py" and child.stem != "__init__":
            if _has_setup_entry(child):
                found.append(
                    ".".join(child.relative_to(Path(".")).with_suffix("").parts)
                )

    found.sort()
    if not music_enabled:
        found = [ext for ext in found if ext != "ext.music"]
    log.debug(f"discovered {len(found)} extensions: {', '.join(found)}")
    return tuple(found)


_BLACKLIST_SQL = """
    SELECT 1 FROM blacklist
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
        value = await loader()
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

        from ext.server.extended.pagination.views import register_stored_paginations

        await register_stored_paginations(self)

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
        failed = sum(1 for r in results if isinstance(r, Exception))
        if failed:
            log.warning("%d/%d extensions failed to load", failed, len(extensions))

    async def _try_load(self, ext: str) -> bool:
        ext_name = ext.split(".")[-1]
        try:
            await self.load_extension(ext)
            log.info("(+) %s", ext_name)
            return True
        except Exception as e:
            log.warning("(-) %s (%s)", ext_name, e)
            return False

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

    async def _global_check(self, ctx: Context) -> bool:
        """runs before every command"""
        owner = await self.is_owner(ctx.author)
        is_help = False
        if ctx.command is not None:
            is_help = ctx.command.qualified_name.lower() == "help"

        if ctx.guild is not None and not owner:
            blacklisted = await self.remember(
                f"blacklist:{ctx.guild.id}:{ctx.author.id}",
                _ACCESS_TTL,
                lambda: self.db.fetchval(_BLACKLIST_SQL, ctx.author.id, ctx.guild.id),
            )
            if bool(blacklisted):
                raise commands.CheckFailure("youre **blacklisted** from using this bot")

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
                if not (allowed & {r.id for r in ctx.author.roles}):
                    mentions = ", ".join(
                        r.mention for rid in allowed if (r := ctx.guild.get_role(rid))
                    )
                    raise commands.CheckFailure(f"only {mentions} can use `{cmd_name}`")

        if ctx.command is not None and ctx.guild is not None and not is_help:
            cmd_name = ctx.command.qualified_name.lower()
            disabled = await self.remember(
                f"disabled:{ctx.guild.id}:{cmd_name}",
                _ACCESS_TTL,
                lambda: self._load_disabled_commands(ctx.guild.id, cmd_name),
            )
            if disabled:
                blocked = self._blocked_ids(
                    disabled.get("object_ids")
                    if isinstance(disabled, dict)
                    else getattr(disabled, "object_ids", None)
                )
                if ctx.author.id in blocked:
                    raise commands.CheckFailure(
                        "this command has been **disabled** for you!"
                    )
                if ctx.channel.id in blocked:
                    raise commands.CheckFailure(
                        "this command has been **disabled** in this channel!"
                    )

        if ctx.guild is not None:
            me = ctx.channel.permissions_for(ctx.guild.me)
            need = (
                ("send_messages",)
                if is_help
                else ("send_messages", "embed_links", "attach_files")
            )
            missing = [p for p in need if not getattr(me, p)]
            if missing:
                raise commands.BotMissingPermissions(missing)

        if not owner and not is_help:
            retry = global_ratelimit(ctx.author.id)
            if retry:
                raise Ratelimited(retry)

        return True

    async def _slash_check(self, inter: discord.Interaction) -> bool:
        """global check for slash commands"""
        ctx = await self.get_context(inter, cls=Context)
        cmd = self._resolve_slash_command(inter)
        if cmd is not None and ctx.command is None:
            ctx.command = cmd
        try:
            await self._global_check(ctx)
        except Ratelimited:
            raise
        except commands.CheckFailure as e:
            raise app_commands.CheckFailure(str(e)) from e
        if cmd is None:
            return True
        try:
            return await cmd.can_run(ctx)
        except commands.CommandError as e:
            raise app_commands.CheckFailure(str(e)) from e

    async def _cooldown_reply(
        self, inter: discord.Interaction, retry_after: float
    ) -> None:
        ctx = await self.get_context(inter, cls=Context)
        emoji = await ctx._get_emoji("cooldown")
        color_value = await ctx._get_color("cooldown")
        embed = reply_embed(
            color=color_value,
            message=(
                f"{emoji} {inter.user.mention}: Please wait "
                f"**{retry_after:.2f} seconds** before using any command again"
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
            if not msg.channel.permissions_for(msg.guild.me).send_messages:
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
        if isinstance(err, commands.CommandNotFound):
            return
        if isinstance(err, commands.MissingRequiredArgument):
            with contextlib.suppress(discord.HTTPException):
                await ctx.send_help(ctx.command)
            return
        if isinstance(err, Ratelimited):
            with contextlib.suppress(discord.HTTPException):
                await ctx.cooldown(
                    f"Please wait **{err.retry_after:.2f} seconds** before using any command again"
                )
            return
        if isinstance(err, commands.CommandOnCooldown):
            with contextlib.suppress(discord.HTTPException):
                await ctx.cooldown(
                    f"Please wait **{err.retry_after:.2f} seconds** before using this command again"
                )
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
