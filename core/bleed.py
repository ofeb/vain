from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
from pathlib import Path
from typing import Iterable, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import HybridCommand, HybridGroup

from .discord.ctx import Cache, Context
from .discord.help import BleedHelp
from .managers.database.client import Database
from .managers.redis.client import BleedCache
from .managers.watch import Watcher
from .managers.guard import Guard
from .tools.embed import PreparedScript, Script, parse
from .managers.values import token, bot, color, database, redis, emojis

log = logging.getLogger("bleed")


_SKIP_DIRS = frozenset({"models", "__pycache__"})
_SAFE_JISHAKU_COMMANDS = frozenset({"invite", "rtt"})


def _has_setup_entry(path: Path) -> bool:
    target = path / "__init__.py" if path.is_dir() else path
    try:
        source = target.read_text(encoding="utf-8")
    except OSError:
        return False
    return "def setup(" in source or "async def setup(" in source


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
                    found.append(".".join(py_file.relative_to(Path(".")).with_suffix("").parts))
            continue
        if child.suffix == ".py" and child.stem != "__init__":
            if _has_setup_entry(child):
                found.append(".".join(child.relative_to(Path(".")).with_suffix("").parts))

    found.sort()
    log.debug(f"discovered {len(found)} extensions: {', '.join(found)}")
    return tuple(found)

_BLACKLIST_SQL = """
    SELECT 1 FROM blacklist
    WHERE (user_id = $1) OR (guild_id = $2)
    LIMIT 1
"""

_PREFIX_TTL = 120

_DISABLED_CMD_SQL = """
    SELECT object_ids FROM disabled_commands
    WHERE guild_id = $1 AND command = $2
"""

_RESTRICTIONS_SQL = """
    SELECT role_id FROM command_restrictions
    WHERE guild_id = $1 AND command = $2
"""


def _intents() -> discord.Intents:
    i = discord.Intents.none()
    i.guilds = True
    i.members = True
    i.bans = True
    i.emojis_and_stickers = True
    i.integrations = True
    i.webhooks = True
    i.invites = True
    i.voice_states = True
    i.guild_messages = True
    i.message_content = True
    i.guild_reactions = True
    i.guild_scheduled_events = True
    i.moderation = True
    return i


class Bleed(commands.AutoShardedBot):
    """the main bot class.
    manages db redis extensions and all discord events.
    instantiate then call run with the token"""

    def __init__(self) -> None:
        self.color: int = color.base
        self.db = Database()
        self.redis: Optional[BleedCache] = None
        self._bleed_help = BleedHelp()
        self.object_cache = Cache(self)
        self.guard = Guard()
        self.watcher: Optional[Watcher] = None
        self.started_at = datetime.datetime.now(datetime.timezone.utc)
        self._seen_message_ids: set[int] = set()
        self._guild_slash_commands: list[app_commands.Command] = []
        self._guild_slash_synced = False
        self.owners = set(bot.owners)
        self.config = {
            "token": token,
            "prefix": bot.prefix,
            "emojis": {
                "success": emojis.approve,
                "fail": emojis.deny,
                "warning": emojis.warn,
                "loading": emojis.loading,
            },
        }

        super().__init__(
            command_prefix=self._get_prefix,
            intents=_intents(),
            owner_ids=self.owners,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False, replied_user=False
            ),
            strip_after_prefix=True,
            case_insensitive=True,
            help_command=None,
            chunk_guilds_at_startup=False,
            max_messages=1000,
        )
        self._bleed_help.register(self)

    async def _fetch_prefixes(self, guild_id: int, user_id: int) -> dict:
        """pull prefix data from cache or db"""
        key = f"prefix:{guild_id}:{user_id}"
        if self.redis and (hit := await self.redis.get(key)):
            return hit

        user_pfx, guild_pfxs, legacy_prefix = await asyncio.gather(
            self.db.fetchval("SELECT prefix FROM self_prefix WHERE user_id = $1", user_id),
            self.db.fetchval("SELECT prefixes FROM config WHERE guild_id = $1", guild_id),
            self.db.fetchval("SELECT prefix FROM guilds WHERE guild_id = $1", guild_id),
        )
        data = {
            "user": user_pfx,
            "guild": list(guild_pfxs) if guild_pfxs else ([legacy_prefix] if legacy_prefix else [bot.prefix]),
        }
        if self.redis:
            await self.redis.set(key, data, ex=_PREFIX_TTL)
        return data

    async def _get_prefix(self, _: "Bleed", msg: discord.Message) -> Iterable[str]:
        """resolve prefixes for a message"""
        default = bot.prefix
        if not msg.guild:
            return commands.when_mentioned_or(default)(self, msg)
        data = await self._fetch_prefixes(msg.guild.id, msg.author.id)
        guild_pfxs: list[str] = data["guild"]
        user_pfx: Optional[str] = data["user"]
        for pfx in sorted(guild_pfxs, key=len, reverse=True):
            if msg.content.startswith(pfx):
                return commands.when_mentioned_or(pfx)(self, msg)
        if user_pfx and msg.content.startswith(user_pfx):
            return commands.when_mentioned_or(user_pfx)(self, msg)
        fallback = guild_pfxs[0] if guild_pfxs else default
        return commands.when_mentioned_or(fallback)(self, msg)


    def _is_slash(self, cmd: commands.Command) -> bool:
        return (
            isinstance(cmd, (HybridCommand, HybridGroup))
            and bool(getattr(cmd, "app_command", None))
            and cmd.parent is None
            and not getattr(getattr(cmd, "cog", None), "__cog_is_app_commands_group__", False)
        )

    def add_command(self, cmd: commands.Command, /) -> None:
        commands.GroupMixin.add_command(self, cmd)
        if not self._is_slash(cmd):
            return
        ac = cmd.app_command
        if getattr(ac, "guild_only", False):
            if ac not in self._guild_slash_commands:
                self._guild_slash_commands.append(ac)
            return
        with contextlib.suppress(app_commands.CommandAlreadyRegistered, app_commands.CommandLimitReached):
            self.tree.add_command(ac)

    async def setup_hook(self) -> None:
        """connect db redis and load all extensions"""
        await self.db.connect()
        log.info("db connected")
        
        await self._run_schema_migration()

        if redis.enabled:
            try:
                self.redis = await BleedCache.from_url(redis.url)
                log.info("redis connected")
            except Exception as e:
                log.warning(f"redis failed: {e}")

        self.add_check(self._global_check)
        self.tree.on_error = self._slash_error
        self.tree.interaction_check = self._slash_check

        await self._load_jishaku()
        await self._load_extensions()
        await self._sync_global_commands()

    async def _run_schema_migration(self) -> None:
        """Execute schema.sql to ensure all tables exist"""
        schema_path = Path(__file__).parent / "managers" / "database" / "models" / "schema.sql"
        if not schema_path.exists():
            log.warning(f"schema.sql not found at {schema_path}")
            return

        try:
            schema = schema_path.read_text(encoding="utf-8")
            async with self.db.pool.acquire() as conn:
                await conn.execute(schema)
            log.info("schema migration completed successfully")
        except Exception as e:
            log.warning(f"schema migration failed: {e}")

    async def _load_jishaku(self) -> None:
        try:
            await self.load_extension("jishaku")
            self._harden_jishaku()
            log.info("jishaku loaded")
        except Exception as e:
            log.warning(f"jishaku failed: {e}")

    def _harden_jishaku(self) -> None:
        """remove jishaku commands that can execute code, read files, or control the host"""
        root = self.get_command("jsk")
        if not isinstance(root, commands.Group):
            return

        for command in list(root.commands):
            if command.name in _SAFE_JISHAKU_COMMANDS:
                continue
            root.remove_command(command.name)

    async def _load_extensions(self) -> None:
        extensions = _discover_extensions("ext")
        results = await asyncio.gather(
            *[self._try_load(ext) for ext in extensions],
            return_exceptions=True,
        )
        ok = sum(1 for r in results if r is True)
        log.info(f"{ok}/{len(extensions)} extensions loaded")

    async def _try_load(self, ext: str) -> bool:
        try:
            await self.load_extension(ext)
            return True
        except Exception as e:
            log.exception(f"failed to load {ext}: {e}")
            return False

    async def _sync_global_commands(self) -> None:
        try:
            synced = await self.tree.sync()
            log.info(f"synced {len(synced)} global slash commands")
        except Exception as e:
            log.exception(f"slash sync failed: {e}")

    async def _sync_guild_commands(self, guild: Optional[discord.Guild] = None) -> None:
        if not self._guild_slash_commands:
            return
        targets = [guild] if guild else list(self.guilds)
        await asyncio.gather(*[self._sync_one_guild(g) for g in targets], return_exceptions=True)

    async def _sync_one_guild(self, guild: discord.Guild) -> None:
        for ac in self._guild_slash_commands:
            with contextlib.suppress(app_commands.CommandAlreadyRegistered, app_commands.CommandLimitReached):
                self.tree.add_command(ac, guild=guild)
        try:
            await self.tree.sync(guild=guild)
        except Exception as e:
            log.warning(f"guild sync failed for {guild.name}: {e}")

    async def get_context(self, origin, /, *, cls=Context) -> Context:
        return await super().get_context(origin, cls=cls)

    async def _global_check(self, ctx: Context) -> bool:
        """runs before every command"""
        if ctx.guild is None:
            return True

        if not await self.is_owner(ctx.author):
            if await self.db.fetchval(_BLACKLIST_SQL, ctx.author.id, ctx.guild.id):
                raise commands.CheckFailure("youre **blacklisted** from using this bot")

        if ctx.command is None:
            return True

        cmd_name = ctx.command.qualified_name.lower()
        is_help = cmd_name == "help"

        if not is_help:
            rows = await self.db.fetch(_RESTRICTIONS_SQL, ctx.guild.id, cmd_name)
            if rows:
                allowed = {r.role_id for r in rows}
                if not (allowed & {r.id for r in ctx.author.roles}):
                    mentions = ", ".join(
                        r.mention for rid in allowed if (r := ctx.guild.get_role(rid))
                    )
                    raise commands.CheckFailure(f"only {mentions} can use `{cmd_name}`")

            disabled = await self.db.fetchrow(_DISABLED_CMD_SQL, ctx.guild.id, ctx.command.qualified_name)
            if disabled and (ctx.author.id in disabled.object_ids or ctx.channel.id in disabled.object_ids):
                raise commands.CheckFailure(f"`{ctx.command.qualified_name}` is disabled here")

        me = ctx.channel.permissions_for(ctx.guild.me)
        need = ("send_messages",) if is_help else ("send_messages", "embed_links", "attach_files")
        missing = [p for p in need if not getattr(me, p)]
        if missing:
            raise commands.BotMissingPermissions(missing)

        if not is_help and self.redis:
            from .tools.ratelimit import ratelimiter
            retry = ratelimiter(f"cmds:{ctx.author.id}", ctx.author.id, rate=2, per=4)
            if retry:
                raise commands.CommandOnCooldown(None, retry, commands.BucketType.user)

        return True

    async def _slash_check(self, inter: discord.Interaction) -> bool:
        """global check for slash commands"""
        ctx = await self.get_context(inter, cls=Context)
        cmd = self._resolve_slash_command(inter)
        if cmd is None:
            return True
        try:
            return await cmd.can_run(ctx)
        except commands.CommandError as e:
            raise app_commands.CheckFailure(str(e)) from e

    async def _slash_error(self, inter: discord.Interaction, err: app_commands.AppCommandError) -> None:
        """handle slash command errors"""
        orig = getattr(err, "original", err)
        if isinstance(orig, discord.NotFound):
            return
        send = inter.followup.send if inter.response.is_done() else inter.response.send_message
        msg = str(err) or "something went wrong"
        if isinstance(err, app_commands.CommandOnCooldown):
            msg = f"slow down, try again in **{err.retry_after:.1f}s**"
        with contextlib.suppress(discord.HTTPException):
            await send(content=msg, ephemeral=True)

    def _resolve_slash_command(self, inter: discord.Interaction) -> Optional[commands.Command]:
        """walk interaction data to find the matching prefix command"""
        data = inter.data
        if not data or inter.type is not discord.InteractionType.application_command:
            return None
        parts = [data["name"]]
        opts = data.get("options") or []
        while opts:
            entry = opts[0]
            if entry.get("type") not in (
                app_commands.AppCommandOptionType.subcommand.value,
                app_commands.AppCommandOptionType.subcommand_group.value,
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
        if not self._guild_slash_synced:
            await self._sync_guild_commands()
            self._guild_slash_synced = True

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._sync_guild_commands(guild=guild)

    async def on_message(self, msg: discord.Message) -> None:
        if msg.author.bot or not self.is_ready():
            return
        if msg.guild:
            if not msg.channel.permissions_for(msg.guild.me).send_messages:
                return
            if await self.db.fetchval(
                "SELECT 1 FROM silenced WHERE guild_id = $1 AND user_id = $2",
                msg.guild.id, msg.author.id,
            ):
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

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
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
                await ctx.send_help()
            return
        if isinstance(err, commands.CommandError):
            with contextlib.suppress(discord.HTTPException):
                await ctx.fail(str(err))
            return
        log.exception(f"unhandled error in {ctx.command}: {err}")

    async def on_command_completion(self, ctx: Context) -> None:
        if not ctx.guild or not ctx.command:
            return
        with contextlib.suppress(Exception):
            await self.db.execute(
                """INSERT INTO command_usage (guild_id, user_id, command_name, uses)
                   VALUES ($1, $2, $3, 1)
                   ON CONFLICT (guild_id, user_id, command_name)
                   DO UPDATE SET uses = command_usage.uses + 1""",
                ctx.guild.id, ctx.author.id, ctx.command.qualified_name,
            )

    @staticmethod
    def _unwrap(err: Exception) -> Exception:
        while isinstance(err, (commands.CommandInvokeError, commands.HybridCommandError)):
            err = err.original
        return err

    async def create_embed(self, template: str, **kw) -> PreparedScript:
        """prepare a reusable embed payload from bleed script text"""
        user = kw.get("user") or kw.get("member")
        if user is None and hasattr(kw.get("ctx"), "author"):
            user = kw["ctx"].author
        script = Script(template, user)
        payload = await script.data(True, **kw)
        return PreparedScript(payload)

    async def send_embed(self, dest, template: str, **kw) -> discord.Message:
        """parse bleed embed code, resolve variables, and send it"""
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
        """legacy helper for sending bleed embed code"""
        return await self.send_embed(dest, template, user=user, **kw)

    async def close(self) -> None:
        """close db redis and bot connections"""
        await self.db.close()
        if self.redis:
            await self.redis.close()
        with contextlib.suppress(Exception):
            await super().close()
        log.info("bleed shut down cleanly")
