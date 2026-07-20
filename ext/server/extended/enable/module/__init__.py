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


class ModuleEnableCommands(Package):
    """re-enable modules per channel or server-wide"""

    async def _resolve_module_and_channel(
        self,
        ctx,
        *,
        payload: str,
    ) -> tuple[str, Optional[TextChannel]]:
        """Parse ``<module> [channel]`` or ``[channel] <module>``."""
        text = (payload or "").strip()
        if not text:
            raise CommandError("provide a module to enable")

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
        name="enablemodule",
        description="Enable a module in a channel (defaults to this channel)",
        usage="[channel] <module>",
        example=",enablemodule #general server",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def enablemodule(self, ctx, *, payload: str = None):
        """Enable a module in a channel. No channel → this channel."""
        if not payload:
            return await ctx.send_help(ctx.command)

        module, channel = await self._resolve_module_and_channel(ctx, payload=payload)
        label = module.replace("_", " ")

        
        if channel is None:
            channel = ctx.channel

        stored = await self.db.fetchval(
            """SELECT channel_ids FROM disabled_modules
               WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id,
            module,
        )

        if not stored or channel.id not in list(stored):
            raise CommandError(f"`{label}` was already **enabled** in {channel.mention}")

        ids = list(stored)
        ids.remove(channel.id)
        if ids:
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
                """DELETE FROM disabled_modules WHERE guild_id = $1 AND module = $2""",
                ctx.guild.id,
                module,
            )
        return await ctx.success(f"**enabled** `{label}` in {channel.mention}")

    @enablemodule.command(
        name="all",
        description="Enables a module in every channel",
        usage="<module>",
        example=",enablemodule all server",
    )
    @has_permissions(manage_channels=True)
    async def enablemodule_all(self, ctx, *, module: ModuleConverter):
        """enable module everywhere"""
        label = module.replace("_", " ")
        stored = await self.db.fetchval(
            """SELECT channel_ids FROM disabled_modules
               WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id,
            module,
        )
        if not stored:
            raise CommandError(
                f"`{label}` has already been **enabled** to use in this server"
            )
        await self.db.execute(
            """DELETE FROM disabled_modules WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id,
            module,
        )
        return await ctx.success(f"**enabled** `{label}` in all channels")

    @enablemodule.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View modules currently disabled somewhere",
    )
    @has_permissions(manage_channels=True)
    async def enablemodule_list(self, ctx):
        """list modules that are disabled (can be re-enabled)"""
        data = await self.db.fetch(
            """SELECT module, channel_ids FROM disabled_modules WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not data:
            raise CommandError("no modules are currently disabled")
        lines = []
        for row in data:
            label = row.module.replace("_", " ")
            for cid in row.channel_ids or []:
                ch = ctx.guild.get_channel(cid)
                if ch:
                    lines.append(f"**{label}** — disabled in {ch.mention}")
        if not lines:
            raise CommandError("no modules are currently disabled")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            Embed(color=self.bot.color, title="Disabled Modules (re-enable these)").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )
