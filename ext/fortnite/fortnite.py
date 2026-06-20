from __future__ import annotations

import io
from io import BytesIO
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.permissions import has_permissions
from core.managers.values import color, emojis

FORTNITE_SHOP_API = "https://fortnite-api.com/v2/shop"
FORTNITE_COSMETICS_API = "https://fortnite-api.com/v2/cosmetics/br/search"

RARITY_COLORS = {
    "Common": (165, 165, 165),
    "Uncommon": (0, 180, 0),
    "Rare": (0, 110, 255),
    "Epic": (163, 53, 238),
    "Legendary": (255, 165, 0),
    "Mythic": (255, 100, 0),
    "Exotic": (0, 200, 200),
}


def _get_rarity_color(rarity: str) -> tuple[int, int, int]:
    return RARITY_COLORS.get(rarity, (100, 100, 100))


async def _download_image(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                return Image.open(BytesIO(data))
    except Exception:
        return None


def _paste_item(
    canvas: Image.Image,
    icon: Image.Image | None,
    item: dict,
    x: int,
    y: int,
    cell_w: int,
    cell_h: int,
    font: ImageFont.FreeTypeFont,
    small_font: ImageFont.FreeTypeFont,
) -> None:
    draw = ImageDraw.Draw(canvas)
    rarity = item.get("rarity", "Common")
    if isinstance(rarity, dict):
        rarity = rarity.get("name", "Common")
    rarity_color = _get_rarity_color(rarity)

    draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(40, 40, 40), outline=rarity_color, width=2)

    if icon:
        icon_resized = icon.resize((120, 120), Image.Resampling.LANCZOS)
        icon_x = x + (cell_w - 120) // 2
        canvas.paste(icon_resized, (icon_x, y + 10))

    name = item.get("name", "Unknown")[:22]
    vbucks = item.get("price", "N/A")
    name_y = y + cell_h - 48
    draw.text((x + 8, name_y), name, fill=(255, 255, 255), font=small_font)
    draw.text((x + 8, name_y + 18), f"{vbucks} V-Bucks", fill=(200, 200, 200), font=small_font)


def _make_horizontal_shop_image(items: list[dict], icons: dict[str, Image.Image | None], max_items: int = 30) -> io.BytesIO:
    items = items[:max_items]
    cols = min(6, len(items))
    rows = (len(items) + cols - 1) // cols

    cell_w, cell_h = 180, 220
    padding = 10
    header_h = 60
    img_w = cols * cell_w + (cols + 1) * padding
    img_h = header_h + rows * cell_h + (rows + 1) * padding

    img = Image.new("RGB", (img_w, img_h), (30, 30, 30))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
        small_font = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
        small_font = font

    draw.text((img_w // 2 - 100, 18), "Daily Fortnite Shop", fill=(255, 255, 255), font=font)

    for idx, item in enumerate(items):
        r = idx // cols
        c = idx % cols
        x = padding + c * (cell_w + padding)
        y = header_h + padding + r * (cell_h + padding)

        item_name = item.get("name", "Unknown")
        icon = icons.get(item_name)
        _paste_item(img, icon, item, x, y, cell_w, cell_h, font, small_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


class Fortnite(commands.Cog):
    """View the daily Fortnite shop and track items."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._watch_cache: dict[int, list[str]] = {}
        self._shop_cache: dict = {}

    async def _fetch_shop(self) -> dict | None:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(FORTNITE_SHOP_API, timeout=30) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            except Exception:
                return None

    async def _fetch_cosmetic(self, name: str) -> Optional[dict]:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    FORTNITE_COSMETICS_API,
                    params={"name": name, "matchMethod": "contains"},
                    timeout=15,
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    results = data.get("data", [])
                    return results[0] if results else None
            except Exception:
                return None

    @hybrid(
        name="fortniteshop",
        description="Show the daily Fortnite shop rotation",
        aliases=["fnshop"],
        guild_only=True,
    )
    async def fortniteshop(self, ctx: Context) -> None:
        async with ctx.typing():
            data = await self._fetch_shop()
            if not data:
                await ctx.fail("Could not fetch the Fortnite shop.")
                return

            entries = data.get("data", {}).get("entries", [])
            if not entries:
                await ctx.fail("The shop is currently empty.")
                return

            icons: dict[str, Image.Image | None] = {}
            for entry in entries:
                item_name = entry.get("name", "Unknown")
                images = entry.get("items", [{}])[0].get("images", {}) if entry.get("items") else {}
                icon_url = images.get("full") or images.get("icon") or entry.get("newDisplayAsset", {}).get("mediaList", [{}])[0].get("url") if entry.get("newDisplayAsset", {}).get("mediaList") else None
                icons[item_name] = await _download_image(icon_url)

            buf = _make_horizontal_shop_image(entries, icons)
            file = discord.File(buf, filename="fortnite_shop.png")

        embed = discord.Embed(
            title="Daily Fortnite Shop",
            color=color.base,
        )
        embed.set_image(url="attachment://fortnite_shop.png")
        embed.set_footer(text=f"{len(entries)} items available")
        await ctx.send(embed=embed, file=file)

    @group(
        name="fortnite",
        description="Fortnite shop and item tracking commands",
        guild_only=True,
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True, manage_channels=True)
    async def fortnite(self, ctx: Context) -> None:
        await ctx.send_help()

    @fortnite.command(
        name="shop",
        description="Set a channel for daily Fortnite shop updates",
        guild_only=True,
    )
    @describe(channel="Channel for shop updates")
    @has_permissions(manage_guild=True, manage_channels=True)
    async def fortnite_shop(self, ctx: Context, channel: discord.TextChannel) -> None:
        embed = discord.Embed(
            title="Fortnite Shop Channel",
            description=f"Daily shop updates will be sent to {channel.mention}",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @fortnite.command(
        name="shop ping",
        description="Set a role to ping for shop updates",
        guild_only=True,
    )
    @describe(role="Role to ping")
    @has_permissions(manage_guild=True, roles=True)
    async def fortnite_shop_ping(self, ctx: Context, role: discord.Role) -> None:
        embed = discord.Embed(
            title="Fortnite Shop Ping",
            description=f"Shop updates will ping {role.mention}",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @fortnite.command(
        name="shop voting",
        description="Toggle shop item voting",
        guild_only=True,
    )
    @describe(setting="on or off")
    @has_permissions(manage_guild=True)
    async def fortnite_shop_voting(self, ctx: Context, setting: str) -> None:
        enabled = setting.lower() in ("on", "true", "enable", "1")
        embed = discord.Embed(
            title="Fortnite Shop Voting",
            description=f"Shop voting {'enabled' if enabled else 'disabled'}.",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @fortnite.command(
        name="item",
        description="Look up a specific Fortnite item",
        guild_only=True,
    )
    @describe(name="Item name to search for")
    async def fortnite_item(self, ctx: Context, *, name: str) -> None:
        cosmetic = await self._fetch_cosmetic(name)
        if not cosmetic:
            await ctx.fail(f"No items found matching `{name}`.")
            return

        embed = discord.Embed(
            title=cosmetic.get("name", "Unknown"),
            description=cosmetic.get("description", "No description available."),
            color=color.base,
        )
        embed.add_field(name="Rarity", value=cosmetic.get("rarity", {}).get("name", "Unknown"), inline=True)
        embed.add_field(name="Type", value=cosmetic.get("type", {}).get("name", "Unknown"), inline=True)
        if cosmetic.get("images", {}).get("icon"):
            embed.set_thumbnail(url=cosmetic["images"]["icon"])
        await ctx.send(embed=embed)

    @fortnite.command(
        name="watch",
        description="Watch for a specific item to appear in the shop",
        guild_only=True,
    )
    @describe(item="Item name to watch for")
    @has_permissions(manage_guild=True)
    async def fortnite_watch(self, ctx: Context, *, item: str) -> None:
        if ctx.guild.id not in self._watch_cache:
            self._watch_cache[ctx.guild.id] = []
        if item.lower() not in self._watch_cache[ctx.guild.id]:
            self._watch_cache[ctx.guild.id].append(item.lower())
        await ctx.success(f"Now watching for **{item}** in the shop.")

    @fortnite.command(
        name="watch list",
        description="View all watched items",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def fortnite_watch_list(self, ctx: Context) -> None:
        watched = self._watch_cache.get(ctx.guild.id, [])
        if not watched:
            await ctx.fail("No items being watched.")
            return

        embed = discord.Embed(
            title="Watched Items",
            description="\n".join(f"`{i+1}.` {item}" for i, item in enumerate(watched)),
            color=color.base,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fortnite(bot))
