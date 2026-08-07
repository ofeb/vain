from __future__ import annotations

from typing import Optional, Union

from discord import Embed, Member, Role, TextChannel
from discord.ext.commands import (
    BadArgument,
    CommandError,
    MemberConverter,
    RoleConverter,
    TextChannelConverter,
    group,
)

from core.discord.package import Package
from core.managers.converters import ModuleConverter
from core.managers.permissions import has_permissions
from core.tools.hierarchy import is_member_like, target_phrase


class ModuleDisableCommands(Package):
    """disable modules per channel, role, member, or server-wide"""

    async def _resolve_module_and_target(
        self,
        ctx,
        *,
        payload: str,
    ) -> tuple[str, Optional[Union[TextChannel, Member, Role, str]]]:
        """Parse ``[channel|member|role|server] <module>`` or reverse."""
        text = (payload or "").strip()
        if not text:
            raise CommandError("provide a module to disable")

        parts = text.split()
        target: Optional[Union[TextChannel, Member, Role, str]] = None
        module_text = text

        if len(parts) >= 2:
            head, rest = parts[0], " ".join(parts[1:])
            head_l = head.lower()
            if head_l in {"server", "guild", "global"}:
                target = "server"
                module_text = rest
            else:
                resolved = None
                for converter in (MemberConverter(), RoleConverter(), TextChannelConverter()):
                    try:
                        resolved = await converter.convert(ctx, head)
                        module_text = rest
                        break
                    except (BadArgument, CommandError):
                        continue
                if resolved is None:
                    
                    try:
                        resolved = await TextChannelConverter().convert(ctx, parts[-1])
                        module_text = " ".join(parts[:-1])
                    except (BadArgument, CommandError):
                        resolved = None
                target = resolved

        module = await ModuleConverter().convert(ctx, module_text)
        return module, target

    @group(
        name="disablemodule",
        description="Disable a module in a channel/role/member/server (defaults to this channel)",
        usage="[channel|member|role|server] <module>",
        example=",disablemodule #general server",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disablemodule(self, ctx, *, payload: str = None):
        """Disable a module. No target → this channel."""
        if not payload:
            return await ctx.send_help(ctx.command)

        module, target = await self._resolve_module_and_target(ctx, payload=payload)
        label = module.replace("_", " ")

        if target is None:
            target = ctx.channel

        
        
        
        if target == "server":
            channel_ids = [c.id for c in ctx.guild.text_channels]
            phrase = "in this **server**"
        elif isinstance(target, (TextChannel,)):
            channel_ids = [target.id]
            phrase = f"in {target.mention}"
        elif isinstance(target, Role) or is_member_like(target):
            
            channel_ids = [ctx.channel.id]
            phrase = f"in {ctx.channel.mention}"
        else:
            channel_ids = [getattr(target, "id", ctx.channel.id)]
            phrase = target_phrase(target) if target != "server" else "in this **server**"

        row = await self.db.fetchrow(
            """SELECT * FROM disabled_modules WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id,
            module,
        )

        if row:
            ids = list(row.channel_ids or [])
            fresh = [cid for cid in channel_ids if cid not in ids]
            if not fresh:
                raise CommandError(f"`{label}` was already **disabled** {phrase}")
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
                channel_ids,
            )
        return await ctx.success(f"**disabled** `{label}` module {phrase}")

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
        all_text = {c.id for c in ctx.guild.text_channels}
        for row in data:
            label = row.module.replace("_", " ")
            ids = set(int(x) for x in (row.channel_ids or []))
            if ids and all_text and all_text.issubset(ids):
                lines.append(f"**{label}** module — disabled in this **server**")
                continue
            for cid in row.channel_ids or []:
                ch = ctx.guild.get_channel(cid)
                if ch:
                    lines.append(f"**{label}** module — ({ch.mention})")
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
            ids = list(existing.channel_ids or [])
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
        return await ctx.success(f"**disabled** `{label}` module in this **server**")
