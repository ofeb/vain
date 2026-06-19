from __future__ import annotations

from discord.ext.commands import group
from discord import Embed
import aiohttp

from core.discord.package import Package
from core.managers.permissions import has_permissions
class Emoji(Package):
    """emoji management"""

    @group(
        name="emoji",
        description="Returns a large emoji or server emote",
        invoke_without_command=True,
    )
    async def emoji(self, ctx, emoji: str):
        """get large emoji"""
        import discord
        
        try:
            custom_emoji = await discord.PartialEmoji.from_str(emoji)
            if custom_emoji.is_custom_emoji():
                e = Embed(color=self.color)
                e.set_image(url=custom_emoji.url)
                await ctx.send(embed=e)
            else:
                await ctx.send(emoji)
        except:
            await ctx.send(emoji)

    @emoji.command(
        name="removemany",
        description="Bulk remove emotes from the current server",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_removemany(self, ctx, *, emotes: str):
        """bulk remove emotes"""
        import discord
        
        emoji_list = emotes.split()
        removed = 0
        failed = 0
        
        for emoji_str in emoji_list:
            try:
                custom_emoji = await discord.PartialEmoji.from_str(emoji_str)
                if custom_emoji.is_custom_emoji():
                    emoji_obj = discord.utils.get(ctx.guild.emojis, name=custom_emoji.name)
                    if emoji_obj:
                        await emoji_obj.delete()
                        removed += 1
            except:
                failed += 1
        
        await ctx.success(f"Removed {removed} emotes, failed {failed}")

    @emoji.command(
        name="removeduplicates",
        description="Remove duplicates of emotes",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_removeduplicates(self, ctx):
        """remove duplicate emotes"""
        seen = set()
        removed = 0
        
        for emoji in ctx.guild.emojis:
            if emoji.name in seen:
                try:
                    await emoji.delete()
                    removed += 1
                except:
                    pass
            else:
                seen.add(emoji.name)
        
        await ctx.success(f"Removed {removed} duplicate emotes")

    @emoji.command(
        name="remove",
        description="Removes emote from server",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_remove(self, ctx, emoji: str):
        """remove emote"""
        import discord
        
        try:
            custom_emoji = await discord.PartialEmoji.from_str(emoji)
            if custom_emoji.is_custom_emoji():
                emoji_obj = discord.utils.get(ctx.guild.emojis, name=custom_emoji.name)
                if emoji_obj:
                    await emoji_obj.delete()
                    await ctx.success(f"Removed emote `{custom_emoji.name}`")
                else:
                    await ctx.send("Emote not found in this server")
        except Exception as e:
            await ctx.send(f"Failed to remove emote: {str(e)}")

    @emoji.command(
        name="stats",
        description="Show top ten most used emotes",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_stats(self, ctx):
        """show emote usage stats"""
        emoji_data = await self.bot.db.fetch(
            "SELECT emoji_name, uses FROM emoji_usage WHERE guild_id = $1 ORDER BY uses DESC LIMIT 10",
            ctx.guild.id
        )
        
        if not emoji_data:
            return await ctx.send("No emoji usage data available")
        
        e = Embed(
            title=f"Top 10 Emojis in {ctx.guild.name}",
            color=self.color,
        )
        for i, emoji in enumerate(emoji_data, start=1):
            e.add_field(
                name=f"#{i} {emoji['emoji_name']}",
                value=f"{emoji['uses']} uses",
                inline=False
            )
        await ctx.send(embed=e)

    @emoji.command(
        name="information",
        description="View the most recent emote used",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_information(self, ctx, message_link: str):
        """get emote info from message"""
        # Parse message link and get emote info
        await ctx.send("This feature would show emote information from the message")

    @emoji.command(
        name="addmany",
        description="Bulk add emotes to the current server",
    )
    async def emoji_addmany(self, ctx, *, emotes: str):
        """bulk add emotes"""
        import discord
        
        emoji_list = emotes.split()
        added = 0
        failed = 0
        
        for emoji_str in emoji_list:
            try:
                custom_emoji = await discord.PartialEmoji.from_str(emoji_str)
                if custom_emoji.is_custom_emoji():
                    async with aiohttp.ClientSession() as session:
                        async with session.get(custom_emoji.url) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                await ctx.guild.create_custom_emoji(
                                    name=custom_emoji.name,
                                    image=data
                                )
                                added += 1
            except:
                failed += 1
        
        await ctx.success(f"Added {added} emotes, failed {failed}")

    @emoji.command(
        name="rename",
        description="Renames emote to the new name provided",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_rename(self, ctx, emoji: str, *, new_name: str):
        """rename emote"""
        import discord
        
        try:
            custom_emoji = await discord.PartialEmoji.from_str(emoji)
            if custom_emoji.is_custom_emoji():
                emoji_obj = discord.utils.get(ctx.guild.emojis, name=custom_emoji.name)
                if emoji_obj:
                    await emoji_obj.edit(name=new_name)
                    await ctx.success(f"Renamed emote to `{new_name}`")
                else:
                    await ctx.send("Emote not found in this server")
        except Exception as e:
            await ctx.send(f"Failed to rename emote: {str(e)}")

    @emoji.command(
        name="add",
        description="Downloads emote and adds to server",
    )
    async def emoji_add(self, ctx, emoji: str, characters: str = ""):
        """add emote from another server"""
        import discord
        
        try:
            custom_emoji = await discord.PartialEmoji.from_str(emoji)
            if custom_emoji.is_custom_emoji():
                async with aiohttp.ClientSession() as session:
                    async with session.get(custom_emoji.url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            name = custom_emoji.name
                            if characters:
                                name = characters
                            await ctx.guild.create_custom_emoji(
                                name=name,
                                image=data
                            )
                            await ctx.success(f"Added emote `{name}`")
        except Exception as e:
            await ctx.send(f"Failed to add emote: {str(e)}")
