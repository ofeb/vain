from typing import Optional
from discord.ext.commands import group, CommandError
from discord import Embed, Role
from core.discord.package import Package


from core.managers.converters import FakePermissionConverter
from core.managers.permissions import has_permissions
class SetCommands(Package):
    """fake permissions management"""

    @group(
        name="fakepermissions",
        aliases=["fp", "fakeperms", "fakeperm"],
        description="grant fake permissions to roles",
        invoke_without_command=True,
    )
    async def fakepermissions(self, ctx):
        """fake perms help"""
        return await ctx.send_help()

    @fakepermissions.command(
        name="remove",
        aliases=["rem", "delete", "del", "r", "d"],
        description="remove fake perms from a role",
        example=",fakepermissions remove @everyone manage_messages",
    )
    @has_permissions(server_owner=True)
    async def fakepermissions_remove(
        self, ctx, role: Role, *, permissions: FakePermissionConverter
    ):
        """drop fake perms"""
        stored = await self.db.fetchval(
            """SELECT permissions FROM fake_permissions WHERE guild_id = $1 AND role_id = $2""",
            ctx.guild.id, role.id,
        )
        if not stored:
            raise CommandError(f"{role.mention} has no fake permissions")
        removed = []
        for perm in permissions:
            try:
                stored.remove(str(perm))
                removed.append(perm)
            except ValueError:
                continue
        await self.db.execute(
            """UPDATE fake_permissions SET permissions = $1 WHERE guild_id = $2 AND role_id = $3""",
            stored, ctx.guild.id, role.id,
        )
        return await ctx.success(
            f"removed from {role.mention}: {', '.join(f'`{p}`' for p in removed)}"
        )

    @fakepermissions.command(
        name="add",
        aliases=["create", "c", "a", "set", "grant", "g"],
        description="give a role fake permissions",
        example=",fakepermissions add @everyone manage_messages",
    )
    @has_permissions(server_owner=True)
    async def fakepermissions_add(
        self, ctx, role: Role, *, permissions: FakePermissionConverter
    ):
        """grant fake perms"""
        await self.db.execute(
            """INSERT INTO fake_permissions (guild_id, role_id, permissions) VALUES($1, $2, $3) ON CONFLICT(guild_id, role_id) DO UPDATE SET permissions = ARRAY(SELECT DISTINCT unnest(fake_permissions.permissions || EXCLUDED.permissions));""",
            ctx.guild.id, role.id, permissions,
        )
        return await ctx.success(
            f"gave {role.mention}: {', '.join(f'`{p}`' for p in permissions)}"
        )

    @fakepermissions.command(
        name="reset",
        description="clear all fake permissions. this cannot be undone",
    )
    @has_permissions(server_owner=True)
    async def fakepermissions_reset(self, ctx):
        """wipe fake perms"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Clear **all** fake permissions? This action **cannot be undone**."
        )
        if not ok:
            return await ctx.warn("Fake permissions reset **cancelled**")
        await self.db.execute(
            """DELETE FROM fake_permissions WHERE guild_id = $1""", ctx.guild.id
        )
        return await ctx.success(
            "Fake permissions cleared. This action cannot be undone."
        )

    @fakepermissions.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="list all fake permissions",
        example=",fakepermissions list Moderator",
    )
    @has_permissions(server_owner=True)
    async def fakepermissions_list(self, ctx, *, role: Optional[Role] = None):
        """show fake perms"""
        if role:
            perms = await self.db.fetchval(
                """SELECT permissions FROM fake_permissions WHERE guild_id = $1 AND role_id = $2""",
                ctx.guild.id, role.id,
            )
            if not perms:
                raise CommandError(f"{role.mention} has no fake permissions")
            lines = [f"`{i}` {p}" for i, p in enumerate(perms, start=1)]
            embed = Embed(color=self.bot.color, title=f"Fake Perms — {role.name}")
            embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
            return await ctx.paginate(embed, lines)
        else:
            data = await self.db.fetch(
                """SELECT role_id, permissions FROM fake_permissions WHERE guild_id = $1""",
                ctx.guild.id,
            )
            if not data:
                raise CommandError("no fake permissions configured")
            embed = Embed(color=self.bot.color, title="Fake Permissions")
            embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
            lines = []
            idx = 0
            for row in data:
                r = ctx.guild.get_role(row.role_id)
                if not r:
                    continue
                idx += 1
                lines.append(
                    f"`{idx}` {r.mention} — {', '.join(f'**{p}**' for p in row.permissions)}"
                )
            return await ctx.paginate(embed, lines)
