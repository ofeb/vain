from typing import Union
from discord.ext.commands import group, has_permissions, CommandError, Converter
from discord import Embed, TextChannel, Role
from asyncio import sleep, Lock
from collections import defaultdict
from core.discord.package import Package


ACTION_MAP = {"deny": ["d", "n", "no"], "allow": ["a", "y", "yes"]}


class ResponderAction(Converter):
    """allow or deny converter"""

    async def convert(self, ctx, argument: str):
        """parse allow/deny"""
        argument = argument.lower()
        if argument in ACTION_MAP:
            return argument
        for key, aliases in ACTION_MAP.items():
            if argument in aliases:
                return key
        raise CommandError("use `allow` or `deny`")


class AutoresponderCommands(Package):
    """autoresponder setup and management"""

    def __init__(self, bot):
        """init with locks"""
        super().__init__(bot)
        self.ar_locks = defaultdict(Lock)

    @group(
        name="autoresponder",
        aliases=["autoresponders", "ars", "ar"],
        description="auto-reply to messages matching a trigger",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def autoresponder(self, ctx):
        """autoresponder help"""
        return await ctx.send_help(ctx.command)

    @autoresponder.command(
        name="role",
        description="allow or deny a role from triggering an autoresponder",
        example=",autoresponder role @boosters deny sup",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_role(
        self, ctx, role: Role, action: ResponderAction, *, trigger: str
    ):
        """restrict autoresponder by role"""
        if action == "deny":
            existing = await self.db.fetchval(
                """SELECT denied_role_ids FROM auto_responders WHERE guild_id = $1 AND trigger = $2""",
                ctx.guild.id, trigger,
            )
            ids = existing or []
            ids.append(role.id)
            query = "INSERT INTO auto_responders (guild_id, trigger, denied_role_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, trigger) DO UPDATE SET denied_role_ids = excluded.denied_role_ids"
            await self.db.execute(query, ctx.guild.id, trigger, ids)
        else:
            data = await self.db.fetch(
                """SELECT denied_role_ids, allowed_role_ids FROM auto_responders WHERE guild_id = $1 AND trigger = $2""",
                ctx.guild.id, trigger,
            )
            if data and data.denied_role_ids and role.id in data.denied_role_ids:
                data.denied_role_ids.remove(role.id)
            allowed = (data.allowed_role_ids if data else None) or []
            allowed.append(role.id)
            query = "INSERT INTO auto_responders (guild_id, trigger, allowed_role_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, trigger) DO UPDATE SET allowed_role_ids = excluded.allowed_role_ids"
            await self.db.execute(query, ctx.guild.id, trigger, allowed)
        return await ctx.success(
            f"{action}ed {role.mention} for trigger `{trigger}`"
        )

    @autoresponder.command(
        name="channel",
        description="allow or deny a channel from autoresponder",
        example=",autoresponder channel #text deny sup",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_channel(
        self, ctx, channel: TextChannel, action: ResponderAction, *, trigger: str
    ):
        """restrict autoresponder by channel"""
        if action == "deny":
            existing = await self.db.fetchval(
                """SELECT denied_channel_ids FROM auto_responders WHERE guild_id = $1 AND trigger = $2""",
                ctx.guild.id, trigger,
            )
            ids = existing or []
            ids.append(channel.id)
            query = "INSERT INTO auto_responders (guild_id, trigger, denied_channel_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, trigger) DO UPDATE SET denied_channel_ids = excluded.denied_channel_ids"
            await self.db.execute(query, ctx.guild.id, trigger, ids)
        else:
            data = await self.db.fetch(
                """SELECT denied_channel_ids, allowed_channel_ids FROM auto_responders WHERE guild_id = $1 AND trigger = $2""",
                ctx.guild.id, trigger,
            )
            if data and data.denied_channel_ids and channel.id in data.denied_channel_ids:
                data.denied_channel_ids.remove(channel.id)
            allowed = (data.allowed_channel_ids if data else None) or []
            allowed.append(channel.id)
            query = "INSERT INTO auto_responders (guild_id, trigger, allowed_channel_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, trigger) DO UPDATE SET allowed_channel_ids = excluded.allowed_channel_ids"
            await self.db.execute(query, ctx.guild.id, trigger, allowed)
        return await ctx.success(
            f"{action}ed {channel.mention} for trigger `{trigger}`"
        )

    @autoresponder.command(
        name="reset",
        description="Remove every auto response",
        aliases=["clear"],
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_reset(self, ctx):
        """wipe all autoresponders"""
        await self.db.execute(
            """DELETE FROM auto_responders WHERE guild_id = $1""", ctx.guild.id
        )
        return await ctx.success("all autoresponders cleared")

    @autoresponder.command(name="variables", description="View a list of available variables")
    @has_permissions(manage_channels=True)
    async def autoresponder_variables(self, ctx):
        """show ar variables"""
        pass

    @autoresponder.command(
        name="update",
        description="Update a reply for a trigger word",
        example=",autoresponder update Hi, Goodbye",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_update(self, ctx, *, args: str):
        """edit an autoresponder"""
        parts = [p.strip() for p in args.split(",", 1)]
        if len(parts) == 1:
            parts = [p.strip() for p in args.split(" ", 1)]
        if len(parts) != 2:
            raise CommandError("expected: trigger, response")
        trigger, response = parts
        await self.db.execute(
            """UPDATE auto_responders SET response = $1 WHERE trigger = $2 AND guild_id = $3""",
            response, trigger, ctx.guild.id,
        )
        return await ctx.success(f"**{trigger}** now replies with `{response}`")

    @autoresponder.command(
        name="remove",
        aliases=["del", "delete", "d", "rem"],
        description="Remove a reply for a trigger word",
        example=",autoresponder remove Hi",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_remove(self, ctx, *, trigger: str):
        """remove an autoresponder"""
        await self.db.execute(
            """DELETE FROM auto_responders WHERE trigger = $1 AND guild_id = $2""",
            trigger, ctx.guild.id,
        )
        return await ctx.success(f"removed autoresponder for `{trigger}` if it existed")

    @autoresponder.command(
        name="list",
        aliases=["view", "show", "ls"],
        description="View auto-reply triggers in guild",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_list(self, ctx):
        """show all autoresponders"""
        data = await self.db.fetch(
            """SELECT trigger, strict FROM auto_responders WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not data:
            raise CommandError("no autoresponders found")
        embed = Embed(title="Auto Responders").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        lines = [
            f"`{i}` **{row.trigger}** (strict: `{'yes' if row.strict else 'no'}`)"
            for i, row in enumerate(data, start=1)
        ]
        return await ctx.paginate(embed, lines)

    @autoresponder.command(
        name="add",
        aliases=["a", "create", "c"],
        description="Create a reply for a trigger word",
        parameters={
            "self_destruct": {"converter": int, "default": None},
            "not_strict": {"no_value": True, "default": False},
            "reply": {"no_value": True, "default": False},
            "ignore_command_check": {"no_value": True, "default": False},
        },
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_add(self, ctx, *, args: str):
        """add an autoresponder"""
        parts = [p.strip() for p in args.split(",", 1)]
        if len(parts) == 1:
            parts = [p.strip() for p in args.split(" ", 1)]
        if len(parts) != 2:
            raise CommandError("expected: trigger, response")
        trigger, response = parts
        timer = ctx.parameters.get("self_destruct", None)
        strict = not ctx.parameters.get("not_strict", False)
        should_reply = bool(ctx.parameters.get("reply", False))
        skip_check = bool(ctx.parameters.get("ignore_command_check", False))
        await self.db.execute(
            """
            INSERT INTO auto_responders (
                guild_id, trigger, response, strict, reply, self_destruct, ignore_command_checks
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (guild_id, trigger)
            DO UPDATE SET
                response = EXCLUDED.response,
                strict = EXCLUDED.strict,
                reply = EXCLUDED.reply,
                self_destruct = EXCLUDED.self_destruct,
                ignore_command_checks = EXCLUDED.ignore_command_checks;
            """,
            ctx.guild.id, trigger, response, strict, should_reply, timer, skip_check,
        )
        flags = ""
        flags += "(strict)" if strict else "(non-strict)"
        flags += "(reply)" if should_reply else ""
        flags += "(bypass check)" if skip_check else ""
        if timer:
            flags += f"\ndeletes after `{timer}` seconds"
        return await ctx.success(f"added autoresponder for **{trigger}** {flags}")

    async def _send_response(self, ctx, rec):
        """send autoresponder reply"""
        rate = await self.bot.object_cache.ratelimited(
            f"auto_responder:{ctx.guild.id}", 1, 5
        )
        if rate != 0:
            await sleep(5)
        if not rec.ignore_command_checks and ctx.valid:
            return
        role_ids = [r.id for r in ctx.author.roles]
        if set(role_ids) & set(rec.denied_role_ids):
            return
        if set([ctx.channel.id]) & set(rec.denied_channel_ids):
            return
        kwargs = {"reference": ctx.message} if rec.reply else {}
        return await ctx.send(rec.response, delete_after=rec.self_destruct, **kwargs)

    async def on_context(self, ctx):
        """handle autoresponder on message"""
        async with self.ar_locks[f"auto_responder:{ctx.channel.id}"]:
            data = await self.bot.db.fetch(
                """SELECT * FROM auto_responders WHERE guild_id = $1""",
                ctx.guild.id,
            )
            if not data:
                return
            content = ctx.message.content.lower()
            for rec in data:
                trigger = rec.trigger.lower()
                if not rec.strict and trigger in content:
                    await self._send_response(ctx, rec)
                elif rec.strict and trigger in content.split(" "):
                    await self._send_response(ctx, rec)
