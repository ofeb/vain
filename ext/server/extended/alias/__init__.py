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
        from ext.server.extended.alias.settings import Settings

        await Settings.ensure_schema(self.db)
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
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items
        from core.discord.views.embed import body as _body

        entries = await self.db.fetch(
            """SELECT alias, command_name, with_parameters FROM aliases WHERE guild_id = $1 ORDER BY alias ASC""",
            ctx.guild.id,
        )
        if not entries:
            return await ctx.warn("No aliases have been added")
        
        seen = set()
        clean = []
        for e in entries:
            alias = str(e["alias"] if hasattr(e, "keys") else e[0]).strip().rstrip(",")
            cmd = str(e["command_name"] if hasattr(e, "keys") else e[1]).strip()
            wp = e["with_parameters"] if hasattr(e, "keys") else (e[2] if len(e) > 2 else False)
            key = alias.lower()
            if not alias or key in seen:
                continue
            seen.add(key)
            wp_tag = " `{}`" if wp else ""
            clean.append((alias, cmd, wp_tag))
        if not clean:
            return await ctx.warn("No aliases have been added")

        pages = []
        chunk = 10
        total = len(clean)
        page_count = max(1, (total + chunk - 1) // chunk)
        for start in range(0, total, chunk):
            batch = clean[start : start + chunk]
            lines = [
                f"-# `{i}.` **{alias}** · `{cmd}`{wp_tag}"
                for i, (alias, cmd, wp_tag) in enumerate(batch, start=start + 1)
            ]
            container = _ui.Container()
            for attr in ("accent_color", "accent_colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(_ui.TextDisplay(f"**Aliases in {ctx.guild.name}**"))
            container.add_item(
                _ui.TextDisplay(f"-# Alias count · {total} · Page {start // chunk + 1}/{page_count}")
            )
            try:
                container.add_item(_ui.Separator(visible=True))
            except Exception:
                pass
            container.add_item(_ui.TextDisplay(chr(10).join(lines)))
            pages.append(layout_from_items([container], timeout=None))
        return await ctx.paginate(pages)


    def _parse_wp_flag(self, payload: str) -> tuple[str, bool]:
        """Parse --with_parameters or --wp flag from payload. Returns (cleaned_payload, with_parameters)."""
        text = (payload or "").strip()
        with_parameters = False
        flag_patterns = ["--with_parameters", "--wp"]
        for flag in flag_patterns:
            if flag in text.lower():
                with_parameters = True
                text = re.sub(r'\s*' + re.escape(flag) + r'\s*', ' ', text, flags=re.IGNORECASE).strip()
                break
        return text, with_parameters

    def _find_command(self, name: str):
        """Find a command by name, supporting group subcommands like 'role add'."""
        cmd = self.bot.get_command(name)
        if cmd:
            return cmd
        parts = name.strip().split()
        if len(parts) >= 2:
            for i in range(len(parts), 0, -1):
                candidate = " ".join(parts[:i])
                cmd = self.bot.get_command(candidate)
                if cmd and hasattr(cmd, "commands"):
                    sub_name = " ".join(parts[i:])
                    sub_cmd = cmd.get_command(sub_name)
                    if sub_cmd:
                        return sub_cmd
                    if sub_name:
                        return cmd
        return None

    @alias.command(
        name="add",
        aliases=["create"],
        description="create an alias for a command (use --wp to allow parameters with {})",
        example=",alias add dep, ban  or  ,alias add role add, r {} --wp",
    )
    @has_permissions(manage_guild=True)
    async def alias_add(self, ctx, *, payload: str):
        """add a command alias - format: <alias>, <command> [--wp]"""
        payload, with_parameters = self._parse_wp_flag(payload)

        if "," not in (payload or ""):
            return await ctx.warn(
                "A **comma** is required between the alias and command\n"
                "> -# **example:** `alias add dep, ban`"
            )
        shortcut, invoke = self._split_alias_command(payload)
        if not shortcut or not invoke:
            return await ctx.warn(
                "Use a comma between alias and command\n"
                "> -# **example:** `alias add dep, ban`"
            )

        if "{}" in invoke and not with_parameters:
            return await ctx.warn(
                "Use **--wp** (or **--with_parameters**) to create an alias with parameters\n"
                "> -# **example:** `alias add sp, purge {} 30 --wp`"
            )

        root = invoke.split()[0]
        cmd = self._find_command(root)
        if cmd is None:
            return await ctx.warn(f"Unknown command `{root}`")
        if self.bot.get_command(shortcut.lower()):
            return await ctx.warn(f"`{shortcut}` is already a real command")
        existing = await self.db.fetchval(
            """SELECT command_name FROM aliases WHERE guild_id = $1 AND alias = $2""",
            ctx.guild.id,
            shortcut.lower(),
        )
        if existing:
            return await ctx.warn(
                f"`{shortcut}` is already an alias for `{existing}`\n"
                "> -# **remove it first** to create a new one"
            )
        await self.db.execute(
            """INSERT INTO aliases (guild_id, command_name, alias, with_parameters) VALUES($1, $2, $3, $4)""",
            ctx.guild.id,
            cmd.qualified_name,
            shortcut.lower(),
            with_parameters,
        )
        wp_note = " (with parameters)" if with_parameters else ""
        return await ctx.success(
            f"Alias added\n> -# **{shortcut.lower()}** → `{cmd.qualified_name}`{wp_note}"
        )

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
        """Parse `<alias>, <command>` (comma required by callers)."""
        text = (raw or "").strip()
        if "," in text:
            left, right = text.split(",", 1)
            return left.strip().rstrip(",").lower(), right.strip()
        parts = text.split(None, 1)
        if len(parts) < 2:
            return (parts[0].strip().rstrip(",").lower() if parts else ""), ""
        return parts[0].strip().rstrip(",").lower(), parts[1].strip()

    @alias_self.command(
        name="add",
        aliases=["create", "set"],
        description="add a personal alias (use --wp to allow parameters with {})",
        example=",alias self add deport, ban  or  ,alias self add sp, purge {} 30 --wp",
    )
    async def alias_self_add(self, ctx, *, payload: str):
        payload, with_parameters = self._parse_wp_flag(payload)

        if "," not in (payload or ""):
            return await ctx.warn(
                "A **comma** is required between the alias and command\n"
                "> -# **example:** `alias self add deport, ban`"
            )
        shortcut, invoke = self._split_alias_command(payload)
        if not self._valid_self_name(shortcut):
            return await ctx.warn(
                "Provide an alias and command\n> -# **example:** `alias self add deport, ban`"
            )
        if not invoke:
            return await ctx.warn(
                "Provide a command after the alias\n> -# **example:** `alias self add deport, ban`"
            )

        if "{}" in invoke and not with_parameters:
            return await ctx.warn(
                "Use **--wp** (or **--with_parameters**) to create an alias with parameters\n"
                "> -# **example:** `alias self add sp, purge {} 30 --wp`"
            )

        root = invoke.split()[0]
        cmd = self._find_command(root)
        if cmd is None:
            return await ctx.warn(f"Unknown command `{root}`")
        if self.bot.get_command(shortcut.lower()):
            return await ctx.warn(f"`{shortcut}` is already a real command")
        from ext.server.extended.alias.settings import Settings

        existing = await Settings.get_selfalias(self.db, ctx.author.id, shortcut.lower())
        if existing:
            return await ctx.warn(
                f"`{shortcut}` is already a self alias for `{existing}`\n"
                "> -# **remove it first** to create a new one"
            )
        await Settings.add_selfalias(
            self.db, ctx.author.id, shortcut.lower(), invoke, cmd.qualified_name, with_parameters
        )
        wp_note = " (with parameters)" if with_parameters else ""
        return await ctx.success(
            f"Self alias added\n> -# **`{shortcut.lower()}`** → `{invoke}`{wp_note}"
        )

    @alias_self.command(
        name="remove",
        aliases=["del", "delete", "rm"],
        description="remove a personal alias",
        example=",alias self remove deport",
    )
    async def alias_self_remove(self, ctx, *, name: str):
        from ext.server.extended.alias.settings import Settings

        result = await Settings.remove_selfalias(self.db, ctx.author.id, name.lower().strip())
        if result == 0:
            return await ctx.warn(f"No self alias **`{name}`**")
        return await ctx.success(f"Removed self alias **`{name.lower().strip()}`**")

    @alias_self.command(
        name="view",
        aliases=["show", "info"],
        description="view what a personal alias invokes",
        example=",alias self view deport",
    )
    async def alias_self_view(self, ctx, *, name: str):
        from ext.server.extended.alias.settings import Settings

        inv = await Settings.get_selfalias(self.db, ctx.author.id, name.lower().strip())
        if not inv:
            return await ctx.warn(f"No self alias **`{name}`**")
        return await ctx.success(f"**`{name.lower().strip()}`** invokes `{inv}`")

    @alias_self.command(
        name="clear",
        aliases=["reset"],
        description="remove all of your personal aliases",
    )
    async def alias_self_clear(self, ctx):
        from ext.server.extended.alias.settings import Settings

        result = await Settings.clear_selfaliases(self.db, ctx.author.id)
        if result == 0:
            return await ctx.warn("You have no personal aliases")
        return await ctx.success("Cleared all of your personal aliases")

    @alias_self.command(
        name="list",
        aliases=["ls"],
        description="list your personal aliases",
    )
    async def alias_self_list(self, ctx):
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items
        from ext.server.extended.alias.settings import Settings

        raw = await Settings.fetch_selfaliases(self.db, ctx.author.id)
        if not raw:
            return await ctx.warn("You have no personal aliases")
        clean = []
        seen = set()
        for e in raw:
            name = str(e["name"]).strip().rstrip(",")
            inv = str(e["invoke"]).strip()
            wp = e.get("with_parameters", False)
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            wp_tag = " `{}`" if wp else ""
            clean.append((name, inv, wp_tag))
        pages = []
        chunk = 10
        total = len(clean)
        page_count = max(1, (total + chunk - 1) // chunk)
        for start in range(0, total, chunk):
            batch = clean[start : start + chunk]
            lines = [
                f"-# `{i}.` **{name}** · `{inv}`{wp_tag}"
                for i, (name, inv, wp_tag) in enumerate(batch, start=start + 1)
            ]
            container = _ui.Container()
            for attr in ("accent_color", "accent_colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(_ui.TextDisplay(f"**Your self aliases**"))
            container.add_item(
                _ui.TextDisplay(f"-# Alias count · {total} · Page {start // chunk + 1}/{page_count}")
            )
            try:
                container.add_item(_ui.Separator(visible=True))
            except Exception:
                pass
            container.add_item(_ui.TextDisplay(chr(10).join(lines)))
            pages.append(layout_from_items([container], timeout=None))
        return await ctx.paginate(pages)
