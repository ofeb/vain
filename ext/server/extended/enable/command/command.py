from __future__ import annotations

import re
from typing import Optional, Union

from discord import Embed, Member, TextChannel
from discord.ext.commands import (
    BadArgument,
    CommandError,
    MemberConverter,
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
    # Always store/lookup lowercase so disable checks match reliably
    return str(getattr(command, "qualified_name", command)).lower()


_CHANNEL_MENTION = re.compile(r"^(<#\d+>)\s+(.+)$", re.DOTALL)
_USER_MENTION = re.compile(r"^(<@!?\d+>)\s+(.+)$", re.DOTALL)


class CommandEnableCommands(Package):
    """enable commands per channel or server-wide"""

    async def _resolve_target_and_command(
        self,
        ctx,
        *,
        payload: str,
    ) -> tuple[Optional[Union[TextChannel, Member]], object]:
        """Parse ``[channel|member] <command>``."""
        text = (payload or "").strip()
        if not text:
            raise CommandError("provide a command to enable")

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

        parts = text.split()
        target: Optional[Union[TextChannel, Member]] = None
        command_text = text

        if len(parts) >= 2:
            head, rest = parts[0], " ".join(parts[1:])
            for converter in (MemberConverter(), TextChannelConverter()):
                try:
                    target = await converter.convert(ctx, head)
                    command_text = rest
                    break
                except (BadArgument, CommandError):
                    continue

        command = await CommandConverter().convert(ctx, command_text)
        return target, command

    async def _save_disabled(
        self,
        ctx,
        command_name: str,
        object_ids: list[int],
        object_types: list[str],
    ) -> None:
        if not object_ids:
            await self.db.execute(
                """DELETE FROM disabled_commands WHERE guild_id = $1 AND lower(command) = lower($2)""",
                ctx.guild.id,
                command_name,
            )
        else:
            await self.db.execute(
                """UPDATE disabled_commands
                   SET object_ids = $1, object_types = $2
                   WHERE guild_id = $3 AND lower(command) = lower($4)""",
                object_ids,
                object_types,
                ctx.guild.id,
                command_name,
            )
        await ctx.bot.invalidate_command_access_cache(ctx.guild.id, command_name)

    @group(
        name="enablecommand",
        aliases=["ecmd"],
        description=(
            "Enable a disabled command in a channel (defaults to this channel) "
            "or for a member"
        ),
        usage="[channel or member] <command>",
        example=",enablecommand #general snipe",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def enablecommand(self, ctx, *, payload: str = None):
        """Enable a command in a channel/member. No channel → this channel."""
        if not payload:
            return await ctx.send_help(ctx.command)

        target, command = await self._resolve_target_and_command(ctx, payload=payload)
        name = _cmd_label(command)

        # No channel/member given → use the channel this command was run in
        if target is None:
            target = ctx.channel

        if is_member_like(target):
            # Config-only (DB write) — bot role vs target does not matter
            await ensure_member_hierarchy(ctx, target, bot_hierarchy=False)

        record = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND lower(command) = lower($2)""",
            ctx.guild.id,
            name,
        )

        target_id = int(target.id)
        if record:
            try:
                raw_ids = record["object_ids"]
            except Exception:
                raw_ids = getattr(record, "object_ids", None) or []
            try:
                raw_types = record["object_types"]
            except Exception:
                raw_types = getattr(record, "object_types", None) or []
            obj_ids = [int(x) for x in (raw_ids or [])]
            obj_types = list(raw_types or [])
        else:
            obj_ids, obj_types = [], []

        if not record or target_id not in obj_ids:
            return await ctx.fail(
                f"`{name}` was already **enabled** {target_phrase(target)}"
            )

        idx = obj_ids.index(target_id)
        obj_ids.pop(idx)
        if idx < len(obj_types):
            obj_types.pop(idx)
        await self._save_disabled(ctx, name, obj_ids, obj_types)
        return await ctx.success(f"**enabled** `{name}` {target_phrase(target)}")

    @enablecommand.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View disabled commands that can still be re-enabled",
    )
    @has_permissions(manage_channels=True)
    async def enablecommand_list(self, ctx):
        """list commands that are currently disabled somewhere"""
        data = await self.db.fetch(
            """SELECT object_ids, object_types, command
               FROM disabled_commands WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not data:
            raise CommandError("no commands are currently disabled")

        def resolve(obj_id: int):
            if m := ctx.guild.get_member(obj_id):
                return m
            if ch := ctx.guild.get_channel(obj_id):
                return ch
            return None

        lines = []
        for row in data:
            if not row.object_ids:
                continue
            for oid in row.object_ids:
                obj = resolve(oid)
                if obj:
                    lines.append(
                        f"**{row.command}** — disabled {target_phrase(obj)}"
                    )
        if not lines:
            raise CommandError("no commands are currently disabled")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            Embed(color=self.bot.color, title="Disabled Commands (re-enable these)").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @enablecommand.command(
        name="all",
        description="Enable a command in every channel",
        usage="<command>",
        example=",enablecommand all snipe",
    )
    @has_permissions(manage_channels=True)
    async def enablecommand_all(self, ctx, *, command: CommandConverter):
        """enable command everywhere (clears all channel/member disables)"""
        name = _cmd_label(command)
        record = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND lower(command) = lower($2)""",
            ctx.guild.id,
            name,
        )
        has_ids = False
        if record:
            try:
                has_ids = bool(record["object_ids"] or getattr(record, "object_ids", None))
            except Exception:
                has_ids = bool(getattr(record, "object_ids", None))
        if not record or not has_ids:
            return await ctx.fail(
                f"`{name}` has already been **enabled** to use in this server"
            )
        await self.db.execute(
            """DELETE FROM disabled_commands WHERE guild_id = $1 AND lower(command) = lower($2)""",
            ctx.guild.id,
            name,
        )
        await ctx.bot.invalidate_command_access_cache(ctx.guild.id, name)
        return await ctx.success(f"**enabled** `{name}` in all channels")
