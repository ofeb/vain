from typing import Optional, Union, List
from discord.ext.commands import group, has_permissions, CommandError, ColourConverter as ColorConverter
from discord import Embed, Role, Emoji, PartialEmoji, Color, Member
from core.discord.package import Package
from lib.classes.color import get_dominant_color
from lib.classes.checks import is_booster
import aiohttp
import asyncio
import random


class BoosterroleCommands(Package):
    """booster role management commands"""

    @group(
        name="boosterrole",
        aliases=["boostrole", "br"],
        description="manage your personal booster color role",
        example=",boosterrole ff0000 sexy",
        extras={"checks": "Boosters Only"},
        invoke_without_command=True,
    )
    async def boosterrole(self, ctx):
        """redirect to create"""
        msg = ctx.message
        msg.content = msg.content.replace("boosterrole", "boosterrole create")
        ctx = await self.bot.get_context(msg)
        await ctx.reinvoke(restart=True, call_hooks=True)

    @boosterrole.command(
        name="create",
        description="get your own custom booster color role",
        example=",boosterrole create #f47373 sup",
    )
    @is_booster()
    async def boosterrole_create(
        self,
        ctx,
        color: Optional[ColorConverter] = None,
        *,
        name: Optional[str] = None,
    ):
        """create booster role"""
        if not color and not name:
            return await ctx.send_help(ctx.command)
        extras = {}
        if name:
            if len(name) > 32:
                raise CommandError("role name cant exceed **32** characters")
            if len(name) < 2:
                raise CommandError("role name needs at least **2** characters")
            extras["name"] = name
        cfg = await self.db.fetchrow(
            """SELECT base_id, role_limit FROM booster_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        pos = None
        if cfg:
            base = ctx.guild.get_role(cfg.base_id)
            pos = base.position - 1 if base and base.position > 1 else None
            if cfg.role_limit:
                count = await self.db.fetchval(
                    """SELECT COUNT(*) FROM custom_roles WHERE guild_id = $1""",
                    ctx.guild.id,
                )
                if count >= cfg.role_limit:
                    raise CommandError(f"hit the max limit of {cfg.role_limit} roles")
        existing_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        role = ctx.guild.get_role(existing_id)
        if not role:
            if not name:
                name = ctx.author.name
            role = await ctx.guild.create_role(
                name=name, color=color, reason="booster role"
            )
            if pos:
                await role.edit(position=pos)
            await self.db.execute(
                """INSERT INTO custom_roles (guild_id, user_id, role_id) VALUES($1, $2, $3) ON CONFLICT(guild_id, user_id) DO UPDATE SET role_id = excluded.role_id""",
                ctx.guild.id,
                ctx.author.id,
                role.id,
            )
            return await ctx.success(f"made and gave you {role.mention}")
        else:
            await role.edit(color=color, **extras, reason="booster role")
            return await ctx.success(f"updated your color to `{color}`")

    @boosterrole.group(
        name="award",
        aliases=["reward"],
        description="Reward a member a specific role upon boost",
        example=",boosterrole award @rich",
        invoke_without_command=True,
    )
    @has_permissions(manage_roles=True, manage_guild=True)
    async def boosterrole_award(self, ctx, *, role: Role):
        """set booster award role"""
        await self.db.execute(
            """INSERT INTO booster_roles (guild_id, award_id) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET award_id = excluded.award_id""",
            ctx.guild.id,
            role.id,
        )
        for member in ctx.guild.premium_subscribers:
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                except Exception:
                    pass
        return await ctx.success(f"giving all boosters {role.mention}")

    @boosterrole_award.command(name="view", description="View the current award role")
    @has_permissions(manage_roles=True, manage_guild=True)
    async def boosterrole_award_view(self, ctx):
        """show boost award role"""
        role_id = await self.db.fetchval(
            """SELECT award_id FROM booster_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not role_id:
            raise CommandError("no booster award role set")
        role = ctx.guild.get_role(role_id)
        return await ctx.send(
            embed=Embed(
                title="Boost Award Role",
                description=f"**Role:** {role.mention}\n**Members:** {len(role.members)}",
            ).set_author(
                name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
            )
        )

    @boosterrole_award.command(
        name="unset",
        description="Remove the reward role",
        aliases=["reset", "clear", "delete", "remove", "del", "d", "r", "c", "cl"],
    )
    @has_permissions(manage_roles=True, manage_guild=True)
    async def boosterrole_award_unset(self, ctx):
        """clear boost award role"""
        try:
            await self.db.execute(
                """UPDATE booster_roles SET award_id = $1 WHERE guild_id = $2""",
                None,
                ctx.guild.id,
            )
        except Exception:
            raise CommandError("no booster award role is set")
        return await ctx.success("booster award role removed")

    @boosterrole.command(
        name="base",
        description="Set the base role for where boost roles will go under",
        example=",boosterrole base @brs",
    )
    @has_permissions(manage_guild=True)
    async def boosterrole_base(self, ctx, *, role: Role):
        """set booster role position"""
        if not role.is_assignable():
            raise CommandError(f"cant edit {role.mention}")
        await self.db.execute(
            """INSERT INTO booster_roles (guild_id, base_id) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET base_id = excluded.base_id""",
            ctx.guild.id,
            role.id,
        )
        dead_ids = []
        role_ids = [
            r.role_id
            for r in await self.db.fetch(
                """SELECT role_id FROM custom_roles WHERE guild_id = $1""", ctx.guild.id
            )
        ]
        for rid in role_ids:
            br = ctx.guild.get_role(rid)
            if br:
                await br.edit(
                    position=role.position - 1 if role.position > 1 else 1,
                    reason=f"base role changed by {ctx.author}",
                )
            else:
                dead_ids.append(rid)
        await self.db.execute(
            """DELETE FROM custom_roles WHERE guild_id = $1 AND role_id = ANY($2::BIGINT[])""",
            ctx.guild.id,
            dead_ids,
        )
        return await ctx.success(f"base role set to {role.mention}")

    @boosterrole.command(
        name="limit",
        description="Set limit for booster roles",
        example=",boosterrole limit 30",
    )
    @has_permissions(manage_guild=True)
    async def boosterrole_limit(self, ctx, limit: int):
        """set booster role cap"""
        if limit < 1:
            limit = None
        await self.db.execute(
            """INSERT INTO booster_roles (guild_id, limit) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET limit = excluded.limit""",
            ctx.guild.id,
            limit,
        )
        msg = f"booster role cap set to {limit}" if limit else "booster role cap removed"
        return await ctx.success(msg)

    async def _purge_roles(self, ctx, records):
        """delete stale booster roles"""
        for rec in records:
            if r := ctx.guild.get_role(rec.role_id):
                try:
                    await r.delete(reason="booster role cleanup")
                except Exception:
                    pass
        await self.db.execute(
            """DELETE FROM custom_roles WHERE guild_id = $1 AND role_id = ANY($2::BIGINT[])""",
            ctx.guild.id,
            [r.role_id for r in records],
        )
        return True

    @boosterrole.command(name="list", description="View all booster roles")
    @has_permissions(manage_guild=True)
    async def boosterrole_list(self, ctx):
        """show all boost roles"""
        all_roles = await self.db.fetch(
            """SELECT user_id, role_id FROM custom_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not all_roles:
            raise CommandError("no booster roles found")
        stale = [
            r for r in all_roles
            if not ctx.guild.get_member(r.user_id) or not ctx.guild.get_role(r.role_id)
        ]
        valid = [r for r in all_roles if ctx.guild.get_member(r.user_id)]
        lines = [
            f"`{i}` {ctx.guild.get_member(r.user_id).mention} — {ctx.guild.get_role(r.role_id).mention}"
            for i, r in enumerate(valid, start=1)
        ]
        if stale:
            asyncio.ensure_future(self._purge_roles(ctx, stale))
        return await ctx.paginate(
            Embed(title="Booster Roles").set_author(
                name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
            ),
            lines,
        )

    @boosterrole.command(
        name="dominant",
        description="Set booster roles color to the most dominant color in avatar",
    )
    @is_booster()
    async def boosterrole_dominant(self, ctx):
        """auto color from avatar"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError("set up a booster role first with `boosterrole`")
        col = Color.from_str(await get_dominant_color(ctx.author) or "#303135")
        role = ctx.guild.get_role(role_id)
        if role:
            await role.edit(color=col, reason=f"dominant color set by {ctx.author}")
            return await ctx.success(f"color updated to `{col}`")
        raise CommandError("your booster role was deleted, use `boosterrole remove` and start fresh")

    @boosterrole.command(
        name="color",
        description="Get your own custom booster color role",
        example=",boosterrole color #ff0000",
    )
    @is_booster()
    async def boosterrole_color(
        self, ctx, color: ColorConverter, *, name: Optional[str] = None
    ):
        """change booster role color"""
        extras = {}
        if name:
            if len(name) > 32:
                raise CommandError("role name cant exceed **32** characters")
            if len(name) < 2:
                raise CommandError("role name needs at least **2** characters")
            extras["name"] = name
        data = await self.db.fetchrow(
            """SELECT base_id, limit FROM booster_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        pos = ctx.guild.get_role(data.base_id).position - 1 if data else None
        if data and data.role_limit:
            count = await self.db.fetchval(
                """SELECT COUNT(*) FROM custom_roles WHERE guild_id = $1""",
                ctx.guild.id,
            )
            if count >= data.role_limit:
                raise CommandError(f"hit the max of {data.role_limit} roles")
        existing_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        role = ctx.guild.get_role(existing_id)
        if not role:
            if not name:
                name = ctx.author.name
            role = await ctx.guild.create_role(
                name=name, color=color, position=pos, reason="booster role"
            )
            await self.db.execute(
                """INSERT INTO custom_roles (guild_id, user_id, role_id) VALUES($1, $2, $3) ON CONFLICT(guild_id, user_id) DO UPDATE SET role_id = excluded.role_id""",
                ctx.guild.id,
                ctx.author.id,
                role.id,
            )
            return await ctx.success(f"made and gave you {role.mention}")
        await role.edit(color=color, **extras, reason="booster role")
        return await ctx.success(f"color set to `{color}`")

    @boosterrole.command(
        name="remove",
        description="Remove custom color booster role",
    )
    @is_booster()
    async def boosterrole_remove(self, ctx):
        """delete your booster role"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError("you dont have a booster role set up")
        role = ctx.guild.get_role(role_id)
        if role:
            await role.delete(reason=f"booster role removed by {ctx.author}")
        await self.db.execute(
            """DELETE FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        return await ctx.success("booster role removed")

    @boosterrole.command(name="cleanup", description="Clean up unused booster roles")
    @has_permissions(manage_roles=True, manage_guild=True)
    async def boosterrole_cleanup(self, ctx):
        """clean stale booster roles"""
        entries = await self.db.fetch(
            """SELECT role_id, user_id FROM custom_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not entries:
            raise CommandError("no booster roles to clean up")
        removed_ids = []
        for entry in entries:
            role = ctx.guild.get_role(entry.role_id)
            if role:
                if not ctx.guild.get_member(entry.user_id):
                    await role.delete(reason=f"cleanup by {ctx.author}")
                    removed_ids.append(entry.role_id)
            else:
                removed_ids.append(entry.role_id)
        await self.db.execute(
            """DELETE FROM custom_roles WHERE role_id = ANY($1::BIGINT[])""",
            removed_ids,
        )
        return await ctx.success(f"cleaned up `{len(removed_ids)}` booster roles")

    @boosterrole.command(
        name="random",
        description="Set a booster role with a random hex code",
    )
    @is_booster()
    async def boosterrole_random(self, ctx):
        """randomize booster role color"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError("set up a booster role first with `boosterrole`")
        rand = random.randint(0, 0xFFFFFF)
        col = Color.from_str(f"#{rand:06X}")
        role = ctx.guild.get_role(role_id)
        if role:
            await role.edit(color=col, reason=f"random color by {ctx.author}")
            return await ctx.success(f"color randomized to `{col}`")
        raise CommandError("your booster role got deleted, use `boosterrole remove` and start fresh")

    @boosterrole.command(
        name="icon",
        description="Set an icon for booster role",
        example=",boosterrole icon https://example.com/img.png",
    )
    @is_booster()
    async def boosterrole_icon(
        self,
        ctx,
        *,
        icon: Optional[Union[Emoji, PartialEmoji, str]] = None,
    ):
        """set booster role icon"""
        if "role_icons" not in [f.lower() for f in ctx.guild.features]:
            raise CommandError("server doesnt have the **Role Icons** feature")

        async def fetch_icon(src):
            if src is None:
                return None
            if isinstance(src, (Emoji, PartialEmoji)):
                return await src.read()
            async with aiohttp.ClientSession() as s:
                async with s.get(src) as resp:
                    return await resp.read()

        if isinstance(icon, str) and not icon.startswith("https://"):
            return await ctx.fail("that url doesnt look valid")
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError("set up your booster role first with `boosterrole`")
        role = ctx.guild.get_role(role_id)
        if not role:
            raise CommandError("your booster role got deleted, use `boosterrole remove` and start fresh")
        await role.edit(
            display_icon=await fetch_icon(icon) if icon else None,
            reason=f"icon changed by {ctx.author}",
        )
        return await ctx.success(
            "booster role icon set" if icon else "booster role icon cleared"
        )

    @boosterrole.command(
        name="rename",
        description="Edit your booster roles name",
        example=",boosterrole rename richgang",
    )
    @is_booster()
    async def boosterrole_rename(self, ctx, *, name: str):
        """rename booster role"""
        if len(name) > 32:
            raise CommandError("name cant exceed **32** characters")
        if len(name) < 2:
            raise CommandError("name needs at least **2** characters")
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError("set up your booster role first with `boosterrole`")
        role = ctx.guild.get_role(role_id)
        if role:
            await role.edit(name=name, reason=f"renamed by {ctx.author}")
            return await ctx.success("booster role renamed")
        raise CommandError("your booster role got deleted, use `boosterrole remove` and start fresh")
