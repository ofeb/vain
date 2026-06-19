from __future__ import annotations

from discord.ext.commands import group

from core.discord.package import Package


from core.managers.permissions import has_permissions
class ReposterCommands(Package):
    """repost media from channels"""

    @group(
        name="reposter",
        aliases=["rp"],
        description="auto repost media to a channel",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def reposter(self, ctx):
        """show reposter help"""
        await ctx.send_help(ctx.command)

    @reposter.command(
        name="add",
        aliases=["a"],
        description="add a channel to repost media from",
        example=",reposter add #media",
    )
    @has_permissions(manage_guild=True)
    async def reposter_add(self, ctx, channel, destination=None):
        """add reposter channel pair"""
        dest = destination or channel
        await self.db.execute(
            """INSERT INTO reposter (guild_id, source_id, dest_id) VALUES($1, $2, $3)
               ON CONFLICT (guild_id, source_id) DO UPDATE SET dest_id = excluded.dest_id""",
            ctx.guild.id, channel.id, dest.id,
        )
        await ctx.success(f"media from {channel.mention} will repost to {dest.mention}")

    @reposter.command(
        name="remove",
        aliases=["rm", "del"],
        description="remove a reposter channel",
        example=",reposter remove #media",
    )
    @has_permissions(manage_guild=True)
    async def reposter_remove(self, ctx, channel):
        """remove reposter entry"""
        deleted = await self.db.fetchval(
            """DELETE FROM reposter WHERE guild_id = $1 AND source_id = $2 RETURNING source_id""",
            ctx.guild.id, channel.id,
        )
        if not deleted:
            from discord.ext.commands import CommandError
            raise CommandError(f"{channel.mention} is not a reposter source")
        await ctx.success(f"removed reposter for {channel.mention}")

    @reposter.command(
        name="list",
        aliases=["ls", "show"],
        description="list active reposters",
    )
    async def reposter_list(self, ctx):
        """show all reposters"""
        rows = await self.db.fetch(
            """SELECT source_id, dest_id FROM reposter WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not rows:
            from discord.ext.commands import CommandError
            raise CommandError("no reposters configured")
        lines = [
            f"<#{r['source_id']}> → <#{r['dest_id']}>" for r in rows
        ]
        from discord import Embed
        e = Embed(title="Active Reposters", description="\n".join(lines), color=self.color)
        await ctx.send(embed=e)
