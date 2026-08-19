from __future__ import annotations

import contextlib
import re

import discord
from discord.ext import commands
from discord.ext.commands import group

from core.discord.package import Package


_SPACE = re.compile(r"\s")


class SelfAlias(Package):
    """Personal command shortcuts (per-user)."""

    async def cog_load(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS selfaliases (
                user_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                invoke TEXT NOT NULL,
                command TEXT NOT NULL,
                PRIMARY KEY (user_id, name)
            )
            """
        )
        await super().cog_load()

    def _valid_name(self, name: str) -> bool:
        name = (name or "").strip()
        return bool(name) and not _SPACE.search(name) and name.isprintable()

    @group(
        name="selfalias",
        aliases=["self", "sa", "selfshortcut"],
        description="manage your personal command aliases",
        invoke_without_command=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    async def selfalias(self, ctx):
        return await ctx.send_help(ctx.command)

    @selfalias.command(
        name="add",
        aliases=["create", "set"],
        description="add a personal alias",
        example=",selfalias add hi avatar",
    )
    async def selfalias_add(self, ctx, name: str, *, invoke: str):
        if not self._valid_name(name):
            return await ctx.warn("Alias name must be a single printable word")
        invoke = (invoke or "").strip()
        if not invoke:
            return await ctx.warn("Provide a command to invoke")
        root = invoke.split()[0]
        cmd = self.bot.get_command(root)
        if cmd is None:
            return await ctx.warn(f"Unknown command `{root}`")
        if self.bot.get_command(name.lower()):
            return await ctx.warn(f"`{name}` is already a real command")
        await self.db.execute(
            """
            INSERT INTO selfaliases (user_id, name, invoke, command)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, name) DO UPDATE
            SET invoke = EXCLUDED.invoke, command = EXCLUDED.command
            """,
            ctx.author.id,
            name.lower(),
            invoke,
            cmd.qualified_name,
        )
        return await ctx.success(f"Self alias **`{name.lower()}`** → `{invoke}`")

    @selfalias.command(
        name="remove",
        aliases=["del", "delete", "rm"],
        description="remove a personal alias",
        example=",selfalias remove hi",
    )
    async def selfalias_remove(self, ctx, name: str):
        result = await self.db.execute(
            "DELETE FROM selfaliases WHERE user_id = $1 AND name = $2",
            ctx.author.id,
            name.lower(),
        )
        if result == "DELETE 0":
            return await ctx.warn(f"No self alias **`{name}`**")
        return await ctx.success(f"Removed self alias **`{name.lower()}`**")

    @selfalias.command(
        name="view",
        aliases=["show", "info"],
        description="view what a self alias invokes",
    )
    async def selfalias_view(self, ctx, name: str):
        row = await self.db.fetchrow(
            "SELECT invoke FROM selfaliases WHERE user_id = $1 AND name = $2",
            ctx.author.id,
            name.lower(),
        )
        if not row:
            return await ctx.warn(f"No self alias **`{name}`**")
        inv = row["invoke"] if hasattr(row, "keys") else row[0]
        return await ctx.success(f"**`{name.lower()}`** invokes `{inv}`")

    @selfalias.command(
        name="clear",
        aliases=["reset"],
        description="remove all of your self aliases",
    )
    async def selfalias_clear(self, ctx):
        result = await self.db.execute(
            "DELETE FROM selfaliases WHERE user_id = $1",
            ctx.author.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("You have no self aliases")
        return await ctx.success("Cleared all of your self aliases")

    @selfalias.command(
        name="list",
        aliases=["ls"],
        description="list your personal aliases",
    )
    async def selfalias_list(self, ctx):
        rows = await self.db.fetch(
            """
            SELECT name, invoke FROM selfaliases
            WHERE user_id = $1
            ORDER BY name ASC
            """,
            ctx.author.id,
        )
        if not rows:
            return await ctx.warn("You have no self aliases")
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items

        pages = []
        chunk = 10
        total = len(rows)
        page_count = max(1, (total + chunk - 1) // chunk)
        for start in range(0, total, chunk):
            batch = rows[start : start + chunk]
            lines = []
            for e in batch:
                name = e["name"] if hasattr(e, "keys") else e[0]
                inv = e["invoke"] if hasattr(e, "keys") else e[1]
                lines.append(f"> **`{name}`** · `{inv}`")
            body = chr(10).join(lines) + chr(10) + chr(10) + f"> -# page {start // chunk + 1}/{page_count}"
            container = _ui.Container()
            for attr in ("accent_color", "accent_colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(_ui.TextDisplay("**Your self aliases**"))
            container.add_item(_ui.TextDisplay(body))
            pages.append(layout_from_items([container], timeout=None))
        return await ctx.paginate(pages)


async def setup(bot):
    await bot.add_cog(SelfAlias(bot))
