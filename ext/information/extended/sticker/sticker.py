from __future__ import annotations

from discord.ext.commands import group
from discord import Embed
import aiohttp

from core.discord.package import Package


from core.managers.permissions import has_permissions
class Sticker(Package):
    """sticker management"""

    @group(
        name="sticker",
        description="Modfy or add stickers to your server!",
        invoke_without_command=True,
    )
    async def sticker(self, ctx):
        """sticker group help"""
        return await ctx.send_help(ctx.command)

    @sticker.command(
        name="tag",
        description="Add server vanity to stickers",
    )
    @has_permissions(manage_expressions=True, manage_guild=True)
    async def sticker_tag(self, ctx):
        """add server vanity to stickers"""
        await ctx.send("This feature would add server vanity to stickers")

    @sticker.command(
        name="remove",
        description="Removes sticker from server",
    )
    @has_permissions(manage_expressions=True)
    async def sticker_remove(self, ctx, name: str):
        """remove sticker from server"""
        sticker = None
        for s in ctx.guild.stickers:
            if s.name.lower() == name.lower():
                sticker = s
                break
        
        if not sticker:
            return await ctx.send("Sticker not found")
        
        await sticker.delete()
        await ctx.success(f"Removed sticker `{name}`")

    @sticker.command(
        name="cleanup",
        description="Cleans server sticker names",
    )
    @has_permissions(manage_expressions=True, manage_guild=True)
    async def sticker_cleanup(self, ctx):
        """clean up sticker names"""
        count = 0
        for sticker in ctx.guild.stickers:
            new_name = ''.join(c for c in sticker.name if c.isalnum() or c in ['_', '-'])
            if new_name != sticker.name:
                try:
                    await sticker.edit(name=new_name)
                    count += 1
                except:
                    pass
        
        await ctx.success(f"Cleaned up {count} sticker names")

    @sticker.command(
        name="rename",
        description="Rename the attached sticker to given new name",
    )
    @has_permissions(manage_expressions=True)
    async def sticker_rename(self, ctx, *, new_name: str):
        """rename sticker"""
        if not ctx.message.stickers:
            return await ctx.send("Please attach a sticker to rename")
        
        sticker = ctx.message.stickers[0]
        try:
            await sticker.edit(name=new_name)
            await ctx.success(f"Renamed sticker to `{new_name}`")
        except Exception as e:
            await ctx.send(f"Failed to rename sticker: {str(e)}")

    @sticker.command(
        name="add",
        description="Downloads sticker and adds to server",
    )
    async def sticker_add(self, ctx, url: str, name: str):
        """add sticker from URL"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return await ctx.send("Failed to download sticker")
                data = await resp.read()
        
        try:
            sticker = await ctx.guild.create_sticker(
                name=name,
                description=f"Added by {ctx.author}",
                file=data,
                emoji="🎨"
            )
            await ctx.success(f"Added sticker `{name}`")
        except Exception as e:
            await ctx.send(f"Failed to add sticker: {str(e)}")
