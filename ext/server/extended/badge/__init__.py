from discord.ext.commands import group, CommandError, ColourConverter as ColorConverter
from discord import Embed, Role, Color
from core.discord.package import Package
import humanize
from discord.utils import utcnow


from core.managers.permissions import has_permissions
class BadgeCommands(Package):
    """colorme custom color role commands"""

    @group(
        name="colorme",
        description="give yourself a custom color role",
        invoke_without_command=True,
        aliases=["cr"],
        example=",colorme purple",
    )
    async def colorme(self, ctx, *, color: ColorConverter):
        """set your color"""
        cfg = await self.db.fetchrow(
            """SELECT * FROM config WHERE guild_id = $1""", ctx.guild.id
        )
        if not cfg or not cfg.colorme:
            raise CommandError("colorme isnt enabled here")
        all_roles = (
            await self.db.fetchval(
                """SELECT roles FROM color_roles WHERE guild_id = $1""", ctx.guild.id
            ) or []
        )
        pairs = [i.split("-", 1) for i in all_roles]
        pair_ids = [int(p[1]) for p in pairs]
        member_role_ids = [r.id for r in ctx.author.roles]
        member_roles = list(ctx.author.roles)

        if any(rid in pair_ids for rid in member_role_ids):
            current_rid = next(rid for rid in pair_ids if rid in member_role_ids)
            current_role = ctx.guild.get_role(current_rid)
            if current_role:
                if len(current_role.members) == 1:
                    entry = next(p for p in pairs if p[1] == str(current_rid))
                    pairs.remove(entry)
                    await current_role.delete(reason="colorme cleanup")
                if current_role in member_roles:
                    member_roles.remove(current_role)

        match = next((p for p in pairs if p[0] == str(color.value)), None)
        if match:
            new_role = ctx.guild.get_role(int(match[1]))
            if not new_role:
                pairs.remove(match)
                new_role = await ctx.guild.create_role(
                    name=str(color.value), color=color, reason="colorme"
                )
                if cfg.colorme_base and (base := ctx.guild.get_role(cfg.colorme_base)):
                    await new_role.edit(position=base.position, reason="colorme base")
                pairs.append([str(color.value), str(new_role.id)])
        else:
            new_role = await ctx.guild.create_role(
                name=str(color.value), color=color, reason="colorme"
            )
            if cfg.colorme_base and (base := ctx.guild.get_role(cfg.colorme_base)):
                await new_role.edit(position=base.position, reason="colorme base")
            pairs.append([str(color.value), str(new_role.id)])

        member_roles.append(new_role)
        await ctx.author.edit(roles=member_roles, reason="colorme")
        await self.db.execute(
            """UPDATE color_roles SET roles = $1 WHERE guild_id = $2""",
            [f"{p[0]}-{p[1]}" for p in pairs],
            ctx.guild.id,
        )
        return await ctx.success(f"Color set\n> -# **{color.value}**")

    @colorme.command(
        name="enable",
        aliases=["on"],
        description="allow users to use colorme",
    )
    @has_permissions(manage_guild=True)
    async def colorme_enable(self, ctx):
        """turn on colorme"""
        await self.db.execute(
            """INSERT INTO config (guild_id, colorme) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET colorme = excluded.colorme""",
            ctx.guild.id, True,
        )
        return await ctx.success("Colorme enabled")

    @colorme.command(
        name="setup",
        description="create basic rainbow color roles and a hoisted separator",
    )
    @has_permissions(manage_guild=True)
    async def colorme_setup(self, ctx):
        """create rainbow color roles"""
        cfg = await self.db.fetchrow(
            """SELECT * FROM config WHERE guild_id = $1""", ctx.guild.id
        )
        if not cfg or not cfg.colorme:
            raise CommandError("colorme isnt enabled here")

        colors = [
            ("Red", Color.red()),
            ("Orange", Color.orange()),
            ("Yellow", Color.yellow()),
            ("Green", Color.green()),
            ("Blue", Color.blue()),
            ("Indigo", Color.from_rgb(75, 0, 130)),
            ("Violet", Color.from_rgb(138, 43, 226)),
            ("Pink", Color.from_rgb(255, 105, 180)),
            ("Teal", Color.teal()),
            ("Gold", Color.gold()),
        ]

        existing = (
            await self.db.fetchval(
                """SELECT roles FROM color_roles WHERE guild_id = $1""", ctx.guild.id
            ) or []
        )
        pairs = [i.split("-", 1) for i in existing]

        msg = await ctx.normal(f"creating **{len(colors)}** color roles...")

        separator = await ctx.guild.create_role(
            name="Color Roles",
            color=Color.default(),
            hoist=True,
            reason="colorme setup",
        )

        created = 0
        for name, color_val in colors:
            if any(p[0] == str(color_val.value) for p in pairs):
                continue
            role = await ctx.guild.create_role(
                name=name, color=color_val, reason="colorme setup"
            )
            if cfg.colorme_base and (base := ctx.guild.get_role(cfg.colorme_base)):
                await role.edit(position=base.position, reason="colorme base")
            else:
                await role.edit(position=separator.position, reason="colorme setup")
            pairs.append([str(color_val.value), str(role.id)])
            created += 1

        await self.db.execute(
            """INSERT INTO color_roles (guild_id, roles) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET roles = excluded.roles""",
            ctx.guild.id,
            [f"{p[0]}-{p[1]}" for p in pairs],
        )
        elapsed = humanize.precisedelta(utcnow() - msg.created_at, format="%0.0f")
        return await msg.edit(
            embed=Embed(
                color=self.bot.color,
                description=f"{ctx.author.mention}: created **{created}** color roles in **{elapsed}**",
            )
        )

    @colorme.command(
        name="disable",
        aliases=["off"],
        description="prevent users from using colorme without deleting color roles",
    )
    @has_permissions(manage_guild=True)
    async def colorme_disable(self, ctx):
        """turn off colorme without deleting color roles"""
        await self.db.execute(
            """INSERT INTO config (guild_id, colorme) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET colorme = excluded.colorme""",
            ctx.guild.id, False,
        )
        return await ctx.success(
            f"Colorme disabled\n> -# **color roles kept**"
        )

    @colorme.command(
        name="reset",
        aliases=["remove", "clear", "delete"],
        description="delete colorme color roles and turn it off. this cannot be undone",
    )
    @has_permissions(manage_guild=True)
    async def colorme_reset(self, ctx):
        """delete colorme color roles and turn it off"""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Reset **all** colorme settings and delete color roles? "
            "This action **cannot be undone**."
        )
        if not ok:
            return await ctx.warn("Cancelled\n> -# **colorme reset was cancelled**")

        await self.db.execute(
            """INSERT INTO config (guild_id, colorme) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET colorme = excluded.colorme""",
            ctx.guild.id, False,
        )
        stored = (
            await self.db.fetchval(
                """SELECT roles FROM color_roles WHERE guild_id = $1""", ctx.guild.id
            ) or []
        )
        for val in stored:
            rid = int(val.split("-", 1)[1])
            role = ctx.guild.get_role(rid)
            if role:
                await role.delete(reason="colorme reset cleanup")
        await self.db.execute(
            """DELETE FROM color_roles WHERE guild_id = $1""", ctx.guild.id
        )
        return await ctx.success(
            "Colorme reset\n> -# **all color roles deleted**"
        )

    @colorme.command(name="cleanup", description="remove unused color roles")
    @has_permissions(manage_guild=True)
    async def colorme_cleanup(self, ctx):
        """clean stale color roles"""
        stored = await self.db.fetchval(
            """SELECT roles FROM color_roles WHERE guild_id = $1""", ctx.guild.id
        )
        if not stored:
            raise CommandError("no color roles exist")
        to_save = []
        to_delete = []
        for val in stored:
            rid = int(val.split("-", 1)[1])
            role = ctx.guild.get_role(rid)
            if not role:
                to_delete.append(rid)
                continue
            if len(role.members) > 0:
                to_save.append(val)
            else:
                to_delete.append(role)

        msg = await ctx.normal(
            f"cleaning **{len(to_delete)}** unused color roles..."
        )
        for item in to_delete:
            if isinstance(item, int):
                continue
            await item.delete(reason="colorme cleanup")
        await self.db.execute(
            """UPDATE color_roles SET roles = $1 WHERE guild_id = $2""",
            to_save, ctx.guild.id,
        )
        elapsed = humanize.precisedelta(utcnow() - msg.created_at, format="%0.0f")
        return await msg.edit(
            embed=Embed(
                color=self.bot.color,
                description=f"{ctx.author.mention}: done in **{elapsed}**",
            )
        )

    @colorme.command(
        name="baserole",
        aliases=["base", "br"],
        description="set base role for color roles to sit below",
    )
    @has_permissions(manage_guild=True)
    async def colorme_baserole(self, ctx, *, role: Role):
        """set color role base"""
        stored = (
            await self.db.fetchval(
                """SELECT roles FROM color_roles WHERE guild_id = $1""", ctx.guild.id
            ) or []
        )
        await self.db.execute(
            """INSERT INTO config (guild_id, colorme_base) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET colorme_base = excluded.colorme_base""",
            ctx.guild.id, role.id,
        )
        if not stored:
            return await ctx.success(f"base role set to {role.mention}")
        msg = await ctx.normal(
            f"repositioning **{len(stored)}** color roles..."
        )
        for val in stored:
            rid = int(val.split("-", 1)[1])
            cr = ctx.guild.get_role(rid)
            if not cr:
                continue
            await cr.edit(position=role.position, reason="colorme base update")
        elapsed = humanize.precisedelta(utcnow() - msg.created_at, format="%0.0f")
        return await msg.edit(
            embed=Embed(
                color=self.bot.color,
                description=f"{ctx.author.mention}: done in **{elapsed}**",
            )
        )
