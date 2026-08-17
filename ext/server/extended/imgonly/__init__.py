from typing import Optional

from discord.ext.commands import group
from discord import Embed, TextChannel
from core.discord.package import Package
from core.discord.hybrid import hybrid, describe

from core.managers.permissions import has_permissions
class ImgonlyCommands(Package):
    """image-only channel management"""

    async def cog_load(self) -> None:
        await self.db.execute(
            """CREATE TABLE IF NOT EXISTS image_only (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, channel_id)
            )"""
        )

    @hybrid(
        name="imgonly",
        aliases=["gallery", "imageonly"],
        description="Set up image + caption only channels",
        group=True,
    )
    async def imgonly(self, ctx):
        """imgonly help"""
        return await ctx.send_help()

    @imgonly.command(
        name="remove",
        aliases=["delete", "del"],
        description="Remove a gallery channel (defaults to current channel)",
        example=",imageonly remove #img",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def imgonly_remove(self, ctx, channel: Optional[TextChannel] = None):
        """un-gallery a channel"""
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        await self.db.execute(
            """DELETE FROM image_only WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id, channel.id,
        )
        return await ctx.success(f"removed {channel.mention} from gallery channels")

    @imgonly.command(
        name="add",
        aliases=["create"],
        description="Set a gallery channel (defaults to current channel)",
        example=",imageonly add #img",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def imgonly_add(self, ctx, channel: Optional[TextChannel] = None):
        """make a gallery channel"""
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        await self.db.execute(
            """INSERT INTO image_only (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT(guild_id, channel_id) DO NOTHING""",
            ctx.guild.id, channel.id,
        )
        return await ctx.success(f"{channel.mention} is now a gallery channel")

    @imgonly.command(
        name="list",
        description="View all gallery channels",
    )
    @has_permissions(manage_guild=True)
    async def imgonly_list(self, ctx):
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
