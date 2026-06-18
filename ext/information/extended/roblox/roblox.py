from __future__ import annotations

from discord.ext.commands import group
from discord import Embed
import aiohttp

from core.discord.package import Package
from core.managers.values import color


class Roblox(Package):
    """roblox management"""

    def __init__(self, bot):
        self.bot = bot
        self.color = color.base

    @group(
        name="roblox",
        description="Gets profile information on the given Roblox user",
        invoke_without_command=True,
    )
    async def roblox(self, ctx, username: str):
        """get roblox profile"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://users.roblox.com/v1/users/search?keyword={username}&limit=1") as resp:
                if resp.status != 200:
                    return await ctx.send("User not found")
                data = await resp.json()
        
        if not data.get('data'):
            return await ctx.send("User not found")
        
        user = data['data'][0]
        e = Embed(
            title=user['name'],
            description=f"Display Name: {user['displayName']}",
            color=self.color,
        )
        e.set_thumbnail(url=f"https://www.roblox.com/headshot-thumbnail/image?userId={user['id']}&width=420&height=420&format=png")
        e.add_field(name="ID", value=user['id'], inline=True)
        e.add_field(name="Created", value=user['created'], inline=True)
        await ctx.send(embed=e)

    @roblox.command(
        name="fromdiscord",
        description="Get Roblox account from Discord account",
    )
    async def roblox_fromdiscord(self, ctx, user_id: int):
        """get roblox from discord"""
        roblox_id = await self.bot.db.fetchval(
            "SELECT roblox_id FROM roblox_links WHERE discord_id = $1",
            user_id
        )
        if not roblox_id:
            return await ctx.send("No Roblox account linked to this Discord account")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://users.roblox.com/v1/users/{roblox_id}") as resp:
                if resp.status != 200:
                    return await ctx.send("Failed to fetch Roblox user")
                data = await resp.json()
        
        e = Embed(
            title=data['name'],
            description=f"Display Name: {data['displayName']}",
            color=self.color,
        )
        e.set_thumbnail(url=f"https://www.roblox.com/headshot-thumbnail/image?userId={data['id']}&width=420&height=420&format=png")
        e.add_field(name="ID", value=data['id'], inline=True)
        await ctx.send(embed=e)

    @roblox.command(
        name="devex",
        description="No description given",
    )
    async def roblox_devex(self, ctx, robux: str):
        """devex robux"""
        await ctx.send("DevEx requires Roblox account verification and is not available through this bot")

    @roblox.command(
        name="todiscord",
        description="Get Discord account from Roblox account",
    )
    async def roblox_todiscord(self, ctx, username: str):
        """get discord from roblox"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://users.roblox.com/v1/users/search?keyword={username}&limit=1") as resp:
                if resp.status != 200:
                    return await ctx.send("User not found")
                data = await resp.json()
        
        if not data.get('data'):
            return await ctx.send("User not found")
        
        roblox_id = data['data'][0]['id']
        discord_id = await self.bot.db.fetchval(
            "SELECT discord_id FROM roblox_links WHERE roblox_id = $1",
            roblox_id
        )
        if not discord_id:
            return await ctx.send("No Discord account linked to this Roblox account")
        
        user = self.bot.get_user(discord_id)
        if not user:
            user = await self.bot.fetch_user(discord_id)
        
        await ctx.send(f"Discord account: {user.mention} ({user})")

    @roblox.command(
        name="template",
        description="Download asset for an item",
    )
    async def roblox_template(self, ctx, asset_id: int):
        """download roblox asset"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://assetdelivery.roblox.com/v1/assetId/{asset_id}") as resp:
                if resp.status != 200:
                    return await ctx.send("Asset not found")
                data = await resp.json()
        
        if data.get('location'):
            await ctx.send(f"Asset URL: {data['location']}")
        else:
            await ctx.send("Failed to get asset URL")

    @roblox.command(
        name="inventory",
        description="No description given",
    )
    async def roblox_inventory(self, ctx, username: str):
        """get roblox inventory"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://users.roblox.com/v1/users/search?keyword={username}&limit=1") as resp:
                if resp.status != 200:
                    return await ctx.send("User not found")
                data = await resp.json()
        
        if not data.get('data'):
            return await ctx.send("User not found")
        
        user_id = data['data'][0]['id']
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://inventory.roblox.com/v1/users/{user_id}/assets/collectibles?limit=10") as resp:
                if resp.status != 200:
                    return await ctx.send("Failed to fetch inventory")
                data = await resp.json()
        
        if not data.get('data'):
            return await ctx.send("No collectibles found")
        
        e = Embed(
            title=f"{username}'s Collectibles",
            color=self.color,
        )
        for item in data['data'][:5]:
            e.add_field(
                name=item['name'],
                value=f"Rap: {item.get('recentAveragePrice', 'N/A')} Robux",
                inline=False
            )
        await ctx.send(embed=e)

    @roblox.command(
        name="item",
        description="No description given",
    )
    async def roblox_item(self, ctx, query: str):
        """search roblox item"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://catalog.roblox.com/v1/search/items?keyword={query}&limit=10") as resp:
                if resp.status != 200:
                    return await ctx.send("Failed to search items")
                data = await resp.json()
        
        if not data.get('data'):
            return await ctx.send("No items found")
        
        items = data['data'][:5]
        e = Embed(
            title=f"Roblox Items: {query}",
            color=self.color,
        )
        for item in items:
            e.add_field(
                name=item['name'],
                value=f"Price: {item.get('price', 'Free')} Robux",
                inline=False
            )
        await ctx.send(embed=e)

    @roblox.command(
        name="outfits",
        description="View all outfits for a user",
    )
    async def roblox_outfits(self, ctx, username: str):
        """get roblox outfits"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://users.roblox.com/v1/users/search?keyword={username}&limit=1") as resp:
                if resp.status != 200:
                    return await ctx.send("User not found")
                data = await resp.json()
        
        if not data.get('data'):
            return await ctx.send("User not found")
        
        user_id = data['data'][0]['id']
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://thumbnails.roblox.com/v1/users/outfits?userIds={user_id}&size=420x420&format=Png&isCircular=false") as resp:
                if resp.status != 200:
                    return await ctx.send("Failed to fetch outfits")
                data = await resp.json()
        
        if not data.get('data'):
            return await ctx.send("No outfits found")
        
        e = Embed(
            title=f"{username}'s Outfits",
            color=self.color,
        )
        for outfit in data['data'][:5]:
            e.add_field(
                name=f"Outfit {outfit['targetId']}",
                value=f"[View](https://www.roblox.com/catalog/?Keyword=outfit)",
                inline=False
            )
        await ctx.send(embed=e)

    @roblox.command(
        name="check",
        description="No description given",
    )
    async def roblox_check(self, ctx, username: str, asset_id_or_name: str):
        """check if user has item"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://users.roblox.com/v1/users/search?keyword={username}&limit=1") as resp:
                if resp.status != 200:
                    return await ctx.send("User not found")
                data = await resp.json()
        
        if not data.get('data'):
            return await ctx.send("User not found")
        
        user_id = data['data'][0]['id']
        
        try:
            asset_id = int(asset_id_or_name)
        except ValueError:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://catalog.roblox.com/v1/search/items?keyword={asset_id_or_name}&limit=1") as resp:
                    if resp.status != 200:
                        return await ctx.send("Failed to search item")
                    item_data = await resp.json()
            
            if not item_data.get('data'):
                return await ctx.send("Item not found")
            
            asset_id = item_data['data'][0]['id']
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://inventory.roblox.com/v1/users/{user_id}/items/{asset_id}") as resp:
                if resp.status == 200:
                    return await ctx.send(f"{username} owns this item")
                else:
                    return await ctx.send(f"{username} does not own this item")
