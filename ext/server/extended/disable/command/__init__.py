from __future__ import annotations

import re
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
from core.managers.converters import CommandConverter
from core.managers.permissions import has_permissions
from core.tools.hierarchy import (
    ensure_member_hierarchy,
    is_member_like,
    target_phrase,
)


def _cmd_label(command) -> str:
    return str(getattr(command, "qualified_name", command)).lower()


_CHANNEL_MENTION = re.compile(r"^(<#\d+>)\s+(.+)$", re.DOTALL)
_USER_MENTION = re.compile(r"^(<@!?\d+>)\s+(.+)$", re.DOTALL)
_ROLE_MENTION = re.compile(r"^(<@&\d+>)\s+(.+)$", re.DOTALL)


class CommandDisableCommands(Package):
    """disable commands per channel, member, role, or server-wide"""

    async def _resolve_target_and_command(
        self,
        ctx,
        *,
        payload: str,
    ) -> tuple[Optional[Union[TextChannel, Member, Role, str]], object]:
        """Parse ``[channel or member or role or server or guild] <command>``."""
        text = (payload or "").strip()
        if not text:
            raise CommandError("provide a command to disable")

        m = _CHANNEL_MENTION.match(text)
        if m:
            target = await TextChannelConverter().convert(ctx, m.group(1))
            command = await CommandConverter().convert(ctx, m.group(2).strip())
            return target, command

        m = _USER_MENTION.match(text)
        if m:
            target = await MemberConverter().convert(ctx, m.group(1))
            command = await CommandConverter().convert(ctx, m.group(2).strip())
            return target, command

        m = _ROLE_MENTION.match(text)
        if m:
            target = await RoleConverter().convert(ctx, m.group(1))
            command = await CommandConverter().convert(ctx, m.group(2).strip())
            return target, command

        parts = text.split()
        target: Optional[Union[TextChannel, Member, Role, str]] = None
        command_text = text

        if len(parts) >= 2:
            head, rest = parts[0], " ".join(parts[1:])
            head_l = head.lower()
            if head_l in {"server", "guild", "global"}:
                target = "server"
                command_text = rest
            else:
                for converter in (MemberConverter(), RoleConverter(), TextChannelConverter()):
                    try:
                        target = await converter.convert(ctx, head)
                        command_text = rest
                        break
                    except (BadArgument, CommandError):
                        continue

        command = await CommandConverter().convert(ctx, command_text)
        return target, command

    def _kind_for(self, target) -> str:
        if target == "server" or target is None:
            return "guild"
        if isinstance(target, Role):
            return "role"
        if is_member_like(target):
            return "member"
        return "channel"

    @group(
        name="disablecommand",
        aliases=["dcmd"],
        description=(
            "Disable a command in a channel/role/member/server "
            "(defaults to this channel)"
        ),
        usage="[channel or member or role or server] <command>",
        example=",disablecommand #general snipe",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disablecommand(self, ctx, *, payload: str = None):
        """Disable a command. No target → this channel."""
        if not payload:
            return await ctx.send_help(ctx.command)

        target, command = await self._resolve_target_and_command(ctx, payload=payload)
        name = _cmd_label(command)

        if target is None:
            target = ctx.channel

        kind = self._kind_for(target)

        
        if isinstance(target, Role):
            result = await self.db.execute(
                """
                DELETE FROM command_restrictions
                WHERE guild_id = $1 AND command = $2 AND role_id = $3
                """,
                ctx.guild.id,
                name,
                target.id,
            )
            await ctx.bot.invalidate_command_access_cache(ctx.guild.id, name)
            if result == "DELETE 0":
                
                return await ctx.fail(
                    f"{target.mention} has no exclusive lock on `{name}`"
                )
            return await ctx.success(
                f"removed exclusive access for {target.mention} on `{name}`"
            )

        if is_member_like(target) and isinstance(target, Member):
            await ensure_member_hierarchy(ctx, target, bot_hierarchy=False)

        existing = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND lower(command) = lower($2)""",
            ctx.guild.id,
            name,
        )

        if kind == "guild" or target == "server":
            target_id = int(ctx.guild.id)
            phrase = "in this **server**"
            kind = "guild"
        else:
            target_id = int(getattr(target, "id"))
            phrase = target_phrase(target)

        if existing:
            try:
                raw_ids = existing["object_ids"]
            except Exception:
                raw_ids = getattr(existing, "object_ids", None) or []
            try:
                raw_types = existing["object_types"]
            except Exception:
                raw_types = getattr(existing, "object_types", None) or []
            ids = [int(x) for x in (raw_ids or [])]
            kinds = list(raw_types or [])
            if target_id in ids:
                return await ctx.fail(
                    f"`{name}` was already **disabled** {phrase}"
                )
            ids.append(target_id)
            kinds.append(kind)
            await self.db.execute(
                """UPDATE disabled_commands
                   SET object_ids = $1, object_types = $2
                   WHERE guild_id = $3 AND lower(command) = lower($4)""",
                ids,
                kinds,
                ctx.guild.id,
                name,
            )
        else:
            await self.db.execute(
                """INSERT INTO disabled_commands
                   (guild_id, command, object_ids, object_types)
                   VALUES($1, $2, $3, $4)""",
                ctx.guild.id,
                name,
                [target_id],
                [kind],
            )
        await ctx.bot.invalidate_command_access_cache(ctx.guild.id, name)
        return await ctx.success(f"**disabled** `{name}` {phrase}")

    @disablecommand.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of disabled commands in guild",
    )
    @has_permissions(manage_channels=True)
    async def disablecommand_list(self, ctx):
        """list disabled commands"""
        data = await self.db.fetch(
            """SELECT object_ids, object_types, command
               FROM disabled_commands WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not data:
            raise CommandError("no commands have been disabled")

        def resolve(obj_id: int, kind: str | None = None):
            kind_l = (kind or "").lower()
            if kind_l in {"guild", "server"} or obj_id == ctx.guild.id:
                return "server"
            if kind_l == "role":
                return ctx.guild.get_role(obj_id)
            role = ctx.guild.get_role(obj_id)
            if role is not None:
                return role
            if m := ctx.guild.get_member(obj_id):
                return m
            if ch := ctx.guild.get_channel(obj_id):
                return ch
            return None

        lines = []
        for row in data:
            ids = list(row.object_ids or [])
            kinds = list(row.object_types or [])
            for i, oid in enumerate(ids):
                kind = kinds[i] if i < len(kinds) else None
                obj = resolve(int(oid), kind)
                if obj == "server":
                    lines.append(f"**{row.command}** - disabled in this **server**")
                elif obj is not None:
                    if isinstance(obj, Role):
                        lines.append(f"**{row.command}** - only {obj.mention} allowed (role lock)")
                    else:
                        lines.append(
                            f"**{row.command}** - disabled {target_phrase(obj)}"
                        )
        if not lines:
            raise CommandError("no commands have been disabled")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            Embed(color=self.bot.color, title="Disabled Commands").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @disablecommand.command(
        name="all",
        description="Disable a command in every channel",
        usage="<command>",
        example=",disablecommand all snipe",
    )
    @has_permissions(manage_channels=True)
    async def disablecommand_all(self, ctx, *, command: CommandConverter):
        """block command everywhere"""
        name = _cmd_label(command)
        existing = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND lower(command) = lower($2)""",
            ctx.guild.id,
            name,
        )
        
        if existing:
            await self.db.execute(
                """UPDATE disabled_commands
                   SET object_ids = $1, object_types = $2
                   WHERE guild_id = $3 AND lower(command) = lower($4)""",
                [ctx.guild.id],
                ["guild"],
                ctx.guild.id,
                name,
            )
        else:
            await self.db.execute(
                """INSERT INTO disabled_commands
                   (guild_id, command, object_ids, object_types)
                   VALUES($1, $2, $3, $4)""",
                ctx.guild.id,
                name,
                [ctx.guild.id],
                ["guild"],
            )
        await ctx.bot.invalidate_command_access_cache(ctx.guild.id, name)
        return await ctx.success(f"**disabled** `{name}` in this **server**")
