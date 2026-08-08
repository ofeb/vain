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

from .proper.helpers import (
    _split_trigger_response,
    _parse_response_flags,
    _is_embed_script,
    _matches_trigger,
    _normalize_embed_script_urls,
)


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
                    "strict": False,
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
        return sorted(
            records.values(),
            key=lambda r: (-len(str(r.get("trigger") or "")), str(r.get("trigger") or "").lower()),
        )

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
            f"auto_responder:{ctx.guild.id}", 1, 5,
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
            ctx.guild.id, record["trigger"], "add",
        )
        role_remove_ids = await self.db.list_autoresponder_roles(
            ctx.guild.id, record["trigger"], "remove",
        )
        if role_add_ids or role_remove_ids:
            add_roles = [
                role for role_id in role_add_ids
                if (role := ctx.guild.get_role(role_id))
            ]
            remove_roles = [
                role for role_id in role_remove_ids
                if (role := ctx.guild.get_role(role_id))
            ]
            if add_roles:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await ctx.author.add_roles(*add_roles, reason="autoresponder role add")
            if remove_roles:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await ctx.author.remove_roles(*remove_roles, reason="autoresponder role remove")
        return bool(record["response"] or role_add_ids or role_remove_ids)

    async def _list_triggers(self, ctx, *, tickets_only: bool = False):
        records = await self._collect_records(ctx.guild.id)
        if tickets_only:
            records = [r for r in records if "ticket" in r["trigger"].lower()]
        if not records:
            raise CommandError(
                "no ticket autoresponders found" if tickets_only else "no autoresponders found"
            )
        embed = Embed(title="Auto Responders", color=self.color).set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url,
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
                    response, ctx=ctx, user=ctx.author, member=ctx.author,
                    guild=ctx.guild, channel=ctx.channel,
                )
            except Exception as err:
                raise CommandError(str(err)) from err
        timer = flags["self_destruct"]
        if timer is not None:
            if timer < 6:
                raise CommandError("self-destruct timer must be at least `6` seconds")
            if timer > 60:
                raise CommandError("self-destruct timer must stay under `60` seconds")
        strict = bool(flags["strict"]) if flags["strict"] is not None else False
        should_delete = bool(flags["delete"])
        should_reply = bool(flags["reply"])
        ignore_command_check = bool(flags["ignore_command_check"])
        existed = bool(
            await self.db.fetchval(
                "SELECT 1 FROM auto_responders WHERE guild_id = $1 AND trigger = $2",
                ctx.guild.id, trigger,
            )
        )
        await self.db.execute(
            """
            INSERT INTO auto_responders (
                guild_id, trigger, response, strict, reply,
                self_destruct, delete_trigger, ignore_command_checks
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
            ctx.guild.id, trigger, response, strict, should_reply,
            timer, should_delete, ignore_command_check,
        )
        details = ["strict" if strict else "not strict"]
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
        return await ctx.success(f"{action} autoresponder for **{trigger}**{detail_text}")

    @group(
        name="autoresponder",
        aliases=["arp", "autoresponders", "ars", "ar"],
        description=(
            "Auto-reply to messages matching a trigger. "
            "Flags: `--strict`, `--not_strict` (default), `--self_destruct <6-60>`, "
            "`--reply`, `--delete`, `--ignore_command_check`"
        ),
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def autoresponder(self, ctx):
        return await ctx.send_help(ctx.command)

    @autoresponder.command(name="reset", aliases=["clear"], description="Remove every auto response")
    @has_permissions(manage_channels=True)
    async def autoresponder_reset(self, ctx):
        await self.db.execute("DELETE FROM auto_responders WHERE guild_id = $1", ctx.guild.id)
        await self.db.execute("DELETE FROM autoresponder_exclusive WHERE guild_id = $1", ctx.guild.id)
        await self.db.execute("DELETE FROM autoresponder_roles WHERE guild_id = $1", ctx.guild.id)
        return await ctx.success("all autoresponders cleared")

    @autoresponder.command(name="variables", aliases=["vars"], description="View a list of available variables")
    @has_permissions(manage_channels=True)
    async def autoresponder_variables(self, ctx):
        return await ctx.normal(
            "check all **variables** at: https://vain.bot/resources/scripting/variables",
            emoji=":information_source:",
        )

    @autoresponder.command(
        name="update",
        description="Update a reply. Flags: --strict --not_strict --self_destruct <secs> --reply --delete --ignore_command_check",
        example=",autoresponder update welc, welcome to the server! --reply --self_destruct 10",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_update(self, ctx, *, args: str):
        return await self._upsert_autoresponder(ctx, args)

    @autoresponder.command(
        name="remove", aliases=["del", "delete"],
        description="Remove a reply for a trigger word",
        example=",autoresponder remove welc",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_remove(self, ctx, *, trigger: str):
        removed = await self.db.fetchval(
            """
            WITH removed_auto AS (
                DELETE FROM auto_responders WHERE guild_id = $1 AND trigger = $2 RETURNING 1
            ),
            removed_exclusive AS (
                DELETE FROM autoresponder_exclusive WHERE guild_id = $1 AND trigger = $2 RETURNING 1
            ),
            removed_roles AS (
                DELETE FROM autoresponder_roles WHERE guild_id = $1 AND trigger = $2 RETURNING 1
            )
            SELECT COALESCE((SELECT count(*) FROM removed_auto), 0)
                + COALESCE((SELECT count(*) FROM removed_exclusive), 0)
                + COALESCE((SELECT count(*) FROM removed_roles), 0)
            """,
            ctx.guild.id, trigger,
        )
        if not removed:
            raise CommandError("no autoresponder found for that trigger")
        return await ctx.success(f"removed autoresponder for `{trigger}`")

    @autoresponder.group(
        name="list", aliases=["view", "show", "ls"],
        description="View auto-reply triggers in guild",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_list(self, ctx):
        return await self._list_triggers(ctx)

    @autoresponder_list.command(name="tickets")
    @has_permissions(manage_channels=True)
    async def autoresponder_list_tickets(self, ctx):
        return await self._list_triggers(ctx, tickets_only=True)

    @autoresponder.command(
        name="add", aliases=["create"],
        description="Create a reply for a trigger. Flags: --strict --not_strict --self_destruct <secs> --reply --delete --ignore_command_check",
        example=",autoresponder add welc, welcome to the server! --self_destruct 10 --reply --not_strict",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_add(self, ctx, *, args: str):
        return await self._upsert_autoresponder(ctx, args)

    async def _find_trigger(self, guild_id: int, trigger: str) -> str | None:
        row = await self.db.fetchrow(
            "SELECT trigger FROM auto_responders WHERE guild_id = $1 AND LOWER(trigger) = LOWER($2) LIMIT 1",
            guild_id, trigger,
        )
        return row["trigger"] if row else None

    @autoresponder.command(
        name="strict",
        usage="<trigger|all> <on|off>",
        example=",autoresponder strict website off",
        description="Toggle strict matching (default: off). Use 'all' for every trigger.",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_strict(self, ctx, trigger: str, state: str = None):
        if not state:
            if trigger.lower() == "all":
                rows = await self.db.fetch(
                    "SELECT trigger, strict FROM auto_responders WHERE guild_id = $1",
                    ctx.guild.id,
                )
                if not rows:
                    raise CommandError("no autoresponders found")
                strict_n = sum(1 for r in rows if r["strict"])
                return await ctx.success(
                    f"**{strict_n}** strict · **{len(rows) - strict_n}** not strict (of {len(rows)})"
                )
            stored = await self._find_trigger(ctx.guild.id, trigger)
            if not stored:
                raise CommandError(f"no autoresponder for **{trigger}**")
            row = await self.db.fetchrow(
                "SELECT strict FROM auto_responders WHERE guild_id = $1 AND trigger = $2",
                ctx.guild.id, stored,
            )
            mode = "strict" if row and row["strict"] else "not strict"
            return await ctx.success(f"**{stored}** is **{mode}**")
        low = state.lower().strip()
        if low in {"on", "enable", "true", "yes", "1", "strict"}:
            strict = True
        elif low in {"off", "disable", "false", "no", "0", "loose", "not_strict", "not-strict"}:
            strict = False
        else:
            return await ctx.warn("Use `on` or `off`")
        if trigger.lower() in {"all", "*", "every"}:
            await self.db.execute(
                "UPDATE auto_responders SET strict = $2 WHERE guild_id = $1",
                ctx.guild.id, strict,
            )
            return await ctx.success(
                f"All autoresponders are now **{'strict' if strict else 'not strict'}**"
            )
        stored = await self._find_trigger(ctx.guild.id, trigger)
        if not stored:
            raise CommandError(f"no autoresponder for **{trigger}**")
        await self.db.execute(
            "UPDATE auto_responders SET strict = $3 WHERE guild_id = $1 AND trigger = $2",
            ctx.guild.id, stored, strict,
        )
        return await ctx.success(
            f"**{stored}** is now **{'strict' if strict else 'not strict'}**"
        )

    @autoresponder.group(
        name="exclusive", invoke_without_command=True,
        description="toggle exclusive access for an autoresponder",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_exclusive(
        self, ctx, target: Union[Role, TextChannel] = None, *, trigger: str = None,
    ):
        if target is None or trigger is None:
            return await ctx.send_help(ctx.command)
        target_type = "role" if isinstance(target, Role) else "channel"
        added = await self.db.toggle_autoresponder_exclusive(
            ctx.guild.id, trigger, target_type, target.id,
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
        return await ctx.paginate(Embed(title="Exclusive Access", color=self.color), lines)

    @autoresponder.group(
        name="role", invoke_without_command=True,
        description="assign or remove roles on autoresponder trigger",
    )
    @has_permissions(manage_channels=True)
    async def autoresponder_role(self, ctx):
        return await ctx.send_help(ctx.command)

    @autoresponder_role.group(name="add", invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def autoresponder_role_add(self, ctx, role: Role = None, *, trigger: str = None):
        if role is None or trigger is None:
            return await ctx.send_help(ctx.command)
        added = await self.db.toggle_autoresponder_role(ctx.guild.id, trigger, role.id, "add")
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
        return await self._role_list(ctx, trigger, "add", "Roles Assigned on Trigger")

    @autoresponder_role.group(name="remove", invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def autoresponder_role_remove(self, ctx, role: Role = None, *, trigger: str = None):
        if role is None or trigger is None:
            return await ctx.send_help(ctx.command)
        added = await self.db.toggle_autoresponder_role(ctx.guild.id, trigger, role.id, "remove")
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
        return await self._role_list(ctx, trigger, "remove", "Roles Removed on Trigger")

    async def on_context(self, ctx):
        if ctx.guild is None or ctx.author.bot or not ctx.message.content:
            return
        async with self.ar_locks[f"auto_responder:{ctx.channel.id}"]:
            records = await self._collect_records(ctx.guild.id)
            if not records:
                return
            content = ctx.message.content
            for record in records:
                trigger = str(record["trigger"] or "").strip()
                if not trigger:
                    continue
                if not _matches_trigger(content, trigger, strict=bool(record.get("strict"))):
                    continue
                handled = await self._send_response(ctx, record)
                if handled:
                    return
