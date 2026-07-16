from __future__ import annotations

from typing import Optional

from discord import Embed, TextChannel
from discord.ext.commands import (
    BadArgument,
    CommandError,
    TextChannelConverter,
    group,
)

from core.discord.package import Package
from core.managers.converters import ModuleConverter
from core.managers.permissions import has_permissions


class ModuleDisableCommands(Package):
    """disable modules per channel or server-wide"""

    async def _resolve_module_and_channel(
        self,
        ctx,
        *,
        payload: str,
    ) -> tuple[str, Optional[TextChannel]]:
        """Parse ``<module> [channel]`` or ``[channel] <module>``."""
        text = (payload or "").strip()
        if not text:
            raise CommandError("provide a module to disable")

        parts = text.split()
        channel: Optional[TextChannel] = None
        module_text = text

        if len(parts) >= 2:
            try:
                channel = await TextChannelConverter().convert(ctx, parts[0])
                module_text = " ".join(parts[1:])
            except (BadArgument, CommandError):
                try:
                    channel = await TextChannelConverter().convert(ctx, parts[-1])
                    module_text = " ".join(parts[:-1])
                except (BadArgument, CommandError):
                    channel = None
                    module_text = text

        module = await ModuleConverter().convert(ctx, module_text)
        return module, channel

    @group(
        name="disablemodule",
        description="Disable a module in a channel or server-wide",
        usage="[channel] <module>",
        example=",disablemodule #general server",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disablemodule(self, ctx, *, payload: str = None):
        """block a module in a channel or everywhere"""
        if not payload:
            return await ctx.send_help(ctx.command)

        module, channel = await self._resolve_module_and_channel(ctx, payload=payload)
        label = module.replace("_", " ")

        row = await self.db.fetchrow(
            """SELECT * FROM disabled_modules WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id,
            module,
        )

        if channel is None:
            all_ids = [c.id for c in ctx.guild.text_channels]
            if not all_ids:
                raise CommandError("this server has no text channels to disable in")
            if row:
                ids = list(row.channel_ids)
                if all(cid in ids for cid in all_ids):
                    raise CommandError(
                        f"`{label}` has already been **disabled** in this server"
                    )
                fresh = [cid for cid in all_ids if cid not in ids]
                ids.extend(fresh)
                await self.db.execute(
                    """UPDATE disabled_modules
                       SET channel_ids = $1
                       WHERE guild_id = $2 AND module = $3""",
                    ids,
                    ctx.guild.id,
                    module,
                )
            else:
                await self.db.execute(
                    """INSERT INTO disabled_modules (guild_id, module, channel_ids)
                       VALUES($1, $2, $3)""",
                    ctx.guild.id,
                    module,
                    all_ids,
                )
            return await ctx.success(f"**disabled** `{label}` in this server")

        if row:
            ids = list(row.channel_ids)
            if channel.id in ids:
                raise CommandError(
                    f"`{label}` was already **disabled** in {channel.mention}"
                )
            ids.append(channel.id)
            await self.db.execute(
                """UPDATE disabled_modules
                   SET channel_ids = $1
                   WHERE guild_id = $2 AND module = $3""",
                ids,
                ctx.guild.id,
                module,
            )
        else:
            await self.db.execute(
                """INSERT INTO disabled_modules (guild_id, module, channel_ids)
                   VALUES($1, $2, $3)""",
                ctx.guild.id,
                module,
                [channel.id],
            )
        return await ctx.success(f"**disabled** `{label}` in {channel.mention}")

    @disablemodule.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of disabled modules in guild",
    )
    @has_permissions(manage_channels=True)
    async def disablemodule_list(self, ctx):
        """list disabled modules"""
        data = await self.db.fetch(
            """SELECT module, channel_ids FROM disabled_modules WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not data:
            raise CommandError("no modules have been disabled")
        lines = []
        for row in data:
            label = row.module.replace("_", " ")
            for cid in row.channel_ids or []:
                ch = ctx.guild.get_channel(cid)
                if ch:
                    lines.append(f"**{label}** — ({ch.mention})")
        if not lines:
            raise CommandError("no modules have been disabled")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            Embed(color=self.bot.color, title="Disabled Modules").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @disablemodule.command(
        name="all",
        description="Disable a module in every channel",
        usage="<module>",
        example=",disablemodule all server",
    )
    @has_permissions(manage_channels=True)
    async def disablemodule_all(self, ctx, module: ModuleConverter):
        """block module everywhere"""
        label = module.replace("_", " ")
        existing = await self.db.fetchrow(
            """SELECT * FROM disabled_modules WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id,
            module,
        )
        all_ids = [c.id for c in ctx.guild.text_channels]
        if existing:
            ids = list(existing.channel_ids)
            fresh = [c.id for c in ctx.guild.text_channels if c.id not in ids]
            if not fresh and all(cid in ids for cid in all_ids):
                raise CommandError(
                    f"`{label}` has already been **disabled** in this server"
                )
            ids = ids + fresh
            await self.db.execute(
                """UPDATE disabled_modules
                   SET channel_ids = $1
                   WHERE guild_id = $2 AND module = $3""",
                ids,
                ctx.guild.id,
                module,
            )
        else:
            await self.db.execute(
                """INSERT INTO disabled_modules (guild_id, module, channel_ids)
                   VALUES($1, $2, $3)""",
                ctx.guild.id,
                module,
                all_ids,
            )
        return await ctx.success(f"**disabled** `{label}` in all channels")
