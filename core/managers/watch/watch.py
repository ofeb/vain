"""hot reload watcher for cog files.
watches dirs and reloads cogs on file change.
wraps watchfiles to dispatch to discord.py"""

from __future__ import annotations

import asyncio, logging, os, sys
from functools import wraps
from pathlib import Path
from typing import List, Optional, Union, TYPE_CHECKING

import discord
from watchfiles import Change, awatch

if TYPE_CHECKING:
    from core.bleed import Bleed

try:
    from discord.ext import commands
except ImportError:
    from nextcord.ext import commands

log = logging.getLogger("watch")
log.addHandler(logging.NullHandler())
log.propagate = False


async def _auto_commit() -> None:
    return


class Watcher:
    """watches cog dirs and reloads on change.
    auto detects added removed and modified py files.
    pass list of dirs or single string"""

    def __init__(
        self,
        client: Bleed,
        path: Union[str, List[str]] = "ext",
        debug: bool = True,
        loop: asyncio.BaseEventLoop = None,
        preload: bool = False,
        colors: bool = True,
    ):
        self.client = client
        self.path = path
        self.debug = debug
        self.loop = loop
        self.started = False
        self.preload = preload

        if colors:
            self.END = "\33[0m"
            self.BOLD = "\33[1m"
            self.GREEN = "\33[32m"
            self.RED = "\33[31m"
        else:
            self.END = self.BOLD = self.GREEN = self.RED = ""

        watch_log = logging.getLogger("watch")
        watch_log.setLevel(logging.INFO)
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        watch_log.addHandler(h)

    @staticmethod
    def _cog_name(path: str) -> str:
        return os.path.normpath(path).split(os.sep)[-1][:-3]

    def _paths_str(self) -> str:
        if isinstance(self.path, list):
            return ", ".join(self.path)
        return self.path

    def _dotted(self, path: str, directory: Optional[str] = None) -> str:
        parts = os.path.normpath(path).split(os.sep)
        base = (directory or self.path)
        root = base.split("/")[0] if isinstance(base, str) else base[0].split("/")[0]
        try:
            idx = list(reversed(parts)).index(root) + 1
        except ValueError:
            raise ValueError("use forward slashes in path param")
        return ".".join(parts[-idx:-1])

    def _exists(self) -> bool:
        paths = [self.path] if isinstance(self.path, str) else self.path
        return all(Path(Path.cwd() / p).exists() for p in paths)

    async def _watch_path(self, path: str) -> None:
        if not self._exists():
            return
        try:
            async for changes in awatch(Path.cwd() / path):
                for change, fpath in sorted(changes, reverse=True):
                    name = self._cog_name(fpath)
                    dotted = self._dotted(fpath, path)
                    cog = f"{dotted}.{name}" if dotted else f"{path}.{name}"
                    if change == Change.deleted:
                        if cog in self.client.extensions:
                            await self._unload(cog)
                    elif change == Change.added:
                        if cog not in self.client.extensions:
                            await self._load(cog)
                    elif change == Change.modified:
                        try:
                            await self._reload(cog)
                        except Exception:
                            await self._load(cog)
                await _auto_commit()
        except FileNotFoundError:
            return

    async def _run(self) -> None:
        paths = [self.path] if isinstance(self.path, str) else self.path
        while self._exists():
            for p in paths:
                await self._watch_path(p)

    async def _load(self, cog: str) -> None:
        try:
            await self.client.load_extension(cog)
            log.info(f"{self.BOLD}{self.GREEN}[loaded]{self.END} {cog}")
        except commands.ExtensionAlreadyLoaded:
            pass
        except Exception as e:
            self._err(e)

    async def _unload(self, cog: str) -> None:
        try:
            await self.client.unload_extension(cog)
            log.info(f"{self.BOLD}{self.RED}[unloaded]{self.END} {cog}")
        except Exception as e:
            self._err(e)

    async def _reload(self, cog: str) -> None:
        try:
            await self.client.reload_extension(cog)
            log.info(f"{self.BOLD}{self.GREEN}[reloaded]{self.END} {cog}")
        except commands.ExtensionNotLoaded:
            await self._load(cog)
        except Exception as e:
            self._err(e)

    @staticmethod
    def _err(exc: Exception) -> None:
        if isinstance(exc, (commands.ExtensionError, SyntaxError)):
            logging.exception(exc)

    async def start(self) -> None:
        """start watching for file changes"""
        if self.started:
            return
        paths = [self.path] if isinstance(self.path, str) else self.path
        for p in paths:
            full = Path(Path.cwd() / p)
            if not full.exists():
                try:
                    full.mkdir(parents=True, exist_ok=True)
                    log.warning(f"created missing dir: {full}")
                except Exception as e:
                    log.error(f"cant create {full}: {e}")
        if not self._exists():
            log.error(f"dirs missing: {self._paths_str()}")
            return
        log.info(f"watching {self.BOLD}{self._paths_str()}{self.END}")
        if self.preload:
            await self._preload()
        if self.debug and __debug__:
            if self.loop is None:
                self.loop = asyncio.get_event_loop()
            self.loop.create_task(self._run())
            self.started = True

    async def _preload(self) -> None:
        log.info("preloading cogs")
        paths = [self.path] if isinstance(self.path, str) else self.path
        for p in paths:
            for f in Path(Path.cwd() / p).rglob("*.py"):
                dotted = self._dotted(str(f), p)
                await self._load(f"{dotted}.{f.stem}" if dotted else f"{p}.{f.stem}")
