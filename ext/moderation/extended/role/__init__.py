from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import timedelta
from typing import Literal, Optional

import aiohttp
import discord
import humanize
import orjson
from discord.ext import commands
from discord.ext.commands import (
    BucketType,
    CommandError,
    MaxConcurrency,
    MaxConcurrencyReached,
    Range,
    group,
)

from core.discord.package import Package
from core.discord.views.confirm import ConfirmView
from core.discord.views.embed import panel_embed
from core.managers.permissions import has_permissions
from core.tools.convert.color import ColorConvert
from core.tools.convert.role import RoleConvert
from core.tools.guild_members import collect_guild_members
from core.tools.hierarchy import ensure_member_hierarchy
from core.tools.human.text import join as human_join
from core.tools.human.text import plural
from core.tools.moderation_logs import build_modlog_embed, send_c2_embed
from core.tools.pages import Paginator, build_pages

MASS_ROLE_CONCURRENCY = MaxConcurrency(1, per=BucketType.guild, wait=False)


def _eta(count: int) -> str:
    """Rough ETA for mass role ops (~1 action/sec)."""
    return humanize.naturaldelta(timedelta(seconds=max(1, int(count))))


async def _quietly_delete(message: discord.Message | None) -> None:
    if message is None:
        return
    with contextlib.suppress(discord.HTTPException, discord.NotFound):
        await message.delete()


async def do_mass_role(
    ctx: commands.Context,
    role: discord.Role,
    predicate: Callable[[discord.Member], bool] = lambda _: True,
    action: Literal["add", "remove"] = "add",
) -> discord.Message | None:
    """Helper for mass role add/remove operations."""
    if ctx.guild is None:
        raise CommandError("This command can only be used in a server")

    me = ctx.guild.me
    if me is None or not me.guild_permissions.manage_roles:
        raise CommandError("I don't have permission to manage roles")

    members = await collect_guild_members(ctx.guild, cache=True)
    verb = "to" if action == "add" else "from"
    targets: list[discord.Member] = []

    for member in members:
        if not predicate(member):
            continue
        try:
            await ensure_member_hierarchy(ctx, member, allow_self=True)
        except CommandError:
            continue
        if action == "add" and role in member.roles:
            continue
        if action == "remove" and role not in member.roles:
            continue
        targets.append(member)

    if not targets:
        raise CommandError(f"No members to {action} {role.mention} {verb}")

    pending = await ctx.warn(
        f"{action.title()[:5]}ing {role.mention} {verb} "
        f"**{plural(len(targets), 'member')}**...\n"
        f"> -# This should take around **{_eta(len(targets))}**",
    )

    success: list[discord.Member] = []
    failures: list[discord.Member] = []
    key = MASS_ROLE_CONCURRENCY.get_key(ctx)

    async with ctx.typing():
        for member in targets:
            if not MASS_ROLE_CONCURRENCY._mapping.get(key):
                break
            method = getattr(member, f"{action}_roles")
            try:
                await method(
                    role,
                    reason=f"Mass {action} by {ctx.author} ({ctx.author.id})",
                )
            except discord.HTTPException:
                failures.append(member)
                if len(failures) >= 6:
                    break
            else:
                success.append(member)

    await _quietly_delete(pending if isinstance(pending, discord.Message) else None)

    parts = [
        f"Successfully {action[:5]}ed {role.mention} {verb} "
        f"**{plural(len(success), 'member')}**"
    ]
    if failures:
        parts.append(
            f"Failed to {action} {role.mention} {verb} "
            f"**{plural(len(failures), 'member')}**"
        )
    return await ctx.success("\n".join(parts))


class Role(Package):
    """role management"""

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._role_tables_ready = False

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: Exception,
    ) -> None:
        if isinstance(error, MaxConcurrencyReached) and ctx.command and str(
            ctx.command.qualified_name
        ).startswith("role"):
            with contextlib.suppress(Exception):
                await ctx.warn(
                    "There is already an ongoing mass role operation\n"
                    f"> -# Cancel it early with `{ctx.clean_prefix}role cancel`"
                )
            return
        return

    async def _ensure_tables(self) -> None:
        if self._role_tables_ready or getattr(self.db, "pool", None) is None:
            return
        with contextlib.suppress(Exception):
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS role_reassign (
                    guild_id BIGINT PRIMARY KEY,
                    enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    ignored_role_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[]
                )
                """
            )
            self._role_tables_ready = True

    def role_cache_key(self, member: discord.Member) -> str:
        return f"roles:{member.guild.id}-{member.id}"

    async def _cache_set_roles(self, key: str, role_ids: list[int], ex: int = 3600) -> None:
        redis = self.redis
        if redis is None:
            return
        payload = orjson.dumps(role_ids)
        with contextlib.suppress(Exception):
            await redis.set(key, payload, ex=ex)

    async def _cache_get_roles(self, key: str) -> list[int]:
        redis = self.redis
        if redis is None:
            return []
        try:
            raw = await redis.get(key)
        except Exception:
            return []
        if not raw:
            return []
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            data = orjson.loads(raw)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        out: list[int] = []
        for item in data:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out

    async def _cache_delete(self, key: str) -> None:
        redis = self.redis
        if redis is None:
            return
        with contextlib.suppress(Exception):
            await redis.delete(key)

    async def _get_reassign(self, guild_id: int) -> tuple[bool, list[int]]:
        await self._ensure_tables()
        if getattr(self.db, "pool", None) is None:
            return False, []
        row = await self.db.fetchrow(
            "SELECT enabled, ignored_role_ids FROM role_reassign WHERE guild_id = $1",
            guild_id,
        )
        if not row:
            return False, []
        ignored = list(row.get("ignored_role_ids") or [])
        return bool(row.get("enabled")), [int(x) for x in ignored]

    async def _set_reassign_enabled(self, guild_id: int, enabled: bool) -> bool:
        await self._ensure_tables()
        if getattr(self.db, "pool", None) is None:
            return enabled
        await self.db.execute(
            """
            INSERT INTO role_reassign (guild_id, enabled)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """,
            guild_id,
            enabled,
        )
        return enabled

    async def _set_reassign_ignored(self, guild_id: int, role_ids: list[int]) -> None:
        await self._ensure_tables()
        if getattr(self.db, "pool", None) is None:
            return
        await self.db.execute(
            """
            INSERT INTO role_reassign (guild_id, ignored_role_ids)
            VALUES ($1, $2::BIGINT[])
            ON CONFLICT (guild_id) DO UPDATE
            SET ignored_role_ids = EXCLUDED.ignored_role_ids
            """,
            guild_id,
            role_ids,
        )

    def _audit_reason(self, ctx, reason: str | None) -> str:
        base = reason or "no reason provided"
        return f"{base} | executed by {ctx.author} ({ctx.author.id})"

    def _default_reason(self, reason: str | None) -> str:
        return reason or "no reason provided"

    async def _ensure_manageable_role(
        self,
        ctx,
        role: discord.Role,
        *,
        action: str = "manage",
        check_integrated: bool = True,
        check_dangerous: bool = False,
    ) -> bool:
        if ctx.guild is None:
            await ctx.warn("This command can only be used in a server")
            return False
        if role == ctx.guild.default_role:
            await ctx.warn(f"You **can't** {action} the default role")
            return False
        if check_integrated and role.managed:
            await ctx.warn(f"You **can't** {action} an integration role")
            return False

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        bot_member = ctx.guild.me or ctx.guild.get_member(
            self.bot.user.id if self.bot.user else 0
        )
        if author and ctx.guild.owner_id != author.id and role >= author.top_role:
            await ctx.warn("That role is above or equal to your highest role")
            return False
        if bot_member is None:
            await ctx.warn("I could not resolve my server member")
            return False
        if role >= bot_member.top_role:
            await ctx.warn("That role is above or equal to my highest role")
            return False

        if check_dangerous:
            try:
                await RoleConvert.dangerous(ctx, role, action=action)
            except CommandError as exc:
                await ctx.warn(str(exc))
                return False
        return True

    async def _ensure_targetable_member(self, ctx, member: discord.Member) -> bool:
        if ctx.guild is None:
            await ctx.warn("This command can only be used in a server")
            return False
        try:
            await ensure_member_hierarchy(ctx, member, allow_self=False)
        except CommandError as exc:
            await ctx.warn(str(exc))
            return False
        return True

    async def _create_case(
        self,
        ctx,
        *,
        action: str,
        target_id: int,
        reason: str | None,
    ) -> int | None:
        if getattr(self.db, "pool", None) is None:
            return None
        return await self.db.create_case(
            guild_id=ctx.guild.id,
            action=action,
            target_id=target_id,
            moderator_id=ctx.author.id,
            reason=self._default_reason(reason),
        )

    async def _send_modlog(
        self,
        ctx,
        *,
        action: str,
        target: discord.abc.User | str | None = None,
        target_name: str | None = None,
        case_id: int | None = None,
        reason: str | None = None,
        extra: str | None = None,
    ) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        channel_id = await self.db.get_modlog_channel(ctx.guild.id)
        if not channel_id:
            return
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        if target_name is not None:
            target_label = target_name
        elif isinstance(target, str):
            target_label = target
        elif target is not None:
            target_label = getattr(target, "mention", None) or str(target)
        else:
            target_label = "Unknown User"

        embed = build_modlog_embed(
            color=None,
            action=action,
            target_label=target_label,
            moderator_label=ctx.author.mention,
            reason=self._default_reason(reason),
            case_id=case_id,
            extra=extra,
        )
        await send_c2_embed(channel, embed)

    

    @Package.listener("on_member_remove")
    async def role_cache(self, member: discord.Member) -> None:
        if member.bot:
            return
        me = member.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return
        role_ids = [role.id for role in member.roles if role.is_assignable()]
        if not role_ids:
            return
        await self._cache_set_roles(self.role_cache_key(member), role_ids, ex=3600)

    @Package.listener("on_member_join")
    async def role_restore_cache(self, member: discord.Member) -> None:
        guild = member.guild
        if member.bot:
            return
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return

        key = self.role_cache_key(member)
        role_ids = await self._cache_get_roles(key)
        if not role_ids:
            return

        enabled, ignored = await self._get_reassign(guild.id)
        if not enabled:
            return

        ignored_set = set(ignored)
        roles = [
            role
            for role_id in role_ids
            if (role := guild.get_role(role_id)) is not None
            and role.is_assignable()
            and role not in member.roles
            and role.id not in ignored_set
            and role < me.top_role
        ]
        if not roles:
            return

        await self._cache_delete(key)
        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            await member.add_roles(*roles, reason="Reassigned from cache")

    

    @group(
        name="role",
        aliases=("r",),
        description="Toggle a role on a member. Subcommands for add/remove/mass/etc.",
        invoke_without_command=True,
        example=",role @hroe developer",
    )
    @has_permissions(manage_roles=True)
    async def role(self, ctx, *, args: str | None = None) -> None:
        """Toggle a role. Usage: ``r @user RoleName`` (add if missing, remove if present).

        Multi-member: ``r @a @b Role Name``. Parsing stops consuming members once the
        remaining tokens form a valid role - so a role named ``member`` is never
        fuzzy-matched as a second user.
        """
        member_list, target_role = await self._parse_role_targets(ctx, args)
        if not member_list or target_role is None:
            return await ctx.send_help(ctx.command)

        for member in member_list:
            if target_role in member.roles:
                await self.role_remove.callback(
                    self, ctx, member, target_role, reason=None
                )
            else:
                await self.role_add.callback(
                    self, ctx, member, target_role, reason=None
                )

    async def _parse_role_targets(
        self, ctx, args: str | None
    ) -> tuple[list[discord.Member], discord.Role | None]:
        """Parse ``[member...] role name`` without Greedy fuzzy eating the role."""
        body = (args or "").strip()
        if not body and ctx.message and ctx.message.content:
            raw = ctx.message.content
            invoker = (ctx.invoked_with or "role").lower()
            prefix = str(ctx.prefix or "")
            if prefix and raw.startswith(prefix):
                raw = raw[len(prefix) :]
            parts = raw.split(None, 1)
            if parts and parts[0].lower() in {invoker, "role", "r"}:
                body = parts[1] if len(parts) > 1 else ""
            else:
                body = raw.strip()

        tokens = body.split()
        if len(tokens) < 2:
            return [], None

        member_conv = commands.MemberConverter()
        role_conv = RoleConvert()

        
        
        
        for member_count in range(1, len(tokens)):
            member_tokens = tokens[:member_count]
            role_name = " ".join(tokens[member_count:]).strip()
            if not role_name:
                continue

            members: list[discord.Member] = []
            ok = True
            for tok in member_tokens:
                try:
                    members.append(await member_conv.convert(ctx, tok))
                except Exception:
                    ok = False
                    break
            if not ok or not members:
                continue

            try:
                role = await role_conv.convert(ctx, role_name)
            except Exception:
                continue

            
            seen: set[int] = set()
            unique: list[discord.Member] = []
            for m in members:
                if m.id not in seen:
                    seen.add(m.id)
                    unique.append(m)
            return unique, role

        return [], None

    @role.command(
        name="add",
        aliases=("grant",),
        description="Adds role to a member",
        example=",role add @member @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_add(
        self,
        ctx,
        member: discord.Member,
        role: RoleConvert,
        *,
        reason: str | None = None,
    ) -> discord.Message | None:
        """Add a role to a member."""
        target_role: discord.Role = role  # type: ignore[assignment]
        if not await self._ensure_targetable_member(ctx, member):
            return None
        if not await self._ensure_manageable_role(ctx, target_role, action="give"):
            return None
        if target_role in member.roles:
            return await ctx.warn(
                f"{member.mention} already has {target_role.mention}"
            )

        await member.add_roles(target_role, reason=self._audit_reason(ctx, reason))
        case_id = await self._create_case(
            ctx, action="role add", target_id=member.id, reason=reason
        )
        await self._send_modlog(
            ctx,
            action="role add",
            target_name=f"{member} -> {target_role.name}",
            case_id=case_id,
            reason=reason,
        )
        return await ctx.success(f"Added {target_role.mention} to {member.mention}")

    @role.command(
        name="remove",
        aliases=("revoke", "rm"),
        description="Removes role from a member",
        example=",role remove @member @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_remove(
        self,
        ctx,
        member: discord.Member,
        role: RoleConvert,
        *,
        reason: str | None = None,
    ) -> discord.Message | None:
        """Remove a role from a member."""
        target_role: discord.Role = role  # type: ignore[assignment]
        if not await self._ensure_targetable_member(ctx, member):
            return None
        if not await self._ensure_manageable_role(ctx, target_role, action="remove"):
            return None
        if target_role not in member.roles:
            return await ctx.warn(
                f"{member.mention} doesn't have {target_role.mention}"
            )

        await member.remove_roles(target_role, reason=self._audit_reason(ctx, reason))
        case_id = await self._create_case(
            ctx, action="role remove", target_id=member.id, reason=reason
        )
        await self._send_modlog(
            ctx,
            action="role remove",
            target_name=f"{member} -> {target_role.name}",
            case_id=case_id,
            reason=reason,
        )
        return await ctx.success(
            f"Removed {target_role.mention} from {member.mention}"
        )

    

    @role.group(
        name="restore",
        aliases=("reassign", "cache"),
        description="Restore a member's roles from cache",
        invoke_without_command=True,
        example=",role restore @member",
    )
    @has_permissions(manage_roles=True)
    async def role_restore(self, ctx, member: discord.Member) -> discord.Message | None:
        """Restore a member's roles from cache."""
        if not await self._ensure_targetable_member(ctx, member):
            return None

        key = self.role_cache_key(member)
        role_ids = await self._cache_get_roles(key)
        roles: list[discord.Role] = []
        for role_id in role_ids:
            role = member.guild.get_role(role_id)
            if not role or role in member.roles:
                continue
            if not await self._ensure_manageable_role(
                ctx, role, action="restore", check_dangerous=True
            ):
                continue
            roles.append(role)

        if not roles:
            return await ctx.warn(f"No roles to restore for {member.mention}")

        labels = human_join([role.mention for role in roles], final="and")
        await member.add_roles(
            *roles,
            reason=f"Restored from cache by {ctx.author} ({ctx.author.id})",
        )
        return await ctx.success(f"Restored {labels} to {member.mention}")

    @role_restore.group(
        name="reassign",
        aliases=("rejoin", "auto"),
        description="Toggle auto reassigning roles when members rejoin",
        invoke_without_command=True,
        example=",role restore reassign",
    )
    @has_permissions(manage_roles=True)
    async def role_restore_reassign(self, ctx) -> discord.Message | None:
        """Toggle auto reassigning roles when members rejoin."""
        enabled, _ = await self._get_reassign(ctx.guild.id)
        new_value = await self._set_reassign_enabled(ctx.guild.id, not enabled)
        return await ctx.success(
            f"{'Now' if new_value else 'No longer'} reassigning roles when members rejoin"
        )

    @role_restore_reassign.group(
        name="exclude",
        aliases=("exempt", "ignore"),
        description="Exclude a role from being re-assigned",
        invoke_without_command=True,
        example=",role restore reassign exclude @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_restore_reassign_ignore(
        self,
        ctx,
        *,
        role: RoleConvert,
    ) -> discord.Message | None:
        """Exclude a role from being re-assigned."""
        _, ignored = await self._get_reassign(ctx.guild.id)
        if role.id in ignored:
            return await ctx.warn(
                f"Already excluding {role.mention} from being re-assigned"
            )
        ignored.append(role.id)
        await self._set_reassign_ignored(ctx.guild.id, ignored)
        return await ctx.success(f"Now excluding {role.mention} when reassigning roles")

    @role_restore_reassign_ignore.command(
        name="remove",
        aliases=("rm",),
        description="Allow a role to be re-assigned",
        example=",role restore reassign exclude remove @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_restore_reassign_ignore_remove(
        self,
        ctx,
        *,
        role: RoleConvert,
    ) -> discord.Message | None:
        """Allow a role to be re-assigned."""
        _, ignored = await self._get_reassign(ctx.guild.id)
        if role.id not in ignored:
            return await ctx.warn(f"Already allowing {role.mention} to be re-assigned")
        ignored = [rid for rid in ignored if rid != role.id]
        await self._set_reassign_ignored(ctx.guild.id, ignored)
        return await ctx.success(f"Now allowing {role.mention} to be re-assigned")

    @role_restore_reassign_ignore.command(
        name="clear",
        aliases=("reset",),
        description="Remove all roles that are being excluded",
        example=",role restore reassign exclude clear",
    )
    @has_permissions(manage_roles=True)
    async def role_restore_reassign_ignore_clear(self, ctx) -> discord.Message | None:
        """Remove all roles that are being excluded."""
        await self._set_reassign_ignored(ctx.guild.id, [])
        return await ctx.success("Now allowing all roles to be re-assigned")

    @role_restore_reassign_ignore.command(
        name="list",
        description="View all roles that are being excluded",
        example=",role restore reassign exclude list",
    )
    @has_permissions(manage_roles=True)
    async def role_restore_reassign_ignore_list(self, ctx) -> discord.Message | None:
        """View all roles that are being excluded."""
        _, ignored = await self._get_reassign(ctx.guild.id)
        roles = [r for rid in ignored if (r := ctx.guild.get_role(rid))]
        if not roles:
            return await ctx.warn("No roles are excluded from being re-assigned")

        entries = [f"{role.mention} (`{role.id}`)" for role in roles]
        embed = panel_embed(title="Excluded Roles", color=None, timestamp=False)
        pages = build_pages(embed, entries, split=10)
        return await Paginator(ctx, pages).start()

    

    @role.command(
        name="create",
        aliases=("make",),
        description="Creates a role with optional color",
        example=",role create #ff0000 Staff",
    )
    @has_permissions(manage_roles=True)
    async def role_create(
        self,
        ctx,
        color: Optional[ColorConvert] = None,
        hoist: Optional[bool] = None,
        *,
        name: Range[str, 1, 100],
    ) -> discord.Message | None:
        """Create a role."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if len(ctx.guild.roles) >= 250:
            return await ctx.warn("This server has reached the maximum amount of roles")

        role = await ctx.guild.create_role(
            name=name,
            color=color or discord.Color.default(),
            hoist=bool(hoist) if hoist is not None else False,
            reason=self._audit_reason(ctx, None),
        )
        case_id = await self._create_case(
            ctx, action="role create", target_id=role.id, reason=None
        )
        await self._send_modlog(
            ctx, action="role create", target_name=role.name, case_id=case_id, reason=None
        )
        return await ctx.success(f"Created the {role.mention} role")

    @role.command(
        name="duplicate",
        aliases=("copy",),
        description="Duplicate a role with a new name",
        example=",role duplicate @Role New Name",
    )
    @has_permissions(manage_roles=True)
    async def role_duplicate(
        self,
        ctx,
        role: RoleConvert,
        color: Optional[ColorConvert] = None,
        hoist: Optional[bool] = None,
        *,
        name: Range[str, 1, 100],
    ) -> discord.Message | None:
        """Duplicate a role with a new name."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if len(ctx.guild.roles) >= 250:
            return await ctx.warn("This server has reached the maximum amount of roles")
        if not await self._ensure_manageable_role(
            ctx, role, action="duplicate", check_integrated=False
        ):
            return None

        new_role = await ctx.guild.create_role(
            name=name,
            color=color or role.color,
            hoist=hoist if hoist is not None else role.hoist,
            permissions=role.permissions,
            reason=self._audit_reason(ctx, None),
        )
        return await ctx.success(f"Duplicated {role.mention} as {new_role.mention}")

    @role.command(
        name="delete",
        aliases=("del",),
        description="Deletes a role",
        example=",role delete @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_delete(
        self,
        ctx,
        role: RoleConvert,
        *,
        reason: str | None = None,
    ) -> discord.Message | None:
        """Delete a role."""
        if not await self._ensure_manageable_role(ctx, role, action="delete"):
            return None

        if role.members:
            confirmed = await ConfirmView(ctx).prompt(
                f"{role.mention} has **{plural(len(role.members), 'member')}**, "
                "are you sure you want to delete it?"
            )
            if not confirmed:
                return await ctx.warn("Role deletion cancelled")

        snapshot = {
            "name": role.name,
            "permissions": role.permissions.value,
            "color": role.color.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "position": role.position,
        }
        role_name = role.name
        role_id = role.id
        await role.delete(reason=self._audit_reason(ctx, reason))

        case_id = await self._create_case(
            ctx, action="role delete", target_id=role_id, reason=reason
        )
        await self._send_modlog(
            ctx,
            action="role delete",
            target_name=role_name,
            case_id=case_id,
            reason=reason,
        )
        if ctx.guild is not None and isinstance(ctx.author, discord.Member):
            ctx.bot.dispatch(
                "antinuke_action",
                ctx.guild,
                ctx.author,
                "role delete",
                case_id or 0,
                {"role": snapshot, "role_id": role_id},
            )
        return await ctx.success(f"Deleted role **{role_name}**")

    @role.command(
        name="color",
        aliases=("colour",),
        description="Set a color for a role",
        example=",role color @Role #ff0000",
    )
    @has_permissions(manage_roles=True)
    async def role_color(
        self,
        ctx,
        role: RoleConvert,
        *,
        color: ColorConvert,
    ) -> discord.Message | None:
        """Change a role's color."""
        if not await self._ensure_manageable_role(
            ctx, role, action="recolor", check_integrated=False
        ):
            return None
        await role.edit(color=color, reason=self._audit_reason(ctx, None))
        return await ctx.success(f"Changed {role.mention}'s color to `{color}`")

    @role.command(
        name="rename",
        aliases=("name", "edit"),
        description="Change a role name",
        example=",role rename @Role New Name",
    )
    @has_permissions(manage_roles=True)
    async def role_rename(
        self,
        ctx,
        role: RoleConvert,
        *,
        name: Range[str, 1, 100],
    ) -> discord.Message | None:
        """Change a role's name."""
        if not await self._ensure_manageable_role(
            ctx, role, action="rename", check_integrated=False
        ):
            return None
        await role.edit(name=name, reason=self._audit_reason(ctx, None))
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.add_reaction("✅")
        return await ctx.success(f"Renamed role to **{name}**")

    @role.command(
        name="hoist",
        description="Toggle hoisting a role",
        example=",role hoist @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_hoist(self, ctx, *, role: RoleConvert) -> discord.Message | None:
        """Toggle if a role should appear in the sidebar."""
        if not await self._ensure_manageable_role(
            ctx, role, action="hoist", check_integrated=False
        ):
            return None
        await role.edit(hoist=not role.hoist, reason=self._audit_reason(ctx, None))
        return await ctx.success(
            f"{role.mention} is {'now' if role.hoist else 'no longer'} hoisted"
        )

    @role.command(
        name="mentionable",
        description="Toggle mentioning a role",
        example=",role mentionable @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_mentionable(
        self, ctx, *, role: RoleConvert
    ) -> discord.Message | None:
        """Toggle if a role should be mentionable."""
        if not await self._ensure_manageable_role(
            ctx, role, action="edit", check_integrated=False
        ):
            return None
        await role.edit(
            mentionable=not role.mentionable, reason=self._audit_reason(ctx, None)
        )
        return await ctx.success(
            f"{role.mention} is {'now' if role.mentionable else 'no longer'} mentionable"
        )

    async def _resolve_role_icon(
        self,
        ctx,
        source: str | None = None,
    ) -> bytes | str | None:
        """Resolve a role icon from emoji, URL, or attached image.

        Returns:
            - ``bytes`` for custom emoji / URL / attachment images
            - ``str`` for unicode emoji (Discord accepts these directly)
            - ``None`` to clear the icon
        """
        if ctx.message and ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            content_type = (attachment.content_type or "").lower()
            filename = (attachment.filename or "").lower()
            is_image = content_type.startswith("image/") or filename.endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp")
            )
            if not is_image:
                raise CommandError("Attached file must be an **image**")
            data = await attachment.read()
            if len(data) > 256 * 1024:
                raise CommandError("Role icons must be **256 KB** or smaller")
            return data

        if not source:
            return None

        raw = source.strip()
        if not raw:
            return None

        try:
            partial = discord.PartialEmoji.from_str(raw)
        except Exception:
            partial = None

        if partial is not None and partial.is_custom_emoji() and partial.id:
            ext = "gif" if partial.animated else "png"
            cdn_url = f"https://cdn.discordapp.com/emojis/{partial.id}.{ext}?size=256&quality=lossless"
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(cdn_url) as resp:
                        if resp.status != 200:
                            raise CommandError("Could not download that **emoji**")
                        data = await resp.read()
            except CommandError:
                raise
            except Exception as exc:
                raise CommandError("Could not download that **emoji**") from exc
            if len(data) > 256 * 1024:
                raise CommandError("Role icons must be **256 KB** or smaller")
            return data

        if raw.startswith(("http://", "https://")):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(raw) as resp:
                        if resp.status != 200:
                            raise CommandError("Could not download that image")
                        content_type = (resp.headers.get("Content-Type") or "").lower()
                        if content_type and not content_type.startswith("image/"):
                            raise CommandError("URL must point to an **image**")
                        data = await resp.read()
            except CommandError:
                raise
            except Exception as exc:
                raise CommandError("Could not download that image") from exc
            if len(data) > 256 * 1024:
                raise CommandError("Role icons must be **256 KB** or smaller")
            return data

        if raw.startswith(("<@", "<#")):
            raise CommandError(
                "Provide a **custom emoji**, **unicode emoji**, **image URL**, or **attachment**"
            )

        if len(raw) <= 16 and not raw.isascii():
            return raw
        if len(raw) <= 8 and all(
            ord(ch) > 127 or ch.isspace() or ch in "️‍" for ch in raw
        ):
            return raw

        raise CommandError(
            "Provide a **custom emoji**, **unicode emoji**, **image URL**, or **attachment**"
        )

    @role.command(
        name="icon",
        description="Set a role icon from an emoji, URL, or image",
        example=",role icon @Role ⭐",
        usage="(role) [emoji or url or attachment]",
    )
    @has_permissions(manage_roles=True)
    async def role_icon(
        self,
        ctx,
        role: RoleConvert,
        *,
        icon: str | None = None,
    ) -> discord.Message | None:
        """Set or clear a role icon (emoji, URL, or attached image). Requires boost level 2."""
        if not await self._ensure_manageable_role(
            ctx, role, action="icon", check_integrated=False
        ):
            return None
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        features = {str(f).upper() for f in getattr(ctx.guild, "features", ()) or ()}
        if ctx.guild.premium_tier < 2 and "ROLE_ICONS" not in features:
            return await ctx.warn("Role icons require server boost level **2**")

        try:
            resolved = await self._resolve_role_icon(ctx, icon)
        except CommandError as exc:
            return await ctx.warn(str(exc))

        try:
            await role.edit(
                display_icon=resolved,
                reason=self._audit_reason(ctx, None),
            )
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to edit that role icon")
        except discord.HTTPException as exc:
            return await ctx.fail(f"Failed to update the role icon: {exc}")

        if resolved is None:
            return await ctx.success(f"Cleared the icon for {role.mention}")
        if isinstance(resolved, str):
            return await ctx.success(
                f"Updated the icon for {role.mention} to {resolved}"
            )
        return await ctx.success(f"Updated the icon for {role.mention}")

    @role.command(
        name="topcolor",
        description="Changes your highest roles color",
        example=",role topcolor #ff0000",
    )
    @has_permissions(manage_roles=True)
    async def role_topcolor(
        self,
        ctx,
        color: ColorConvert,
        member: discord.Member | None = None,
    ) -> discord.Message | None:
        """Change a member's highest colored role color."""
        target = member or (
            ctx.author if isinstance(ctx.author, discord.Member) else None
        )
        if target is None:
            return await ctx.warn("Could not resolve target member")
        if member is not None and not await self._ensure_targetable_member(ctx, target):
            return None

        candidates = [
            r
            for r in target.roles
            if r.color.value != 0 and not r.is_default() and not r.managed
        ]
        if not candidates:
            return await ctx.warn(f"{target.mention} has no colored roles")
        top = max(candidates, key=lambda r: r.position)
        if not await self._ensure_manageable_role(
            ctx, top, action="recolor", check_integrated=False
        ):
            return None
        await top.edit(color=color, reason=self._audit_reason(ctx, None))
        return await ctx.success(
            f"Changed {target.mention}'s top role {top.mention} color to `{color}`"
        )

    

    @role.command(
        name="cancel",
        description="Cancels a mass role task running",
        example=",role cancel",
    )
    @has_permissions(manage_roles=True)
    async def role_cancel(self, ctx) -> discord.Message | None:
        """Cancel an ongoing mass role operation."""
        key = MASS_ROLE_CONCURRENCY.get_key(ctx)
        if key not in MASS_ROLE_CONCURRENCY._mapping:
            return await ctx.warn("There isn't an ongoing mass role operation to cancel")
        await MASS_ROLE_CONCURRENCY.release(ctx)
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.add_reaction("✅")
        return await ctx.success("Cancelled the mass role operation")

    @role.group(
        name="all",
        aliases=("everyone",),
        description="Add a role to all members",
        invoke_without_command=True,
        max_concurrency=MASS_ROLE_CONCURRENCY,
        example=",role all @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_all(self, ctx, *, role: RoleConvert) -> discord.Message | None:
        """Add a role to all members."""
        if not await self._ensure_manageable_role(
            ctx, role, action="mass-add", check_dangerous=True
        ):
            return None
        return await do_mass_role(ctx, role)

    @role_all.command(
        name="remove",
        aliases=("revoke", "rm"),
        description="Remove a role from all members",
        max_concurrency=MASS_ROLE_CONCURRENCY,
        example=",role all remove @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_all_remove(
        self, ctx, *, role: RoleConvert
    ) -> discord.Message | None:
        """Remove a role from all members."""
        if not await self._ensure_manageable_role(ctx, role, action="mass-remove"):
            return None
        return await do_mass_role(
            ctx,
            role,
            lambda member: role in member.roles,
            action="remove",
        )

    @role.group(
        name="humans",
        description="Add a role to all humans",
        invoke_without_command=True,
        max_concurrency=MASS_ROLE_CONCURRENCY,
        example=",role humans @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_humans(self, ctx, *, role: RoleConvert) -> discord.Message | None:
        """Add a role to all human members."""
        if not await self._ensure_manageable_role(
            ctx, role, action="mass-add", check_dangerous=True
        ):
            return None
        return await do_mass_role(ctx, role, lambda member: not member.bot)

    @role_humans.command(
        name="remove",
        aliases=("revoke", "rm"),
        description="Remove a role from all humans",
        max_concurrency=MASS_ROLE_CONCURRENCY,
        example=",role humans remove @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_humans_remove(
        self, ctx, *, role: RoleConvert
    ) -> discord.Message | None:
        """Remove a role from all human members."""
        if not await self._ensure_manageable_role(ctx, role, action="mass-remove"):
            return None
        return await do_mass_role(
            ctx,
            role,
            lambda member: (not member.bot) and role in member.roles,
            action="remove",
        )

    @role.group(
        name="bots",
        description="Add a role to all bots",
        invoke_without_command=True,
        max_concurrency=MASS_ROLE_CONCURRENCY,
        example=",role bots @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_bots(self, ctx, *, role: RoleConvert) -> discord.Message | None:
        """Add a role to all bots."""
        if not await self._ensure_manageable_role(
            ctx, role, action="mass-add", check_dangerous=True
        ):
            return None
        return await do_mass_role(ctx, role, lambda member: member.bot)

    @role_bots.command(
        name="remove",
        aliases=("revoke", "rm"),
        description="Remove a role from all bots",
        max_concurrency=MASS_ROLE_CONCURRENCY,
        example=",role bots remove @Role",
    )
    @has_permissions(manage_roles=True)
    async def role_bots_remove(
        self, ctx, *, role: RoleConvert
    ) -> discord.Message | None:
        """Remove a role from all bots."""
        if not await self._ensure_manageable_role(ctx, role, action="mass-remove"):
            return None
        return await do_mass_role(
            ctx,
            role,
            lambda member: member.bot and role in member.roles,
            action="remove",
        )

    @role.group(
        name="has",
        aliases=("with", "in"),
        description="Add a role to members with a specific role",
        invoke_without_command=True,
        max_concurrency=MASS_ROLE_CONCURRENCY,
        example=",role has @HasRole @AssignRole",
    )
    @has_permissions(manage_roles=True)
    async def role_has(
        self,
        ctx,
        role: RoleConvert,
        *,
        assign_role: RoleConvert,
    ) -> discord.Message | None:
        """Add a role to all members with another role."""
        if not await self._ensure_manageable_role(
            ctx, assign_role, action="mass-add", check_dangerous=True
        ):
            return None
        return await do_mass_role(
            ctx,
            assign_role,
            lambda member: role in member.roles,
        )

    @role_has.command(
        name="remove",
        aliases=("revoke", "rm"),
        description="Remove a role from members with a specific role",
        max_concurrency=MASS_ROLE_CONCURRENCY,
        example=",role has remove @HasRole @RemoveRole",
    )
    @has_permissions(manage_roles=True)
    async def role_has_remove(
        self,
        ctx,
        role: RoleConvert,
        *,
        assign_role: RoleConvert,
    ) -> discord.Message | None:
        """Remove a role from all members with another role."""
        if not await self._ensure_manageable_role(
            ctx, assign_role, action="mass-remove"
        ):
            return None
        return await do_mass_role(
            ctx,
            assign_role,
            lambda member: role in member.roles and assign_role in member.roles,
            action="remove",
        )
