from __future__ import annotations

import contextlib
import re
from asyncio import Lock, sleep
from collections import defaultdict
from typing import Union

import discord
from discord import Embed, Role, TextChannel
from discord.ext.commands import CommandError, group

from core.discord.package import Package
from core.tools.embed import Script

from core.managers.permissions import has_permissions
_ANGLE_URL_RE = re.compile(r"<(https?://[^>\s]+)>", re.IGNORECASE)


def _split_trigger_response(raw: str) -> tuple[str, str] | None:
    """Split a trigger and response pair from a command payload."""
    if "," not in raw:
        return None
    if ", " in raw:
        trigger, response = raw.split(", ", 1)
    else:
        trigger, response = raw.split(",", 1)
    trigger = trigger.strip()
    response = response.strip()
    if not trigger or not response:
        return None
    return trigger, response


def _parse_response_flags(raw: str) -> tuple[str, dict[str, object], str | None]:
    """Parse trailing autoresponder flags from the response body."""
    flags = {
        "not_strict": False,
        "self_destruct": None,
        "delete": False,
        "reply": False,
        "ignore_command_check": False,
    }
    remaining = raw
    error: str | None = None
    flag_re = re.compile(
        r"(?:\s+--(?P<flag>not_strict|not-strict|delete|reply|ignore_command_check|"
        r"ignore-command-check|self_destruct|self-destruct)(?:=(?P<eqval>\S+)|"
        r"\s+(?P<val>(?!\-\-)\S+))?)\s*$",
        re.IGNORECASE,
    )

    while True:
        match = flag_re.search(remaining)
        if not match:
            break

        flag = match.group("flag").lower()
        value = match.group("eqval") or match.group("val")
        if flag in {"not_strict", "not-strict"}:
            flags["not_strict"] = True
        elif flag == "delete":
            flags["delete"] = True
        elif flag == "reply":
            flags["reply"] = True
        elif flag in {"ignore_command_check", "ignore-command-check"}:
            flags["ignore_command_check"] = True
        elif flag in {"self_destruct", "self-destruct"}:
            if value is None or not value.isdigit():
                error = "self_destruct must be a number between 6 and 60."
            else:
                flags["self_destruct"] = int(value)

        remaining = remaining[: match.start()].rstrip()

    return remaining.strip(), flags, error


def _is_embed_script(response: str) -> bool:
    """Return True when the response should be parsed as bleed embed code."""
    from core.tools.embed import is_embed_script as _core_is_embed_script
    return _core_is_embed_script(response)


def _normalize_embed_script_urls(response: str) -> str:
    """Unwrap angle-bracket URLs inside embed scripts copied from Discord."""
    if not _is_embed_script(response):
        return response
    return _ANGLE_URL_RE.sub(r"\1", response)


class AutoresponderCommands(Package):
    """Autoresponder setup and management."""

    def __init__(self, bot):
        super().__init__(bot)
        self.ar_locks = defaultdict(Lock)

    async def _collect_records(self, guild_id: int) -> list[dict]:
        rows = await self.db.fetch(
            "SELECT * FROM auto_responders WHERE guild_id = $1 ORDER BY trigger",
            guild_id,
        )
        records = {
            row.trigger: {
                "trigger": row.trigger,
                "response": row.response,
                "strict": bool(row.strict),
                "reply": bool(row.reply),
                "self_destruct": row.self_destruct,
                "delete_trigger": bool(row.delete_trigger),
                "ignore_command_checks": bool(row.ignore_command_checks),
                "allowed_role_ids": list(row.allowed_role_ids or []),
                "denied_role_ids": list(row.denied_role_ids or []),
                "allowed_channel_ids": list(row.allowed_channel_ids or []),
                "denied_channel_ids": list(row.denied_channel_ids or []),
            }
            for row in rows
        }

        for trigger in await self.db.list_autoresponder_role_triggers(guild_id):
            records.setdefault(
                trigger,
                {
                    "trigger": trigger,
                    "response": "",
                    "strict": True,
                    "reply": False,
                    "self_destruct": None,
                    "delete_trigger": False,
                    "ignore_command_checks": False,
                    "allowed_role_ids": [],
                    "denied_role_ids": [],
                    "allowed_channel_ids": [],
                    "denied_channel_ids": [],
                },
            )

        return [records[key] for key in sorted(records)]

    async def _exclusive_allowed(self, ctx, trigger: str) -> bool:
        rows = await self.db.list_autoresponder_exclusives(ctx.guild.id, trigger)
        if not rows:
            return True

        author_role_ids = {role.id for role in ctx.author.roles}
        for row in rows:
            if row.target_type == "channel" and row.target_id == ctx.channel.id:
                return True
            if row.target_type == "role" and row.target_id in author_role_ids:
                return True
        return False

    async def _send_message_response(self, ctx, record: dict) -> None:
        response = str(record["response"])
        reply_reference = ctx.message if record["reply"] else None

        if _is_embed_script(response):
            try:
                builder = await self.create_embed(
                    response,
                    ctx=ctx,
                    user=ctx.author,
                    member=ctx.author,
                    guild=ctx.guild,
                    channel=ctx.channel,
                )
            except Exception as error:
                with contextlib.suppress(discord.HTTPException):
                    await ctx.send(f"Embed script error: {error}\n`{response}`")
                return
            if record["self_destruct"] is not None:
                builder.data["delete_after"] = record["self_destruct"]
            if reply_reference is not None:
                builder.data["reference"] = reply_reference
            await builder.send(ctx.channel)
            return

        rendered = Script(response, ctx.author).render(
            ctx=ctx,
            user=ctx.author,
            member=ctx.author,
            guild=ctx.guild,
            channel=ctx.channel,
        )
        kwargs = {}
        if record["self_destruct"] is not None:
            kwargs["delete_after"] = record["self_destruct"]
        if reply_reference is not None:
            kwargs["reference"] = reply_reference
        await ctx.send(rendered, **kwargs)

    async def _send_response(self, ctx, record: dict) -> bool:
        rate = await self.bot.object_cache.ratelimited(
            f"auto_responder:{ctx.guild.id}",
            1,
            5,
        )
        if rate:
            await sleep(min(rate, 5))

        if ctx.valid and not record["ignore_command_checks"]:
            return False

        author_role_ids = {role.id for role in ctx.author.roles}
        if author_role_ids & set(record["denied_role_ids"]):
            return False
        if record["allowed_role_ids"] and not (
            author_role_ids & set(record["allowed_role_ids"])
        ):
            return False
        if ctx.channel.id in set(record["denied_channel_ids"]):
            return False
        if record["allowed_channel_ids"] and ctx.channel.id not in set(
            record["allowed_channel_ids"]
        ):
            return False
        if not await self._exclusive_allowed(ctx, record["trigger"]):
            return False

        if record["response"]:
            await self._send_message_response(ctx, record)

        if record["delete_trigger"]:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await ctx.message.delete()

        role_add_ids = await self.db.list_autoresponder_roles(
            ctx.guild.id,
            record["trigger"],
            "add",
        )
        role_remove_ids = await self.db.list_autoresponder_roles(
            ctx.guild.id,
            record["trigger"],
            "remove",
        )
        if role_add_ids or role_remove_ids:
            add_roles = [
                role
                for role_id in role_add_ids
                if (role := ctx.guild.get_role(role_id))
            ]
            remove_roles = [
                role
                for role_id in role_remove_ids
                if (role := ctx.guild.get_role(role_id))
            ]
            if add_roles:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await ctx.author.add_roles(
                        *add_roles,
                        reason="autoresponder role add",
                    )
            if remove_roles:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await ctx.author.remove_roles(
                        *remove_roles,
                        reason="autoresponder role remove",
                    )

        return bool(record["response"] or role_add_ids or role_remove_ids)

    async def _list_triggers(self, ctx, *, tickets_only: bool = False):
        records = await self._collect_records(ctx.guild.id)
        if tickets_only:
            records = [
                record for record in records if "ticket" in record["trigger"].lower()
            ]

        if not records:
            if tickets_only:
                raise CommandError("no ticket autoresponders found")
            raise CommandError("no autoresponders found")

        embed = Embed(title="Auto Responders", color=self.color).set_author(
            name=str(ctx.author),
            icon_url=ctx.author.display_avatar.url,
        )
        lines = []
        for index, record in enumerate(records, start=1):
            if not record["response"]:
                detail = "role response"
            elif _is_embed_script(record["response"]):
                detail = "embed response"
            else:
                detail = "text response"
            if record["response"]:
                detail = f"{detail} ({'strict' if record['strict'] else 'not strict'})"
            lines.append(f"`{index:02d}` **{record['trigger']}** - {detail}")
        return await ctx.paginate(embed, lines)

    async def _role_list(self, ctx, trigger: str, mode: str, title: str):
        role_ids = await self.db.list_autoresponder_roles(ctx.guild.id, trigger, mode)
        if not role_ids:
            raise CommandError("no roles configured for that trigger")

        lines = [
            f"`{index:02d}` {ctx.guild.get_role(role_id).mention if ctx.guild.get_role(role_id) else f'<@&{role_id}>'}"
            for index, role_id in enumerate(role_ids, start=1)
        ]
        return await ctx.paginate(Embed(title=title, color=self.color), lines)

    async def _upsert_autoresponder(self, ctx, raw: str):
        parsed = _split_trigger_response(str(raw))
        if not parsed:
            raise CommandError("expected: trigger, response")

        trigger, response_raw = parsed
        response, flags, error = _parse_response_flags(response_raw)
        if error:
            raise CommandError(error)
        if not response:
            raise CommandError("expected: trigger, response")

        from core.tools.embed import maybe_wrap_embed_script
        response = _normalize_embed_script_urls(maybe_wrap_embed_script(response))
        if _is_embed_script(response):
            try:
                await self.create_embed(
                    response,
                    ctx=ctx,
                    user=ctx.author,
                    member=ctx.author,
                    guild=ctx.guild,
                    channel=ctx.channel,
                )
            except Exception as err:
                raise CommandError(str(err)) from err

        timer = flags["self_destruct"]
        if timer is not None:
            if timer < 6:
                raise CommandError("self-destruct timer must be at least `6` seconds")
            if timer > 60:
                raise CommandError("self-destruct timer must stay under `60` seconds")

        strict = not bool(flags["not_strict"])
        should_delete = bool(flags["delete"])
        should_reply = bool(flags["reply"])
        ignore_command_check = bool(flags["ignore_command_check"])
        existed = bool(
            await self.db.fetchval(
                "SELECT 1 FROM auto_responders WHERE guild_id = $1 AND trigger = $2",
                ctx.guild.id,
                trigger,
            )
        )

        await self.db.execute(
            """
            INSERT INTO auto_responders (
                guild_id,
                trigger,
                response,
                strict,
                reply,
                self_destruct,
                delete_trigger,
                ignore_command_checks
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (guild_id, trigger) DO UPDATE SET
                response = EXCLUDED.response,
                strict = EXCLUDED.strict,
                reply = EXCLUDED.reply,
                self_destruct = EXCLUDED.self_destruct,
                delete_trigger = EXCLUDED.delete_trigger,
                ignore_command_checks = EXCLUDED.ignore_command_checks
            """,
            ctx.guild.id,
            trigger,
            response,
            strict,
            should_reply,
            timer,
            should_delete,
            ignore_command_check,
        )

        details = []
        details.append("strict" if strict else "not strict")
        if should_reply:
            details.append("reply")
        if should_delete:
            details.append("delete trigger")
        if ignore_command_check:
            details.append("ignore command check")
        detail_text = f" ({', '.join(details)})" if details else ""
        if timer is not None:
            detail_text += f"\ndeletes after `{timer}` seconds"

        action = "updated" if existed else "added"
        return await ctx.success(
            f"{action} autoresponder for **{trigger}**{detail_text}"
        )

    @group(
        name="autoresponder",
        aliases=["arp", "autoresponders", "ars", "ar"],
        description="auto-reply to messages matching a trigger",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def autoresponder(self, ctx):
        """Autoresponder help."""
        return await ctx.send_help(ctx.command)

    @autoresponder.command(
        name="reset",
        aliases=["clear"],
        description="Remove every auto response",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_reset(self, ctx):
        """Wipe all autoresponders."""
        await self.db.execute(
            "DELETE FROM auto_responders WHERE guild_id = $1",
            ctx.guild.id,
        )
        await self.db.execute(
            "DELETE FROM autoresponder_exclusive WHERE guild_id = $1",
            ctx.guild.id,
        )
        await self.db.execute(
            "DELETE FROM autoresponder_roles WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success("all autoresponders cleared")

    @autoresponder.command(
        name="variables",
        aliases=["vars"],
        description="View a list of available variables",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_variables(self, ctx):
        """Show available variables."""
        return await ctx.normal(
            "check all **variables** at: https://bleed.bot/resources/scripting/variables",
            emoji=":information_source:",
        )

    @autoresponder.command(
        name="update",
        description="Update a reply for a trigger word",
        example=",autoresponder update welc, welcome to the server! --reply",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_update(self, ctx, *, args: str):
        """Edit an autoresponder."""
        return await self._upsert_autoresponder(ctx, args)

    @autoresponder.command(
        name="remove",
        aliases=["del", "delete"],
        description="Remove a reply for a trigger word",
        example=",autoresponder remove welc",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_remove(self, ctx, *, trigger: str):
        """Remove an autoresponder trigger."""
        removed = await self.db.fetchval(
            """
            WITH removed_auto AS (
                DELETE FROM auto_responders
                WHERE guild_id = $1 AND trigger = $2
                RETURNING 1
            ),
            removed_exclusive AS (
                DELETE FROM autoresponder_exclusive
                WHERE guild_id = $1 AND trigger = $2
                RETURNING 1
            ),
            removed_roles AS (
                DELETE FROM autoresponder_roles
                WHERE guild_id = $1 AND trigger = $2
                RETURNING 1
            )
            SELECT
                COALESCE((SELECT count(*) FROM removed_auto), 0)
                + COALESCE((SELECT count(*) FROM removed_exclusive), 0)
                + COALESCE((SELECT count(*) FROM removed_roles), 0)
            """,
            ctx.guild.id,
            trigger,
        )
        if not removed:
            raise CommandError("no autoresponder found for that trigger")
        return await ctx.success(f"removed autoresponder for `{trigger}`")

    @autoresponder.group(
        name="list",
        aliases=["view", "show", "ls"],
        description="View auto-reply triggers in guild",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_list(self, ctx):
        """Show all autoresponders."""
        return await self._list_triggers(ctx)

    @autoresponder_list.command(name="tickets")
    @has_permissions(manage_channels=True)
    async def autoresponder_list_tickets(self, ctx):
        """Show ticket autoresponders."""
        return await self._list_triggers(ctx, tickets_only=True)

    @autoresponder.command(
        name="add",
        aliases=["create"],
        description="Create a reply for a trigger word",
        example=",autoresponder add welc, welcome to the server! --self_destruct 10 --reply",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_add(self, ctx, *, args: str):
        """Add an autoresponder."""
        return await self._upsert_autoresponder(ctx, args)

    @autoresponder.group(
        name="exclusive",
        invoke_without_command=True,
        description="toggle exclusive access for an autoresponder",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_exclusive(
        self,
        ctx,
        target: Union[Role, TextChannel] = None,
        *,
        trigger: str = None,
    ):
        """Toggle exclusive access to a role or channel."""
        if target is None or trigger is None:
            return await ctx.send_help(ctx.command)

        target_type = "role" if isinstance(target, Role) else "channel"
        added = await self.db.toggle_autoresponder_exclusive(
            ctx.guild.id,
            trigger,
            target_type,
            target.id,
        )
        if added:
            return await ctx.success(
                f"**added** exclusive access for {target.mention} to **{trigger}**"
            )
        return await ctx.success(
            f"**removed** exclusive access for {target.mention} on **{trigger}**"
        )

    @autoresponder_exclusive.command(name="list")
    @has_permissions(manage_channels=True)
    async def autoresponder_exclusive_list(self, ctx, *, trigger: str):
        """View exclusive access entries."""
        rows = await self.db.list_autoresponder_exclusives(ctx.guild.id, trigger)
        if not rows:
            raise CommandError("no exclusive access configured for that trigger")

        lines = []
        for index, row in enumerate(rows, start=1):
            if row.target_type == "role":
                role = ctx.guild.get_role(row.target_id)
                label = role.mention if role else f"<@&{row.target_id}>"
            else:
                channel = ctx.guild.get_channel(row.target_id)
                label = channel.mention if channel else f"<#{row.target_id}>"
            lines.append(f"`{index:02d}` {label}")

        return await ctx.paginate(
            Embed(title="Exclusive Access", color=self.color),
            lines,
        )

    @autoresponder.group(
        name="role",
        invoke_without_command=True,
        description="assign or remove roles on autoresponder trigger",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_role(self, ctx):
        """Autoresponder role help."""
        return await ctx.send_help(ctx.command)

    @autoresponder_role.group(name="add", invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def autoresponder_role_add(
        self,
        ctx,
        role: Role = None,
        *,
        trigger: str = None,
    ):
        """Toggle role assignment on trigger."""
        if role is None or trigger is None:
            return await ctx.send_help(ctx.command)

        added = await self.db.toggle_autoresponder_role(
            ctx.guild.id,
            trigger,
            role.id,
            "add",
        )
        if added:
            return await ctx.success(
                f"**added** {role.mention} assignment upon **{trigger}** trigger"
            )
        return await ctx.success(
            f"**removed** {role.mention} assignment upon **{trigger}** trigger"
        )

    @autoresponder_role_add.command(name="list")
    @has_permissions(manage_channels=True)
    async def autoresponder_role_add_list(self, ctx, *, trigger: str):
        """List role assignments for a trigger."""
        return await self._role_list(ctx, trigger, "add", "Roles Assigned on Trigger")

    @autoresponder_role.group(name="remove", invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def autoresponder_role_remove(
        self,
        ctx,
        role: Role = None,
        *,
        trigger: str = None,
    ):
        """Toggle role removal on trigger."""
        if role is None or trigger is None:
            return await ctx.send_help(ctx.command)

        added = await self.db.toggle_autoresponder_role(
            ctx.guild.id,
            trigger,
            role.id,
            "remove",
        )
        if added:
            return await ctx.success(
                f"**added** {role.mention} removal upon **{trigger}** trigger"
            )
        return await ctx.success(
            f"**removed** {role.mention} removal upon **{trigger}** trigger"
        )

    @autoresponder_role_remove.command(name="list")
    @has_permissions(manage_channels=True)
    async def autoresponder_role_remove_list(self, ctx, *, trigger: str):
        """List role removals for a trigger."""
        return await self._role_list(ctx, trigger, "remove", "Roles Removed on Trigger")

    async def on_context(self, ctx):
        """Handle autoresponders on every guild message context."""
        if ctx.guild is None or ctx.author.bot or not ctx.message.content:
            return

        async with self.ar_locks[f"auto_responder:{ctx.channel.id}"]:
            records = await self._collect_records(ctx.guild.id)
            if not records:
                return

            content = ctx.message.content.lower()
            for record in records:
                trigger = record["trigger"].lower()
                if record["strict"]:
                    if content != trigger:
                        continue
                elif trigger not in content:
                    continue

                handled = await self._send_response(ctx, record)
                if handled:
                    return
