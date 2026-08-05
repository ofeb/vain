from __future__ import annotations

from typing import Literal

from discord.ext.commands import CommandError, group

from core.discord.package import Package
from core.managers.converters import EmbedConverter
from core.managers.permissions import has_permissions
from core.tools.moderation_logs import DEFAULT_INVOKE_DM, DEFAULT_INVOKE_RESPONSE

INVOKE_USAGE = "(message or embed code)"

ACTIONS_WITH_DM = (
    "softban",
    "jail",
    "timeout",
    "kick",
    "unban",
    "unjail",
    "untimeout",
    "tempban",
    "warn",
    "ban",
    "mute",
    "unmute",
)

MESSAGE_ONLY_ACTIONS = (
    "hardban",
    "imute",
    "iunmute",
    "rmute",
    "runmute",
)

ACTION_LABELS = {
    "softban": "softban",
    "jail": "jail",
    "timeout": "timeout",
    "kick": "kick",
    "unban": "unban",
    "unjail": "unjail",
    "hardban": "hardban",
    "untimeout": "untimeout",
    "tempban": "tempban",
    "warn": "warn",
    "ban": "ban",
    "mute": "mute",
    "unmute": "unmute",
    "imute": "imute",
    "iunmute": "iunmute",
    "rmute": "rmute",
    "runmute": "runmute",
}


def _register_invoke_action(parent, action: str, *, has_dm: bool) -> None:
    label = ACTION_LABELS[action]

    @parent.group(
        name=action,
        description=f"Change {label} message for DM or command response",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def action_group(self, ctx):
        """Change punishment messages for DM or command response"""
        return await ctx.send_help(ctx.command)

    action_group.__name__ = f"invoke_{action}"

    @action_group.command(
        name="on",
        description=f"Enable {label} command response messages",
    )
    @has_permissions(manage_guild=True)
    async def message_on(self, ctx):
        """enable command response invoke"""
        await self._set_invoke_enabled(ctx, action, "message", True)
        return await ctx.success(f"{label} response **enabled**")

    message_on.__name__ = f"invoke_{action}_on"

    @action_group.command(
        name="off",
        description=f"Disable {label} command response messages",
    )
    @has_permissions(manage_guild=True)
    async def message_off(self, ctx):
        """disable command response invoke"""
        await self._set_invoke_enabled(ctx, action, "message", False)
        return await ctx.success(f"{label} response **disabled**")

    message_off.__name__ = f"invoke_{action}_off"

    if has_dm:

        @action_group.group(
            name="dm",
            description=f"Change {label} message for Direct Messages",
            invoke_without_command=True,
            usage=INVOKE_USAGE,
        )
        @has_permissions(manage_guild=True)
        async def dm_group(self, ctx, *, message: EmbedConverter | None = None):
            """set dm message"""
            if message is None:
                return await ctx.send_help(ctx.command)
            await self._set_invoke(ctx, action, "dm", message.script)
            return await ctx.success(f"{label} DM updated")

        dm_group.__name__ = f"invoke_{action}_dm"

        @dm_group.command(
            name="on",
            description=f"Enable {label} Direct Message notifications",
        )
        @has_permissions(manage_guild=True)
        async def dm_on(self, ctx):
            """enable dm invoke"""
            await self._set_invoke_enabled(ctx, action, "dm", True)
            return await ctx.success(f"{label} DM **enabled**")

        dm_on.__name__ = f"invoke_{action}_dm_on"

        @dm_group.command(
            name="off",
            description=f"Disable {label} Direct Message notifications",
        )
        @has_permissions(manage_guild=True)
        async def dm_off(self, ctx):
            """disable dm invoke"""
            await self._set_invoke_enabled(ctx, action, "dm", False)
            return await ctx.success(f"{label} DM **disabled**")

        dm_off.__name__ = f"invoke_{action}_dm_off"

        @dm_group.command(
            name="view",
            description=f"View the {label} message for Direct Messages",
        )
        @has_permissions(manage_guild=True)
        async def dm_view(self, ctx):
            """view dm message"""
            return await self._view_invoke(ctx, action, "dm")

        dm_view.__name__ = f"invoke_{action}_dm_view"

    @action_group.group(
        name="message",
        aliases=["msg"],
        description=f"Change {label} message for command response",
        invoke_without_command=True,
        usage=INVOKE_USAGE,
    )
    @has_permissions(manage_guild=True)
    async def message_group(self, ctx, *, message: EmbedConverter | None = None):
        """set command response message"""
        if message is None:
            return await ctx.send_help(ctx.command)
        await self._set_invoke(ctx, action, "message", message.script)
        return await ctx.success(f"{label} response updated")

    message_group.__name__ = f"invoke_{action}_message"

    @message_group.command(
        name="view",
        description=f"View the {label} message for command response",
    )
    @has_permissions(manage_guild=True)
    async def message_view(self, ctx):
        """view command response message"""
        return await self._view_invoke(ctx, action, "message")

    message_view.__name__ = f"invoke_{action}_message_view"


class InvokeCommands(Package):
    """invoke message customization"""

    @group(
        name="invoke",
        description="Change punishment messages for DM or command response",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invoke(self, ctx):
        """Change punishment messages for DM or command response"""
        return await ctx.send_help(ctx.command)

    async def _set_invoke(
        self,
        ctx,
        action: str,
        target: Literal["dm", "message"],
        code: str,
    ) -> None:
        column = "dm_code" if target == "dm" else "message_code"
        await self.db.execute(
            f"""INSERT INTO invocation (guild_id, command, {column})
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, command)
                DO UPDATE SET {column} = excluded.{column}""",
            ctx.guild.id,
            action,
            code,
        )

    async def _set_invoke_enabled(
        self,
        ctx,
        action: str,
        target: Literal["dm", "message"],
        enabled: bool,
    ) -> None:
        column = "dm_enabled" if target == "dm" else "message_enabled"
        await self.db.execute(
            f"""INSERT INTO invocation (guild_id, command, {column})
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, command)
                DO UPDATE SET {column} = excluded.{column}""",
            ctx.guild.id,
            action,
            enabled,
        )

    async def _view_invoke(
        self,
        ctx,
        action: str,
        target: Literal["dm", "message"],
    ):
        column = "dm_code" if target == "dm" else "message_code"
        label = ACTION_LABELS[action]
        kind = "DM" if target == "dm" else "response"
        msg = await self.db.fetchval(
            f"""SELECT {column} FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id,
            action,
        )
        if not msg:
            defaults = DEFAULT_INVOKE_DM if target == "dm" else DEFAULT_INVOKE_RESPONSE
            msg = defaults.get(action)
        if not msg:
            raise CommandError(f"no {label} {kind} set")
        return await self.bot.send_embed(
            ctx.channel,
            msg,
            user=ctx.author,
            moderator=ctx.author,
        )


for _action in ACTIONS_WITH_DM:
    _register_invoke_action(InvokeCommands.invoke, _action, has_dm=True)

for _action in MESSAGE_ONLY_ACTIONS:
    _register_invoke_action(InvokeCommands.invoke, _action, has_dm=False)
