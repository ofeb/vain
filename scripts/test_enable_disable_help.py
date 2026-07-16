"""Focused tests for enable/disable command/module + help usage/example."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# lightweight stubs if missing
if "asyncpg" not in sys.modules:
    asyncpg = types.ModuleType("asyncpg")
    asyncpg.UniqueViolationError = type("UniqueViolationError", (Exception,), {})
    asyncpg.exceptions = types.ModuleType("asyncpg.exceptions")
    asyncpg.exceptions.UniqueViolationError = asyncpg.UniqueViolationError
    asyncpg.exceptions.InvalidCatalogNameError = type("InvalidCatalogNameError", (Exception,), {})
    asyncpg.Record = type("Record", (), {})
    asyncpg.Pool = type("Pool", (), {})
    asyncpg.Connection = type("Connection", (), {})

    async def _create_pool(*a, **k):
        return None

    asyncpg.create_pool = _create_pool
    sys.modules["asyncpg"] = asyncpg
    sys.modules["asyncpg.exceptions"] = asyncpg.exceptions

for mod in ("redis", "redis.asyncio", "jishaku", "fast_string_match", "PIL", "yt_dlp", "orjson", "loguru", "humanize", "xxhash", "pytz"):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import core.patches.cmd  # noqa: F401
import discord
from discord.ext import commands
from discord.ext.commands import CommandError

from core.discord import help as H

# Import command modules directly to avoid loading entire server package
import importlib.util

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

_en_cmd = _load(
    "vain_test_enable_cmd",
    ROOT / "ext/server/extended/enable/command/command.py",
)
_dis_cmd = _load(
    "vain_test_disable_cmd",
    ROOT / "ext/server/extended/disable/command/command.py",
)
_en_mod = _load(
    "vain_test_enable_mod",
    ROOT / "ext/server/extended/enable/module/module.py",
)
_dis_mod = _load(
    "vain_test_disable_mod",
    ROOT / "ext/server/extended/disable/module/module.py",
)
CommandEnableCommands = _en_cmd.CommandEnableCommands
CommandDisableCommands = _dis_cmd.CommandDisableCommands
ModuleEnableCommands = _en_mod.ModuleEnableCommands
ModuleDisableCommands = _dis_mod.ModuleDisableCommands

PASS = 0
FAIL = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {msg}")


def _record(**kw):
    r = MagicMock()
    for k, v in kw.items():
        setattr(r, k, v)
    return r


class FakeDB:
    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self.module_rows: dict[tuple, list] = {}
        self.executes: list = []

    async def fetchrow(self, sql, *args):
        sql_l = sql.lower()
        if "disabled_commands" in sql_l:
            key = (args[0], args[1])
            data = self.rows.get(key)
            if not data:
                return None
            return _record(
                guild_id=args[0],
                command=args[1],
                object_ids=list(data["object_ids"]),
                object_types=list(data["object_types"]),
            )
        if "disabled_modules" in sql_l:
            key = (args[0], args[1])
            ids = self.module_rows.get(key)
            if ids is None:
                return None
            return _record(guild_id=args[0], module=args[1], channel_ids=list(ids))
        return None

    async def fetchval(self, sql, *args):
        sql_l = sql.lower()
        if "disabled_modules" in sql_l and "channel_ids" in sql_l:
            key = (args[0], args[1])
            ids = self.module_rows.get(key)
            return list(ids) if ids is not None else None
        return None

    async def fetch(self, sql, *args):
        sql_l = sql.lower()
        if "disabled_commands" in sql_l:
            out = []
            for (gid, cmd), data in self.rows.items():
                if gid == args[0]:
                    out.append(
                        _record(
                            command=cmd,
                            object_ids=list(data["object_ids"]),
                            object_types=list(data["object_types"]),
                        )
                    )
            return out
        if "disabled_modules" in sql_l:
            out = []
            for (gid, mod), ids in self.module_rows.items():
                if gid == args[0]:
                    out.append(_record(module=mod, channel_ids=list(ids)))
            return out
        return []

    async def execute(self, sql, *args):
        self.executes.append((sql, args))
        sql_l = sql.lower()
        if "delete from disabled_commands" in sql_l:
            self.rows.pop((args[0], args[1]), None)
            return
        if "delete from disabled_modules" in sql_l:
            self.module_rows.pop((args[0], args[1]), None)
            return
        if "insert into disabled_commands" in sql_l:
            self.rows[(args[0], args[1])] = {
                "object_ids": list(args[2]),
                "object_types": list(args[3]),
            }
            return
        if "update disabled_commands" in sql_l:
            # SET object_ids, object_types WHERE guild, command
            self.rows[(args[2], args[3])] = {
                "object_ids": list(args[0]),
                "object_types": list(args[1]),
            }
            return
        if "insert into disabled_modules" in sql_l:
            self.module_rows[(args[0], args[1])] = list(args[2])
            return
        if "update disabled_modules" in sql_l:
            self.module_rows[(args[1], args[2])] = list(args[0])
            return


def _make_ctx(db: FakeDB, bot_commands=None):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 500001
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = 100001
    ch.name = "general"
    ch.mention = "<#100001>"
    ch.guild = guild
    guild.text_channels = [ch]
    guild.channels = [ch]
    guild.get_channel = lambda i: ch if i == ch.id else None
    guild.get_member = lambda i: None

    member = MagicMock(spec=discord.Member)
    member.id = 1001
    member.mention = "<@1001>"
    member.display_avatar = MagicMock(url="https://x")

    bot = MagicMock()
    bot.color = 0x5865F2
    bot.invalidate_command_access_cache = AsyncMock()

    # real snipe command object
    @commands.command(name="snipe")
    async def snipe_cmd(ctx):
        pass

    bot.get_command = lambda name: snipe_cmd if str(name).lower() == "snipe" else None
    bot.walk_commands = lambda: [snipe_cmd]
    bot.commands = [snipe_cmd]
    if not hasattr(bot, "command_list"):
        bot.command_list = {"snipe": snipe_cmd}

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = member
    ctx.channel = ch
    ctx.bot = bot
    ctx.prefix = ","
    ctx.clean_prefix = ","
    ctx.success = AsyncMock()
    ctx.fail = AsyncMock()
    ctx.warn = AsyncMock()
    ctx.send_help = AsyncMock()
    ctx.paginate = AsyncMock()
    ctx.command = None
    return ctx, ch, snipe_cmd


async def test_enablecommand_flows():
    print("\n=== enablecommand ===")
    db = FakeDB()
    pkg = CommandEnableCommands.__new__(CommandEnableCommands)
    pkg.bot = MagicMock(color=0x5865F2, db=db)
    ctx, ch, snipe = _make_ctx(db)

    # already enabled server-wide
    try:
        await CommandEnableCommands.enablecommand(pkg, ctx, payload="snipe")
        fail("expected already-enabled server error")
    except CommandError as e:
        if "already been **enabled** to use in this server" in str(e):
            ok("enablecommand snipe → already enabled server-wide")
        else:
            fail(f"wrong msg: {e}")

    # disabled in channel, enable server-wide
    db.rows[(ctx.guild.id, "snipe")] = {
        "object_ids": [ch.id],
        "object_types": ["channel"],
    }
    await CommandEnableCommands.enablecommand(pkg, ctx, payload="snipe")
    if (ctx.guild.id, "snipe") not in db.rows:
        ok("enablecommand snipe clears disables server-wide")
    else:
        fail("server-wide enable did not delete row")
    ctx.success.assert_awaited()
    assert "this server" in ctx.success.await_args.args[0]

    # re-disable in channel then enable in channel via resolver bypass
    # (TextChannelConverter needs a live discord state; test core path directly)
    db.rows[(ctx.guild.id, "snipe")] = {
        "object_ids": [ch.id],
        "object_types": ["channel"],
    }
    ctx.success.reset_mock()
    # monkeypatch resolver to return channel target
    async def _resolve_ch(ctx_, *, payload):
        return ch, snipe

    pkg._resolve_target_and_command = _resolve_ch  # type: ignore
    await CommandEnableCommands.enablecommand(pkg, ctx, payload=f"#general snipe")
    if (ctx.guild.id, "snipe") not in db.rows:
        ok("enablecommand #channel snipe removes channel disable")
    else:
        fail(f"channel enable left row: {db.rows}")

    # already enabled in channel
    try:
        await CommandEnableCommands.enablecommand(pkg, ctx, payload=f"#general snipe")
        fail("expected already-enabled channel error")
    except CommandError as e:
        if "already **enabled** in" in str(e):
            ok("enablecommand #channel snipe → already enabled in channel")
        else:
            fail(f"wrong channel msg: {e}")

    # all subcommand
    db.rows[(ctx.guild.id, "snipe")] = {
        "object_ids": [ch.id, 99],
        "object_types": ["channel", "member"],
    }
    await CommandEnableCommands.enablecommand_all(pkg, ctx, command=snipe)
    if (ctx.guild.id, "snipe") not in db.rows:
        ok("enablecommand all snipe clears everything")
    else:
        fail("all did not clear")


async def test_disablecommand_flows():
    print("\n=== disablecommand ===")
    db = FakeDB()
    pkg = CommandDisableCommands.__new__(CommandDisableCommands)
    pkg.bot = MagicMock(color=0x5865F2, db=db)
    ctx, ch, snipe = _make_ctx(db)

    await CommandDisableCommands.disablecommand(pkg, ctx, payload="snipe")
    row = db.rows.get((ctx.guild.id, "snipe"))
    if row and ch.id in row["object_ids"]:
        ok("disablecommand snipe disables server-wide (all text channels)")
    else:
        fail(f"server disable failed: {db.rows}")

    try:
        await CommandDisableCommands.disablecommand(pkg, ctx, payload="snipe")
        fail("expected already disabled server")
    except CommandError as e:
        if "already been **disabled** in this server" in str(e):
            ok("disablecommand snipe → already disabled server-wide")
        else:
            fail(f"wrong msg: {e}")

    # clear and disable channel only
    db.rows.clear()

    async def _resolve_ch(ctx_, *, payload):
        return ch, snipe

    pkg._resolve_target_and_command = _resolve_ch  # type: ignore
    await CommandDisableCommands.disablecommand(pkg, ctx, payload="#general snipe")
    row = db.rows.get((ctx.guild.id, "snipe"))
    if row and row["object_ids"] == [ch.id]:
        ok("disablecommand #channel snipe")
    else:
        fail(f"channel disable failed: {row}")

    try:
        await CommandDisableCommands.disablecommand(pkg, ctx, payload="#general snipe")
        fail("expected already disabled channel")
    except CommandError as e:
        if "already **disabled** in" in str(e):
            ok("disablecommand #channel snipe → already disabled in channel")
        else:
            fail(f"wrong msg: {e}")


async def test_module_flows():
    print("\n=== enable/disable module ===")
    db = FakeDB()
    en = ModuleEnableCommands.__new__(ModuleEnableCommands)
    en.bot = MagicMock(color=0x5865F2, db=db)
    dis = ModuleDisableCommands.__new__(ModuleDisableCommands)
    dis.bot = MagicMock(color=0x5865F2, db=db)
    ctx, ch, _ = _make_ctx(db)

    # ModuleConverter accepts unknown module keys (returns normalized)
    await ModuleDisableCommands.disablemodule(dis, ctx, payload="server")
    if db.module_rows.get((ctx.guild.id, "server")) == [ch.id]:
        ok("disablemodule server (server-wide via all text channels)")
    else:
        # server-wide uses all text channel ids
        ids = db.module_rows.get((ctx.guild.id, "server"))
        if ids and ch.id in ids:
            ok("disablemodule server server-wide")
        else:
            fail(f"disablemodule server failed: {db.module_rows}")

    try:
        await ModuleEnableCommands.enablemodule(en, ctx, payload="server")
        # should succeed clearing
        if (ctx.guild.id, "server") not in db.module_rows:
            ok("enablemodule server clears disables")
        else:
            fail("enablemodule server left rows")
    except CommandError as e:
        fail(f"enablemodule server error: {e}")

    try:
        await ModuleEnableCommands.enablemodule(en, ctx, payload="server")
        fail("expected already enabled")
    except CommandError as e:
        if "already been **enabled** to use in this server" in str(e):
            ok("enablemodule server → already enabled")
        else:
            fail(f"wrong msg: {e}")

    db.module_rows[(ctx.guild.id, "server")] = [ch.id]

    async def _resolve_mod(ctx_, *, payload):
        return "server", ch

    en._resolve_module_and_channel = _resolve_mod  # type: ignore
    try:
        await ModuleEnableCommands.enablemodule(en, ctx, payload="#general server")
        if (ctx.guild.id, "server") not in db.module_rows:
            ok("enablemodule #channel server")
        else:
            fail("channel enable left row")
    except CommandError as e:
        fail(f"channel enable error: {e}")

    try:
        await ModuleEnableCommands.enablemodule(en, ctx, payload="#general server")
        fail("expected already enabled channel")
    except CommandError as e:
        if "already **enabled** in" in str(e):
            ok("enablemodule #channel → already enabled")
        else:
            fail(f"wrong msg: {e}")


def test_help_system():
    print("\n=== help usage/example ===")

    @commands.group(
        name="enablecommand",
        invoke_without_command=True,
        usage="[channel or member] <command>",
        example=",enablecommand #general snipe",
    )
    async def enablecommand(ctx, *, args: str = None):
        pass

    @enablecommand.command(name="list")
    async def enablecommand_list(ctx):
        pass

    @enablecommand.command(name="all", usage="<command>", example=",enablecommand all snipe")
    async def enablecommand_all(ctx, *, command):
        pass

    @commands.group(name="context", invoke_without_command=True)
    async def context(ctx):
        pass

    @context.group(name="self", invoke_without_command=True)
    async def context_self(ctx):
        pass

    @context_self.group(name="color", invoke_without_command=True)
    async def context_self_color(ctx):
        pass

    @context_self_color.command(name="list", example=",context self color list")
    async def context_self_color_list(ctx):
        pass

    @context_self_color.command(name="base", example=",context self color base #2A2B2F")
    async def context_self_color_base(ctx, color: str = None):
        pass

    @commands.command(name="ping")
    async def ping(ctx):
        pass

    prefix = ","

    # no-arg commands: usage only, no example, no duplication
    for cmd in (enablecommand_list, context_self_color_list, ping):
        block = H._usage_block(cmd, prefix)
        if "Example:" in block:
            fail(f"{cmd.qualified_name} should not show Example")
        else:
            ok(f"{cmd.qualified_name} usage-only (no example)")
        if block.count(cmd.qualified_name) > 1 and f"{cmd.qualified_name} {cmd.qualified_name}" in block:
            fail(f"{cmd.qualified_name} duplicated in usage block: {block}")
        else:
            ok(f"{cmd.qualified_name} no duplicated name")
        if "Syntax:" in block:
            fail(f"{cmd.qualified_name} still says Syntax")
        elif "Usage:" in block:
            ok(f"{cmd.qualified_name} uses Usage label")
        else:
            fail(f"{cmd.qualified_name} missing Usage")

    # self path preserved
    syn = H._syntax(context_self_color_base, prefix)
    if "context self color base" in syn and "context color base context" not in syn:
        ok("context self color path preserved")
    else:
        fail(f"self path broken: {syn}")

    ex = H._example(context_self_color_base, prefix)
    if ex == ",context self color base #2A2B2F":
        ok("context self color base example clean")
    else:
        fail(f"bad self example: {ex!r}")

    # enablecommand example
    ex = H._example(enablecommand, prefix)
    if ex == ",enablecommand #general snipe":
        ok("enablecommand example clean")
    else:
        fail(f"bad enablecommand example: {ex!r}")

    # list never duplicates
    ex = H._example(enablecommand_list, prefix)
    if ex is None:
        ok("enablecommand list example is None")
    else:
        fail(f"list example should be None, got {ex!r}")

    # event commands removed from server package source
    server_init = (ROOT / "ext/server/__init__.py").read_text(encoding="utf-8")
    if "EventEnableCommands" not in server_init and "EventDisableCommands" not in server_init:
        ok("enableevent/disableevent removed from Server package")
    else:
        fail("event packages still imported in ext/server/__init__.py")


async def main():
    print("enable/disable + help tests")
    test_help_system()
    await test_enablecommand_flows()
    await test_disablecommand_flows()
    await test_module_flows()
    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL == 0


if __name__ == "__main__":
    ok_all = asyncio.run(main())
    sys.exit(0 if ok_all else 1)
