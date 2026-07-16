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
    return getattr(command, "qualified_name", str(command))


_CHANNEL_MENTION = re.compile(r"^(<#\d+>)\s+(.+)$", re.DOTALL)
_USER_MENTION = re.compile(r"^(<@!?\d+>)\s+(.+)$", re.DOTALL)


class CommandDisableCommands(Package):
    """disable commands per channel, member, or server-wide"""

    async def _resolve_target_and_command(
        self,
        ctx,
        *,
        payload: str,
    ) -> tuple[Optional[Union[TextChannel, Member]], object]:
        """Parse ``[channel|member] <command>``."""
        text = (payload or "").strip()
        if not text:
            raise CommandError("provide a command to disable")

        # Prefer full mention forms so nicknames with spaces never break parsing
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
            # Members first — channel names rarely look like user tokens
            for converter in (MemberConverter(), TextChannelConverter()):
                try:
                    target = await converter.convert(ctx, head)
                    command_text = rest
                    break
                except (BadArgument, CommandError):
                    continue

        command = await CommandConverter().convert(ctx, command_text)
        return target, command

    @group(
        name="disablecommand",
        aliases=["dcmd"],
        description=(
            "Disable a command in a channel (defaults to this channel) or for a member"
        ),
        usage="[channel or member] <command>",
        example=",disablecommand #general snipe",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disablecommand(self, ctx, *, payload: str = None):
        """Disable a command in a channel/member. No channel → this channel."""
        if not payload:
            return await ctx.send_help(ctx.command)

        target, command = await self._resolve_target_and_command(ctx, payload=payload)
        name = _cmd_label(command)

        # No channel/member given → use the channel this command was run in
        if target is None:
            target = ctx.channel

        if is_member_like(target):
            await ensure_member_hierarchy(ctx, target)

        existing = await self.db.fetchrow(
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id,
            name,
        )

        kind = "member" if is_member_like(target) else "channel"
        if existing:
            if target.id in existing.object_ids:
                raise CommandError(
                    f"`{name}` was already **disabled** {target_phrase(target)}"
                )
            ids = list(existing.object_ids)
            kinds = list(existing.object_types)
            ids.append(target.id)
            kinds.append(kind)
            await self.db.execute(
                """UPDATE disabled_commands
                   SET object_ids = $1, object_types = $2
                   WHERE guild_id = $3 AND command = $4""",
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
                [target.id],
                [kind],
            )
        await ctx.bot.invalidate_command_access_cache(ctx.guild.id, name)
        return await ctx.success(f"**disabled** `{name}` {target_phrase(target)}")

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

        def resolve(obj_id: int):
            if m := ctx.guild.get_member(obj_id):
                return m
            if ch := ctx.guild.get_channel(obj_id):
                return ch
            return None

        lines = []
        for row in data:
            for oid in row.object_ids:
                obj = resolve(oid)
                if obj:
                    lines.append(
                        f"**{row.command}** — disabled {target_phrase(obj)}"
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
            """SELECT * FROM disabled_commands WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id,
            name,
        )
        all_ids = [c.id for c in ctx.guild.text_channels]
        if existing:
            ids = list(existing.object_ids)
            kinds = list(existing.object_types)
            fresh = [c.id for c in ctx.guild.text_channels if c.id not in ids]
            if not fresh and all(cid in ids for cid in all_ids):
                raise CommandError(
                    f"`{name}` has already been **disabled** in this server"
                )
            ids.extend(fresh)
            kinds.extend(["channel"] * len(fresh))
            await self.db.execute(
                """UPDATE disabled_commands
                   SET object_ids = $1, object_types = $2
                   WHERE guild_id = $3 AND command = $4""",
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
                all_ids,
                ["channel"] * len(all_ids),
            )
        await ctx.bot.invalidate_command_access_cache(ctx.guild.id, name)
        return await ctx.success(f"**disabled** `{name}` in all channels")
