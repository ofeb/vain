from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, group, hybrid
from core.managers.permissions import has_permissions
from core.managers.values import color, emojis, api

log = logging.getLogger("bleed.fortnite")


@dataclass(slots=True)
class FortniteCosmetic:
    id: str
    name: str
    type_name: str
    rarity: str
    image_url: str
    price: int | None = None


class Fortnite(commands.Cog):
    """View the daily Fortnite shop and track items."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _fnbr_headers(self) -> dict[str, str]:
        key = api.fnbr.strip()
        if not key:
            raise commands.CommandError(
                "FNBR is not configured. Set **api.fnbr** in values.py."
            )
        return {"x-api-key": key}

    def _parse_fnbr_item(self, row: dict[str, Any]) -> FortniteCosmetic:
        images = row.get("images") or {}
        icon = images.get("icon") or images.get("featured") or ""
        price_raw = row.get("price") or "0"
        try:
            price = int(str(price_raw).replace(",", ""))
        except ValueError:
            price = None
        return FortniteCosmetic(
            id=row.get("id") or "",
            name=row.get("name") or "Unknown",
            type_name=row.get("readableType") or row.get("type") or "Item",
            rarity=row.get("rarity") or "common",
            image_url=icon if isinstance(icon, str) else "",
            price=price,
        )

    def _parse_fortnite_api_item(self, row: dict[str, Any]) -> FortniteCosmetic:
        item = row
        if row.get("brItems"):
            item = row["brItems"][0]
        images = item.get("images") or {}
        icon = (
            images.get("icon")
            or images.get("featured")
            or images.get("smallIcon")
            or ""
        )
        price = row.get("finalPrice") or row.get("regularPrice") or row.get("price")
        if isinstance(price, dict):
            price = price.get("finalPrice") or price.get("regularPrice")
        try:
            price_value = int(price) if price is not None else None
        except (TypeError, ValueError):
            price_value = None
        return FortniteCosmetic(
            id=item.get("id") or row.get("offerId") or "",
            name=item.get("name") or row.get("displayName") or "Unknown",
            type_name=item.get("type", {}).get("displayValue")
            if isinstance(item.get("type"), dict)
            else item.get("type") or "Item",
            rarity=(item.get("rarity") or {}).get("value", "common")
            if isinstance(item.get("rarity"), dict)
            else item.get("rarity") or "common",
            image_url=icon if isinstance(icon, str) else "",
            price=price_value,
        )

    async def _fetch_fortnite_api_shop_raw(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://fortnite-api.com/v2/shop",
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return {}
                payload = await resp.json()
        return payload.get("data") or {}

    async def fetch_fnbr_shop_raw(self) -> dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://fnbr.co/api/shop",
                    headers=self._fnbr_headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"FNBR returned {resp.status}")
                    payload = await resp.json()
            data = payload.get("data") or {}
            if data.get("featured") or data.get("daily") or data.get("sections"):
                return data
        except Exception as exc:
            log.warning("FNBR shop request failed: %s", exc)

        log.info("falling back to fortnite-api.com shop")
        fallback = await self._fetch_fortnite_api_shop_raw()

        def _entry_rows(bucket: str) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for entry in (fallback.get(bucket) or {}).get("entries") or []:
                cosmetic = self._parse_fortnite_api_item(entry)
                rows.append(
                    {
                        "id": cosmetic.id,
                        "name": cosmetic.name,
                        "readableType": cosmetic.type_name,
                        "rarity": cosmetic.rarity,
                        "images": {"icon": cosmetic.image_url},
                        "price": str(cosmetic.price or 0),
                    }
                )
            return rows

        featured = _entry_rows("featured")
        daily = _entry_rows("daily")
        return {
            "date": fallback.get("date") or "Today",
            "featured": featured,
            "daily": daily,
            "sections": [
                {
                    "displayName": "Featured",
                    "sortOrder": 0,
                    "items": [item["id"] for item in featured if item.get("id")],
                },
                {
                    "displayName": "Daily",
                    "sortOrder": 1,
                    "items": [item["id"] for item in daily if item.get("id")],
                },
            ],
        }

    async def fetch_fortnite_shop(self) -> list[FortniteCosmetic]:
        data = await self.fetch_fnbr_shop_raw()
        return [self._parse_fnbr_item(row) for row in (data.get("featured") or []) + (data.get("daily") or [])]

    async def fetch_fortnite_shop_layout(self):
        from .shop_renderer import ShopLayout, ShopSection, ShopTile

        data = await self.fetch_fnbr_shop_raw()
        catalog = {
            row["id"]: row for row in (data.get("featured") or []) + (data.get("daily") or [])
        }
        sections: list[ShopSection] = []
        for section in sorted(data.get("sections") or [], key=lambda s: s.get("sortOrder", 0)):
            tiles: list[ShopTile] = []
            for item_id in section.get("items") or []:
                row = catalog.get(item_id)
                if not row:
                    continue
                images = row.get("images") or {}
                icon = images.get("icon") or images.get("featured") or ""
                tiles.append(
                    ShopTile(
                        item_id=item_id,
                        name=row.get("name") or "Unknown",
                        price=str(row.get("price") or "0"),
                        rarity=row.get("rarity") or "common",
                        image_url=icon if isinstance(icon, str) else "",
                    )
                )
            if tiles:
                sections.append(
                    ShopSection(display_name=section.get("displayName") or "Items", items=tiles)
                )
        return ShopLayout(date=str(data.get("date") or "Today"), sections=sections)

    async def fetch_fortnite_cosmetic(self, name: str) -> FortniteCosmetic | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://fnbr.co/api/images",
                    headers=self._fnbr_headers(),
                    params={"search": name, "limit": 1},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"FNBR returned {resp.status}")
                    payload = await resp.json()
            rows = payload.get("data") or []
            if rows:
                return self._parse_fnbr_item(rows[0])
        except Exception as exc:
            log.warning("FNBR cosmetic lookup failed for %r: %s", name, exc)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://fortnite-api.com/v2/cosmetics/br/search",
                    params={"query": name, "matchMethod": "contains"},
                    headers={"Accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return None
                    payload = await resp.json()
            rows = payload.get("data") or []
            if not rows:
                return None
            return self._parse_fortnite_api_item(rows[0])
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
            try:
                layout = await self.fetch_fortnite_shop_layout()
            except Exception as exc:
                return await ctx.fail(f"Could not fetch the Fortnite shop: {exc}")

            if not layout.sections:
                return await ctx.fail("The shop is currently empty.")

            from .shop_renderer import render_shop_image

            try:
                image_bytes = await render_shop_image(layout, self.bot)
            except Exception as exc:
                return await ctx.fail(f"Failed to render shop image: {exc}")

            file = discord.File(
                __import__("io").BytesIO(image_bytes), filename="fortnite_shop.png"
            )

        embed = discord.Embed(
            title="Fortnite Item Shop",
            description=f"**{layout.date}**",
            color=color.base,
        )
        embed.set_image(url="attachment://fortnite_shop.png")
        total_items = sum(len(s.items) for s in layout.sections)
        embed.set_footer(text=f"{total_items} items \u2219 Module: gaming")
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
        name="item",
        description="Look up a specific Fortnite item",
        guild_only=True,
    )
    @describe(name="Item name to search for")
    async def fortnite_item(self, ctx: Context, *, name: str) -> None:
        async with ctx.typing():
            cosmetic = await self.fetch_fortnite_cosmetic(name)
        if not cosmetic:
            return await ctx.fail(f"No items found matching `{name}`.")

        embed = discord.Embed(
            title=cosmetic.name,
            color=color.base,
        )
        embed.add_field(name="Type", value=cosmetic.type_name, inline=True)
        embed.add_field(name="Rarity", value=cosmetic.rarity.title(), inline=True)
        if cosmetic.price is not None:
            embed.add_field(name="Price", value=f"{cosmetic.price} V-Bucks", inline=True)
        if cosmetic.image_url:
            embed.set_thumbnail(url=cosmetic.image_url)
        embed.set_footer(text="Module: gaming")
        await ctx.send(embed=embed)

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
        name="watch",
        description="Watch for a specific item to appear in the shop",
        guild_only=True,
    )
    @describe(item="Item name to watch for")
    @has_permissions(manage_guild=True)
    async def fortnite_watch(self, ctx: Context, *, item: str) -> None:
        await ctx.success(f"Now watching for **{item}** in the shop.")

    @fortnite.command(
        name="watch list",
        description="View all watched items",
        guild_only=True,
    )
    @has_permissions(manage_guild=True)
    async def fortnite_watch_list(self, ctx: Context) -> None:
        await ctx.fail("No items being watched.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Fortnite(bot))
