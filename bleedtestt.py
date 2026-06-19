"""
uh test to see if all commands & all possible shit works ^.^
"""

import asyncio
import sys
import traceback
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest.mock
from unittest.mock import AsyncMock, MagicMock, PropertyMock

asyncpg_pkg = types.ModuleType("asyncpg")
asyncpg_pkg.Connection = type("Connection", (), {})
asyncpg_pkg.Pool = type("Pool", (), {"acquire": lambda self: MagicMock()})
asyncpg_pkg.Record = type("Record", (), {"__getitem__": lambda self, k: None})
asyncpg_pkg.create_pool = AsyncMock()
asyncpg_pkg.exceptions = types.ModuleType("asyncpg.exceptions")
asyncpg_pkg.exceptions.InvalidCatalogNameError = type("InvalidCatalogNameError", (Exception,), {})
asyncpg_pkg.UniqueViolationError = type("UniqueViolationError", (Exception,), {})
asyncpg_pkg.exceptions.UniqueViolationError = asyncpg_pkg.UniqueViolationError
sys.modules["asyncpg"] = asyncpg_pkg
sys.modules["asyncpg.exceptions"] = asyncpg_pkg.exceptions

redis_pkg = types.ModuleType("redis")
redis_asyncio = types.ModuleType("redis.asyncio")
redis_connection = types.ModuleType("redis.asyncio.connection")
redis_connection.BlockingConnectionPool = type("BlockingConnectionPool", (), {})
redis_asyncio.connection = redis_connection
redis_lock = types.ModuleType("redis.asyncio.lock")
redis_lock.Lock = type("Lock", (), {})
redis_asyncio.lock = redis_lock
redis_asyncio.Redis = type("Redis", (), {"from_url": classmethod(AsyncMock())})
redis_pkg.Redis = redis_asyncio.Redis
redis_pkg.StrictRedis = type("StrictRedis", (), {"from_url": classmethod(AsyncMock())})
redis_pkg.asyncio = redis_asyncio
redis_backoff = types.ModuleType("redis.backoff")
redis_backoff.EqualJitterBackoff = type("EqualJitterBackoff", (), {})
redis_pkg.backoff = redis_backoff
redis_exceptions = types.ModuleType("redis.exceptions")
redis_exceptions.LockError = type("LockError", (Exception,), {})
redis_exceptions.NoScriptError = type("NoScriptError", (Exception,), {})
redis_pkg.exceptions = redis_exceptions
redis_retry = types.ModuleType("redis.retry")
redis_retry.Retry = type("Retry", (), {})
redis_pkg.retry = redis_retry
sys.modules["redis"] = redis_pkg
sys.modules["redis.asyncio"] = redis_asyncio
sys.modules["redis.asyncio.connection"] = redis_connection
sys.modules["redis.asyncio.lock"] = redis_lock
sys.modules["redis.backoff"] = redis_backoff
sys.modules["redis.exceptions"] = redis_exceptions
sys.modules["redis.retry"] = redis_retry

sys.modules["jishaku"] = unittest.mock.MagicMock()
fsm_mock = unittest.mock.MagicMock()
sys.modules["fast_string_match"] = fsm_mock
sys.modules["PIL"] = unittest.mock.MagicMock()
sys.modules["yt_dlp"] = unittest.mock.MagicMock()
sys.modules["TagScriptEngine"] = unittest.mock.MagicMock()
sys.modules["watchfiles"] = unittest.mock.MagicMock()

ujson_mock = unittest.mock.MagicMock()
ujson_mock.dumps = MagicMock(side_effect=lambda x, **kw: __import__('json').dumps(x))
ujson_mock.loads = MagicMock(side_effect=lambda x, **kw: __import__('json').loads(x))
sys.modules["ujson"] = ujson_mock
sys.modules["tuuid"] = unittest.mock.MagicMock()

import datetime
from io import BytesIO
from pathlib import Path

import discord
from discord import Embed, Interaction, SelectOption, ui
from discord.ext import commands
from discord.ext.commands import Command, Group, Cog


class MockConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def fetch(self, *args, **kwargs):
        return []

    async def fetchrow(self, *args, **kwargs):
        return None

    async def fetchval(self, *args, **kwargs):
        return None

    async def execute(self, *args, **kwargs):
        return ""


class MockPool:
    def acquire(self):
        return self

    async def __aenter__(self):
        return MockConnection()

    async def __aexit__(self, *args):
        pass

    def close(self):
        pass


class MockDatabase:
    pool = MockPool()

    async def connect(self):
        self.pool = MockPool()
        return self

    async def fetch(self, *args, **kwargs):
        return []

    async def fetchrow(self, *args, **kwargs):
        return None

    async def fetchval(self, *args, **kwargs):
        return None

    async def execute(self, *args, **kwargs):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _mock_core_modules():
    import core.bleed as bleed_mod
    import core.managers.database.database as db_mod
    import core.managers.database.client as db_client_mod

    db_client_mod.Database = MockDatabase
    db_mod.Database = MockDatabase

    bleed_mod.Bleed.setup_hook = MagicMock(return_value=None)
    return bleed_mod


_results = {
    "total": 0,
    "pass": 0,
    "fail": 0,
    "skip": 0,
    "details": [],
}


def ok(msg: str):
    _results["total"] += 1
    _results["pass"] += 1
    _results["details"].append(f"  PASS  {msg}")


def fail(msg: str):
    _results["total"] += 1
    _results["fail"] += 1
    _results["details"].append(f"  FAIL  {msg}")


def skip(msg: str):
    _results["total"] += 1
    _results["skip"] += 1
    _results["details"].append(f"  SKIP  {msg}")


async def main():
    bleed_mod = _mock_core_modules()
    Bleed = bleed_mod.Bleed

    bot = Bleed()

    from core.bleed import _discover_extensions
    exts = _discover_extensions("ext")
    print(f"\nLoading {len(exts)} extensions...")
    loaded_ok = 0
    loaded_fail = []
    for ext in exts:
        try:
            await bot.load_extension(ext)
            loaded_ok += 1
        except Exception as e:
            loaded_fail.append((ext, str(e)))
    print(f"  loaded {loaded_ok}/{len(exts)} ({len(loaded_fail)} failed)")
    for ext, err in loaded_fail:
        print(f"    FAIL  {ext}: {err.split(chr(10))[0]}")

    all_cogs: list[Cog] = list(bot.cogs.values())

    all_commands: list[Command] = []
    for cog in all_cogs:
        for cmd in cog.walk_commands():
            all_commands.append(cmd)

    for name, cmd in bot.all_commands.items():
        if cmd not in all_commands:
            all_commands.append(cmd)
            if cmd.cog and cmd.cog not in all_cogs:
                all_cogs.append(cmd.cog)

    print(f"\nDiscovered {len(all_cogs)} cogs, {len(all_commands)} commands")
    print("=" * 70)

    print("\n cogs ")

    seen_cog_names: set[str] = set()
    for cog in all_cogs:
        name = type(cog).__name__
        qn = cog.qualified_name

        if qn in seen_cog_names:
            fail(f"Cog `{qn}` name collision (loaded twice)")
        seen_cog_names.add(qn)

        if not cog.description and "owner" not in qn.lower():
            skip(f"Cog `{qn}` has no description")

        if not callable(getattr(cog, "walk_commands", None)):
            fail(f"Cog `{qn}` has no walk_commands")
        else:
            ok(f"Cog `{qn}` has walk_commands")

        if hasattr(cog, "cog_check"):
            ok(f"Cog `{qn}` defines cog_check")

    ok(f"{len(all_cogs)} cogs enumerated")

    print("\n commands")

    seen_cmds: set[str] = set()
    dupes: list[str] = []

    for cmd in all_commands:
        qn = cmd.qualified_name
        if qn in seen_cmds:
            dupes.append(qn)
        seen_cmds.add(qn)

    if dupes:
        for d in dupes:
            fail(f"Duplicate command `{d}`")
    else:
        ok("No duplicate command names")

    groups = [c for c in all_commands if isinstance(c, Group)]
    ok(f"{len(groups)} groups, {len(all_commands) - len(groups)} leaf commands")

    print("\n command atribs ")

    for cmd in all_commands:
        qn = cmd.qualified_name
        cog_name = cmd.cog_name or "None"

        if not cmd.name:
            fail(f"{cog_name}/{qn}: no name")
        else:
            ok(f"{cog_name}/{qn}: name=`{cmd.name}`")

        cb = cmd.callback
        if cb is None:
            fail(f"{cog_name}/{qn}: no callback")
        elif not callable(cb):
            fail(f"{cog_name}/{qn}: callback not callable")
        else:
            ok(f"{cog_name}/{qn}: callback OK")

        if cmd.help or cmd.description or cmd.short_doc:
            ok(f"{cog_name}/{qn}: has help/description")
        else:
            skip(f"{cog_name}/{qn}: no help text")

        if cmd.aliases:
            ok(f"{cog_name}/{qn}: aliases={cmd.aliases}")
        else:
            skip(f"{cog_name}/{qn}: no aliases")

        checks = cmd.checks
        if checks:
            check_names = [c.__qualname__ for c in checks]
            ok(f"{cog_name}/{qn}: {len(checks)} checks ({', '.join(check_names[:3])}...)")
        else:
            skip(f"{cog_name}/{qn}: no custom checks")

        app_cmd = getattr(cmd, "app_command", None)
        if app_cmd is not None:
            ok(f"{cog_name}/{qn}: hybrid (slash registered)")
        else:
            skip(f"{cog_name}/{qn}: prefix-only")

        if getattr(cmd, "guild_only", False):
            ok(f"{cog_name}/{qn}: guild_only")
        if getattr(cmd, "dm_permission", True) is False:
            ok(f"{cog_name}/{qn}: dm_permission=False")

        if cmd.cog:
            try:
                children = list(cmd.cog.walk_commands())
                if cmd in children:
                    ok(f"{cog_name}/{qn}: reachable via cog.walk_commands()")
                else:
                    fail(f"{cog_name}/{qn}: NOT found in cog.walk_commands()")
            except Exception:
                fail(f"{cog_name}/{qn}: walk_commands raised")

    print("\n perms & checks")

    owner_cmds = []
    admin_cmds = []
    mod_cmds = []
    public_cmds = []

    for cmd in all_commands:
        qn = cmd.qualified_name
        checks = cmd.checks
        has_owner = any("owner" in c.__qualname__.lower() or "is_owner" in c.__qualname__.lower()
                        for c in checks)
        has_admin = any("administrator" in c.__qualname__.lower() or "has_permissions" in c.__qualname__.lower()
                        for c in checks)
        if has_owner:
            owner_cmds.append(qn)
        elif has_admin:
            admin_cmds.append(qn)
        else:
            public_cmds.append(qn)

    ok(f"{len(owner_cmds)} owner-only commands")
    ok(f"{len(admin_cmds)} admin-only commands")
    ok(f"{len(public_cmds)} public commands")

    if owner_cmds:
        ok(f"Owner commands: {', '.join(owner_cmds[:10])}...")
    if admin_cmds:
        ok(f"Admin commands: {', '.join(admin_cmds[:10])}...")

    print("\n help droppdown menu")

    from core.discord.help import BleedHelp, HelpView, _COG_MAP, _detail_embed

    help_sys = bot._bleed_help

    cats = {}
    for cog_name, cog in bot.cogs.items():
        cat = _COG_MAP.get(cog_name, cog_name)
        cats.setdefault(cat, []).extend(list(cog.walk_commands()))

    fake_ctx = MagicMock(spec=discord.ext.commands.Context)
    fake_ctx.author = MagicMock()
    fake_ctx.author.display_name = "TestUser"
    fake_ctx.author.display_avatar = MagicMock()
    fake_ctx.author.display_avatar.url = "https://example.com/av.png"
    fake_ctx.bot = bot
    fake_ctx.prefix = ";"
    fake_ctx.clean_prefix = ";"
    fake_ctx.send = AsyncMock()
    fake_ctx.interaction = None

    try:
        view = HelpView(fake_ctx, cats)
        ok("HelpView created without crash")
    except Exception as e:
        fail(f"HelpView crashed: {e}")

    try:
        home_embed = view._home_embed()
        ok("_home_embed rendered without crash")
    except Exception as e:
        fail(f"_home_embed crashed: {e}")

    for cat_name in list(cats.keys())[:5]:
        try:
            view.cat_embed(cat_name)
            ok(f"cat_embed({cat_name}) rendered")
        except Exception as e:
            fail(f"cat_embed({cat_name}) crashed: {e}")

    for cmd in list(all_commands)[:5]:
        try:
            e = _detail_embed(cmd, fake_ctx)
            ok(f"_detail_embed({cmd.qualified_name}) rendered (title={e.title})")
        except Exception as e:
            fail(f"_detail_embed({cmd.qualified_name}) crashed: {e}")

    from core.discord.views.paginate import PaginateView
    sample_cmds = list(all_commands)[:10]
    sample_embeds = [_detail_embed(c, fake_ctx) for c in sample_cmds]
    try:
        paginator = PaginateView(fake_ctx, sample_embeds)
        ok("PaginateView created without crash")
    except Exception as e:
        fail(f"PaginateView crashed: {e}")

    print("\n" + "=" * 70)
    print(f"RESULTS:  {_results['pass']} passed  |  {_results['fail']} failed  |  {_results['skip']} skipped  |  {_results['total']} total")

    if _results["fail"]:
        print("\nFAILURES:")
        for d in _results["details"]:
            if "FAIL" in d:
                print(f"  {d}")
        sys.exit(1)
    else:
        print("\nALL CHECKS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
