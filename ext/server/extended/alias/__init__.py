from __future__ import annotations

import contextlib
import re

from discord.ext.commands import group, CommandError
from core.discord.package import Package
from core.managers.converters import CommandConverter
from core.managers.permissions import has_permissions

_SPACE = re.compile(r"\s")


class AliasCommands(Package):
    """command alias management (server + personal)"""

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

    @group(
        name="alias",
        aliases=["shortcut"],
        description="create your own shortcuts for commands",
        invoke_without_command=True,
    )
    async def alias(self, ctx):
        """alias group help"""
        return await ctx.send_help(ctx.command)

    @alias.command(
        name="view",
        aliases=["show"],
        description="view command execution for alias",
        example=",alias view hi",
    )
    @has_permissions(manage_guild=True)
    async def alias_view(self, ctx, *, shortcut: str):
        """view alias target"""
        cmd_name = await self.db.fetchval(
            """SELECT command_name FROM aliases WHERE guild_id = $1 AND alias = $2""",
            ctx.guild.id,
            shortcut,
        )
        if not cmd_name:
            raise CommandError(f"no alias found for `{shortcut[:25]}`")
        cmd = self.bot.get_command(cmd_name)
        name = cmd.qualified_name if cmd else cmd_name
        return await ctx.normal(f"**{shortcut}** runs `{name}`", emoji="ℹ️")

    @alias.command(
        name="removeall",
        aliases=["delall", "deleteeall"],
        description="remove an alias for command",
        example=",alias removeall avatar",
    )
    @has_permissions(manage_guild=True)
    async def alias_removeall(self, ctx, *, command: CommandConverter):
        """remove every alias for command"""
        await self.db.execute(
            """DELETE FROM aliases WHERE command_name = $1 AND guild_id = $2""",
            command.qualified_name,
            ctx.guild.id,
        )
        return await ctx.success(f"Removed aliases for `{command.qualified_name}`")

    @alias.command(
        name="list",
        description="list every alias for all commands",
    )
    @has_permissions(manage_guild=True)
    async def alias_list(self, ctx):
        """list all server aliases"""
        entries = await self.db.fetch(
            """SELECT alias, command_name FROM aliases WHERE guild_id = $1 ORDER BY alias ASC""",
            ctx.guild.id,
        )
        if not entries:
            return await ctx.warn("No aliases have been added")
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items

        pages = []
        chunk = 10
        total = len(entries)
        page_count = max(1, (total + chunk - 1) // chunk)
        for start in range(0, total, chunk):
            batch = entries[start : start + chunk]
            lines = []
            for e in batch:
                alias = e["alias"] if hasattr(e, "keys") else getattr(e, "alias", e[0])
                cmd = e["command_name"] if hasattr(e, "keys") else getattr(e, "command_name", e[1])
                lines.append(f"> **`{alias}`** · `{cmd}`")
            body = chr(10).join(lines) + chr(10) + chr(10) + f"> -# page {start // chunk + 1}/{page_count}"
            container = _ui.Container()
            for attr in ("accent_color", "accent_colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(_ui.TextDisplay("**Server aliases**"))
            container.add_item(_ui.TextDisplay(body))
            pages.append(layout_from_items([container], timeout=None))
        return await ctx.paginate(pages)

    @alias.command(
        name="add",
        aliases=["create"],
        description="create an alias for command",
        example=",alias add hi avatar",
    )
    @has_permissions(manage_guild=True)
    async def alias_add(self, ctx, shortcut: str, *, command: CommandConverter):
        """add a command alias"""
        await self.db.execute(
            """INSERT INTO aliases (guild_id, command_name, alias) VALUES($1, $2, $3) ON CONFLICT(guild_id, alias) DO UPDATE SET command_name = excluded.command_name""",
            ctx.guild.id,
            command.qualified_name,
            shortcut,
        )
        return await ctx.success(f"Alias added\n> -# **{shortcut}** → `{command.qualified_name}`")

    @alias.command(
        name="remove",
        aliases=["del", "delete"],
        description="remove an alias for command",
        example=",alias remove hi",
    )
    @has_permissions(manage_guild=True)
    async def alias_remove(self, ctx, *, shortcut: str):
        """delete an alias"""
        await self.db.execute(
            """DELETE FROM aliases WHERE guild_id = $1 AND alias = $2""",
            ctx.guild.id,
            shortcut,
        )
        return await ctx.success(f"Removed alias\n> -# **`{shortcut}`**")

    @alias.command(
        name="reset",
        aliases=["clear"],
        description="reset every alias for all commands. this can't be undone",
    )
    @has_permissions(manage_guild=True)
    async def alias_reset(self, ctx):
        """wipe all aliases"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Clear **all** command aliases for this server? "
            "This action **can't be undone**."
        )
        if not ok:
            return await ctx.warn("Cancelled\n> -# **alias reset was cancelled**")
        await self.db.execute(
            """DELETE FROM aliases WHERE guild_id = $1""", ctx.guild.id
        )
        return await ctx.success(
            "All aliases cleared\n> -# **this action can't be undone**"
        )

    

    @alias.group(
        name="self",
        aliases=["selfalias", "sa", "personal"],
        description="manage your personal command aliases",
        invoke_without_command=True,
    )
    async def alias_self(self, ctx):
        return await ctx.send_help(ctx.command)

    def _valid_self_name(self, name: str) -> bool:
        name = (name or "").strip()
        return bool(name) and not _SPACE.search(name) and name.isprintable()

    def _split_alias_command(self, raw: str) -> tuple[str, str]:
        """Parse `<alias>, <command>` or `<alias> <command>`."""
        text = (raw or "").strip()
        if "," in text:
            left, right = text.split(",", 1)
            return left.strip(), right.strip()
        parts = text.split(None, 1)
        if len(parts) < 2:
            return parts[0] if parts else "", ""
        return parts[0].strip(), parts[1].strip()

    @alias_self.command(
        name="add",
        aliases=["create", "set"],
        description="add a personal alias",
        example=",alias self add deport, ban",
    )
    async def alias_self_add(self, ctx, *, payload: str):
        shortcut, invoke = self._split_alias_command(payload)
        if not self._valid_self_name(shortcut):
            return await ctx.warn(
                "Provide an alias and command\n> -# **example:** `alias self add deport, ban`"
            )
        if not invoke:
            return await ctx.warn(
                "Provide a command after the alias\n> -# **example:** `alias self add deport, ban`"
            )
        root = invoke.split()[0]
        cmd = self.bot.get_command(root)
        if cmd is None:
            return await ctx.warn(f"Unknown command `{root}`")
        if self.bot.get_command(shortcut.lower()):
            return await ctx.warn(f"`{shortcut}` is already a real command")
        await self.db.execute(
            """
            INSERT INTO selfaliases (user_id, name, invoke, command)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, name) DO UPDATE
            SET invoke = EXCLUDED.invoke, command = EXCLUDED.command
            """,
            ctx.author.id,
            shortcut.lower(),
            invoke,
            cmd.qualified_name,
        )
        return await ctx.success(
            f"Self alias added\n> -# **`{shortcut.lower()}`** → `{invoke}`"
        )

    @alias_self.command(
        name="remove",
        aliases=["del", "delete", "rm"],
        description="remove a personal alias",
        example=",alias self remove deport",
    )
    async def alias_self_remove(self, ctx, *, name: str):
        result = await self.db.execute(
            "DELETE FROM selfaliases WHERE user_id = $1 AND name = $2",
            ctx.author.id,
            name.lower().strip(),
        )
        if result == "DELETE 0":
            return await ctx.warn(f"No self alias **`{name}`**")
        return await ctx.success(f"Removed self alias **`{name.lower().strip()}`**")

    @alias_self.command(
        name="view",
        aliases=["show", "info"],
        description="view what a personal alias invokes",
        example=",alias self view deport",
    )
    async def alias_self_view(self, ctx, *, name: str):
        row = await self.db.fetchrow(
            "SELECT invoke FROM selfaliases WHERE user_id = $1 AND name = $2",
            ctx.author.id,
            name.lower().strip(),
        )
        if not row:
            return await ctx.warn(f"No self alias **`{name}`**")
        inv = row["invoke"] if hasattr(row, "keys") else row[0]
        return await ctx.success(f"**`{name.lower().strip()}`** invokes `{inv}`")

    @alias_self.command(
        name="clear",
        aliases=["reset"],
        description="remove all of your personal aliases",
    )
    async def alias_self_clear(self, ctx):
        result = await self.db.execute(
            "DELETE FROM selfaliases WHERE user_id = $1",
            ctx.author.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("You have no personal aliases")
        return await ctx.success("Cleared all of your personal aliases")

    @alias_self.command(
        name="list",
        aliases=["ls"],
        description="list your personal aliases",
    )
    async def alias_self_list(self, ctx):
        rows = await self.db.fetch(
            """
            SELECT name, invoke FROM selfaliases
            WHERE user_id = $1
            ORDER BY name ASC
            """,
            ctx.author.id,
        )
        if not rows:
            return await ctx.warn("You have no personal aliases")
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
