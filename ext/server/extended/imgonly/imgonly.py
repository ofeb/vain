from discord.ext.commands import group, has_permissions
from discord import Embed, TextChannel
from core.discord.package import Package


class ImgonlyCommands(Package):
    """image-only channel management"""

    @group(
        name="imageonly",
        aliases=["imgonly", "ionly"],
        description="Set up image + caption only channels",
        invoke_without_command=True,
    )
    async def imageonly(self, ctx):
        """imgonly help"""
        return await ctx.send_help()

    @imageonly.command(
        name="remove",
        aliases=["delete", "del", "d", "rem", "r"],
        description="Remove a gallery channel",
        example=",imageonly remove #img",
    )
    @has_permissions(manage_guild=True)
    async def imageonly_remove(self, ctx, *, channel: TextChannel):
        """un-gallery a channel"""
        await self.db.execute(
            """DELETE FROM image_only WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id, channel.id,
        )
        return await ctx.success(f"removed {channel.mention} from gallery channels")

    @imageonly.command(
        name="add",
        aliases=["a", "set", "create", "s", "c"],
        description="Set a gallery channel",
        example=",imageonly add #img",
    )
    @has_permissions(manage_guild=True)
    async def imageonly_add(self, ctx, *, channel: TextChannel):
        """make a gallery channel"""
        await self.db.execute(
            """INSERT INTO image_only (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT(guild_id, channel_id) DO NOTHING""",
            ctx.guild.id, channel.id,
        )
        return await ctx.success(f"{channel.mention} is now a gallery channel")

    @imageonly.command(
        name="list",
        aliases=["ls", "view", "show"],
        description="View all gallery channels",
    )
    @has_permissions(manage_guild=True)
    async def imageonly_list(self, ctx):
        """show gallery channels"""
        data = await self.db.fetch(
            """SELECT channel_id FROM image_only WHERE guild_id = $1""", ctx.guild.id
        )
        dead = []
        lines = []
        for row in data:
            ch = ctx.guild.get_channel(row.channel_id)
            if not ch:
                dead.append(row.channel_id)
                continue
            lines.append(f"{ch.mention} (`{row.channel_id}`)")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        embed = Embed(title="Image Only Channels").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(embed, numbered)
