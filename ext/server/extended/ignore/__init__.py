from typing import Union
from discord.ext.commands import group, CommandError
from discord import Embed, TextChannel, Member
from core.discord.package import Package


from core.managers.converters import CommandConverter
from core.managers.permissions import has_permissions
class IgnoreCommands(Package):
    """ignore channels and members + allow override"""

    @group(
        name="ignore",
        description="ignore a member or channel from bot responses",
        invoke_without_command=True,
    )
    @has_permissions(administrator=True)
    async def ignore(self, ctx):
        """ignore help"""
        return await ctx.send_help(ctx.command)

    @ignore.command(
        name="remove",
        description="remove ignoring for a member or channel",
        example=",ignore remove @jon",
    )
    @has_permissions(administrator=True)
    async def ignore_remove(self, ctx, *, target: Union[Member, TextChannel]):
        """un-ignore something"""
        row = await self.db.fetchrow(
            """SELECT * FROM ignored WHERE guild_id = $1 AND object_id = $2""",
            ctx.guild.id, target.id,
        )
        if not row:
            raise CommandError(f"{target.mention} isnt being ignored")
        await self.db.execute(
            """DELETE FROM ignored WHERE guild_id = $1 AND object_id = $2""",
            ctx.guild.id, target.id,
        )
        return await ctx.success(f"{target.mention} is no longer ignored")

    @ignore.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="view a list of ignored members or channels",
    )
    @has_permissions(administrator=True)
    async def ignore_list(self, ctx):
        """list ignored targets"""
        entries = await self.db.fetch(
            """SELECT object_id FROM ignored WHERE guild_id = $1""", ctx.guild.id
        )
        if not entries:
            raise CommandError("nothing is being ignored")

        def find_obj(oid):
            return ctx.guild.get_member(oid) or ctx.guild.get_channel(oid)

        lines = []
        for rec in entries:
            obj = find_obj(rec.object_id)
            if obj:
                lines.append(f"{obj.mention}")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            Embed(color=self.bot.color, title="Ignore List").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @ignore.command(
        name="add",
        description="ignore a member or channel",
        example=",ignore add @jon",
    )
    @has_permissions(administrator=True)
    async def ignore_add(self, ctx, *, target: Union[Member, TextChannel]):
        """start ignoring something"""
        from core.tools.hierarchy import ensure_member_hierarchy, is_member_like

        if is_member_like(target):
            await ensure_member_hierarchy(ctx, target, bot_hierarchy=False)
        await self.db.execute(
            """INSERT INTO ignored (guild_id, object_id, object_type) VALUES($1, $2, $3) ON CONFLICT(guild_id, object_id) DO NOTHING""",
            ctx.guild.id,
            target.id,
            "channel" if isinstance(target, TextChannel) else "member",
        )
        return await ctx.success(f"now ignoring {target.mention}")

    @group(
        name="allow",
        description="grant or revoke command access for a member",
        example=",allow jonathan ban",
        invoke_without_command=True,
    )
    @has_permissions(server_owner=True)
    async def allow(self, ctx, member: Member, command: CommandConverter):
        """toggle command access"""
        from core.tools.hierarchy import ensure_member_hierarchy

        await ensure_member_hierarchy(ctx, member, bot_hierarchy=False)
        try:
            await self.db.execute(
                """INSERT INTO command_allowed (guild_id, user_id, command) VALUES($1, $2, $3)""",
                ctx.guild.id, member.id, command,
            )
            return await ctx.success(f"**{member}** can now use **{command}**")
        except Exception:
            await self.db.execute(
                """DELETE FROM command_allowed WHERE guild_id = $1 AND user_id = $2 AND command = $3""",
                ctx.guild.id, member.id, command,
            )
            return await ctx.success(f"**{member}** can no longer use **{command}**")

    @allow.command(
        name="list",
        description="see who can bypass command permissions",
        aliases=["ls", "show", "view"],
    )
    @has_permissions(server_owner=True)
    async def allow_list(self, ctx):
        """list allowed overrides"""
        rows = await self.db.fetch(
            "SELECT user_id, command FROM command_allowed WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not rows:
            raise CommandError("nobody has been granted access overrides")
        embed = Embed(title="Allowed Users").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        lines = []
        for i, rec in enumerate(rows, start=1):
            usr = self.bot.get_user(rec.user_id)
            label = str(usr) if usr else "Unknown User"
            lines.append(f"`{i}` **{label}** (`{rec.user_id}`) - {rec.command}")
        return await ctx.paginate(embed, lines)
