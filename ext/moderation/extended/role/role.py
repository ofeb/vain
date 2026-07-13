import discord
from discord.ext.commands import CommandError, group

from core.discord.package import Package


from core.managers.permissions import has_permissions
def _parse_color(value: str | None) -> discord.Color | None:
    if not value:
        return None
    raw = value.strip().lower()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) != 6:
        return None
    try:
        return discord.Color(int(raw, 16))
    except ValueError:
        return None


class Role(Package):
    """role management"""

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
    ) -> bool:
        """Check if a role can be modified. Returns True if OK, False if blocked."""
        if ctx.guild is None:
            await ctx.warn("This command can only be used in a server")
            return False
        if role == ctx.guild.default_role:
            await ctx.warn(f"You cannot {action} the default role")
            return False
        if role.managed:
            await ctx.warn(f"You cannot {action} an integration role")
            return False

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        bot_member = ctx.guild.me or ctx.guild.get_member(self.bot.user.id if self.bot.user else 0)
        if author and ctx.guild.owner_id != author.id and role >= author.top_role:
            await ctx.warn("That role is above or equal to your highest role")
            return False
        if bot_member is None:
            await ctx.warn("I could not resolve my server member")
            return False
        if role >= bot_member.top_role:
            await ctx.warn("That role is above or equal to my highest role")
            return False
        return True

    async def _ensure_targetable_member(self, ctx, member: discord.Member) -> bool:
        """Check if a member's roles can be modified. Returns True if OK, False if blocked."""
        if ctx.guild is None:
            await ctx.warn("This command can only be used in a server")
            return False
        if member.id == ctx.author.id:
            await ctx.warn("You cannot modify your own roles with this command")
            return False
        if member.id == ctx.guild.owner_id:
            await ctx.warn("You cannot modify the server owner's roles")
            return False

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        bot_member = ctx.guild.me or ctx.guild.get_member(self.bot.user.id if self.bot.user else 0)
        if author and ctx.guild.owner_id != author.id and member.top_role >= author.top_role:
            await ctx.warn(
                f"**{member.display_name}** has a higher or equal role than you — "
                f"their top role ({member.top_role.mention}) must be below yours ({author.top_role.mention})"
            )
            return False
        if bot_member is None:
            await ctx.warn("I could not resolve my server member")
            return False
        if member.top_role >= bot_member.top_role:
            await ctx.warn(
                f"**{member.display_name}** has a higher or equal role than me — "
                f"their top role ({member.top_role.mention}) must be below my highest role ({bot_member.top_role.mention})"
            )
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
        target_name: str,
        case_id: int | None,
        reason: str | None,
    ) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        channel_id = await self.db.get_modlog_channel(ctx.guild.id)
        if not channel_id:
            return
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            color=self.color,
            title=f"Case #{case_id}" if case_id is not None else "Moderation action",
            description=(
                f"**Action:** {action}\n"
                f"**Target:** {target_name}\n"
                f"**Moderator:** {ctx.author}\n"
                f"**Reason:** {self._default_reason(reason)}"
            ),
        )
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group(
        name="role",
        description="Modify a member's roles",
        invoke_without_command=True,
    )
    @has_permissions(manage_roles=True)
    async def role(self, ctx, member, role):
        """modify member roles"""
        pass

    @role.command(
        name="has",
        description="Add a role to members with a specific role",
    )
    async def role_has(self, ctx, role, assign_role):
        """add role to members with role"""
        pass

    @role.command(
        name="has remove",
        description="Remove a role from members with a specific role",
    )
    async def role_has_remove(self, ctx, role, remove_role):
        """remove role from members with role"""
        pass

    @role.command(
        name="remove",
        description="Removes role from a member",
    )
    @has_permissions(manage_roles=True)
    async def role_remove(
        self,
        ctx,
        member: discord.Member,
        role: discord.Role,
        *,
        reason: str = None,
    ):
        """remove role from member"""
        if not await self._ensure_targetable_member(ctx, member):
            return
        if not await self._ensure_manageable_role(ctx, role, action="remove"):
            return
        if role not in member.roles:
            return await ctx.warn(f"**{member}** does not have **{role.name}**")

        await member.remove_roles(role, reason=self._audit_reason(ctx, reason))
        case_id = await self._create_case(
            ctx,
            action="role remove",
            target_id=member.id,
            reason=reason,
        )
        await self._send_modlog(
            ctx,
            action="role remove",
            target_name=f"{member} -> {role.name}",
            case_id=case_id,
            reason=reason,
        )
        return await ctx.success(
            f"Removed **{role.name}** from **{member}** - {self._default_reason(reason)}"
        )

    @role.command(
        name="hoist",
        description="Toggle hoisting a role",
    )
    async def role_hoist(self, ctx, role):
        """toggle role hoist"""
        pass

    @role.command(
        name="humans",
        description="Add a role to all humans",
    )
    async def role_humans(self, ctx, role, flags):
        """add role to all humans"""
        pass

    @role.command(
        name="humans remove",
        description="Remove a role from all humans",
    )
    async def role_humans_remove(self, ctx, role):
        """remove role from all humans"""
        pass

    @role.command(
        name="add",
        description="Adds role to a member",
    )
    @has_permissions(manage_roles=True)
    async def role_add(
        self,
        ctx,
        member: discord.Member,
        role: discord.Role,
        *,
        reason: str = None,
    ):
        """add role to member"""
        if not await self._ensure_targetable_member(ctx, member):
            return
        if not await self._ensure_manageable_role(ctx, role, action="give"):
            return
        if role in member.roles:
            return await ctx.warn(f"**{member}** already has **{role.name}**")

        await member.add_roles(role, reason=self._audit_reason(ctx, reason))
        case_id = await self._create_case(
            ctx,
            action="role add",
            target_id=member.id,
            reason=reason,
        )
        await self._send_modlog(
            ctx,
            action="role add",
            target_name=f"{member} -> {role.name}",
            case_id=case_id,
            reason=reason,
        )
        return await ctx.success(
            f"Added **{role.name}** to **{member}** - {self._default_reason(reason)}"
        )

    @role.command(
        name="color",
        description="Set a color for a role",
    )
    async def role_color(self, ctx, colour, role):
        """set role color"""
        pass

    @role.command(
        name="color gradient",
        description="Set a gradient color for a role",
    )
    async def role_color_gradient(self, ctx, colour, second_colour, role):
        """set role gradient color"""
        pass

    @role.command(
        name="delete",
        description="Deletes a role",
    )
    @has_permissions(manage_roles=True)
    async def role_delete(
        self,
        ctx,
        role: discord.Role,
        *,
        reason: str = None,
    ):
        """delete role"""
        if not await self._ensure_manageable_role(ctx, role, action="delete"):
            return

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
            ctx,
            action="role delete",
            target_id=role_id,
            reason=reason,
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
        return await ctx.success(
            f"Deleted role **{role_name}** - {self._default_reason(reason)}"
        )

    @role.command(
        name="mentionable",
        description="Toggle mentioning a role",
    )
    async def role_mentionable(self, ctx, role):
        """toggle role mentionable"""
        pass

    @role.command(
        name="cancel",
        description="Cancels a mass role task running",
    )
    async def role_cancel(self, ctx):
        """cancel mass role task"""
        pass

    @role.command(
        name="restore",
        description="Restore roles to a member",
    )
    async def role_restore(self, ctx, member):
        """restore member roles"""
        pass

    @role.command(
        name="icon",
        description="Set an icon for a role",
    )
    async def role_icon(self, ctx, url, role):
        """set role icon"""
        pass

    @role.command(
        name="topcolor",
        description="Changes your highest roles color",
    )
    async def role_topcolor(self, ctx, colour, member):
        """change highest role color"""
        pass

    @role.command(
        name="bots",
        description="Add a role to all bots",
    )
    async def role_bots(self, ctx, role):
        """add role to all bots"""
        pass

    @role.command(
        name="bots remove",
        description="Remove a role from all bots",
    )
    async def role_bots_remove(self, ctx, role):
        """remove role from all bots"""
        pass

    @role.command(
        name="edit",
        description="Change a role name",
    )
    async def role_edit(self, ctx, role, *, name):
        """edit role name"""
        pass

    @role.command(
        name="create",
        description="Creates a role with optional color",
    )
    @has_permissions(manage_roles=True)
    async def role_create(
        self,
        ctx,
        first: str,
        *,
        rest: str = None,
    ):
        """create role"""
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")
        color = _parse_color(first)
        if color is not None:
            if not rest:
                raise CommandError("provide a role name after the color")
            role_name = rest.strip()
        else:
            role_name = first if rest is None else f"{first} {rest}".strip()
            color = discord.Color.default()

        if not role_name:
            raise CommandError("provide a role name")

        role = await ctx.guild.create_role(
            name=role_name,
            color=color,
            reason=self._audit_reason(ctx, reason=None),
        )
        case_id = await self._create_case(
            ctx,
            action="role create",
            target_id=role.id,
            reason=None,
        )
        await self._send_modlog(
            ctx,
            action="role create",
            target_name=role.name,
            case_id=case_id,
            reason=None,
        )
        return await ctx.success(f"Created role **{role.name}**")
