from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from config import color

from core.discord.views.embed import panel_embed

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("Vain.fortnite")

@dataclass(slots=True)
class FortniteCosmetic:
    id: str
    name: str
    type_name: str
    rarity: str
    image_url: str
    price: int | None = None

class Fortnite(Package):
    def __init__(self, bot: Vain):
        super().__init__(bot)

    def _parse_fortnite_api_item(self, row: dict[str, Any]) -> FortniteCosmetic:
        item = row
        if row.get("brItems"):
            item = row["brItems"][0]
        images = item.get("images") or {}
        icon = images.get("icon") or images.get("featured") or images.get("smallIcon") or ""
        price = row.get("finalPrice") or row.get("regularPrice") or row.get("price")
        if isinstance(price, dict):
            price = price.get("finalPrice") or price.get("regularPrice")
        try:
            price_value = int(price) if price is not None else None
        except (TypeError, ValueError):
            price_value = None
        rarity = item.get("rarity")
        if isinstance(rarity, dict):
            rarity = rarity.get("value", "common")
        type_info = item.get("type")
        if isinstance(type_info, dict):
            type_name = type_info.get("displayValue") or type_info.get("value") or "Item"
        else:
            type_name = type_info or "Item"
        return FortniteCosmetic(
            id=item.get("id") or row.get("offerId") or "",
            name=item.get("name") or row.get("displayName") or "Unknown",
            type_name=type_name,
            rarity=rarity or "common",
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

    async def fetch_fortnite_shop_layout(self):
        from .improper.shop_renderer import ShopLayout, ShopSection, ShopTile

        data = await self._fetch_fortnite_api_shop_raw()
        catalog: dict[str, dict[str, Any]] = {}

        def _entry_rows(bucket: str) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for entry in (data.get(bucket) or {}).get("entries") or []:
                cosmetic = self._parse_fortnite_api_item(entry)
                row = {
                    "id": cosmetic.id,
                    "name": cosmetic.name,
                    "readableType": cosmetic.type_name,
                    "rarity": cosmetic.rarity,
                    "images": {"icon": cosmetic.image_url},
                    "price": str(cosmetic.price or 0),
                }
                if cosmetic.id:
                    catalog[cosmetic.id] = row
                rows.append(row)
            return rows

        featured = _entry_rows("featured")
        daily = _entry_rows("daily")
        sections: list[ShopSection] = []

        raw_sections = data.get("sections") or []
        if raw_sections:
            for section in sorted(raw_sections, key=lambda s: s.get("sortOrder", 0)):
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
        else:
            for label, rows in (("Featured", featured), ("Daily", daily)):
                if not rows:
                    continue
                tiles = [
                    ShopTile(
                        item_id=row["id"],
                        name=row["name"],
                        price=str(row["price"]),
                        rarity=row["rarity"],
                        image_url=(row.get("images") or {}).get("icon", ""),
                    )
                    for row in rows
                    if row.get("id")
                ]
                if tiles:
                    sections.append(ShopSection(display_name=label, items=tiles))

        return ShopLayout(date=str(data.get("date") or "Today"), sections=sections)

    async def fetch_fortnite_cosmetic(self, name: str) -> FortniteCosmetic | None:
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

    @hybrid(
        name="fortnite",
        description="fortnite shop and cosmetic lookup",
        group=True,
        aliases=["fn"],
    )
    async def fortnite(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @fortnite.command(
        name="itemshop",
        description="view the current fortnite item shop",
        aliases=["shop", "item-shop"],
    )
    async def fortnite_itemshop(self, ctx: Context) -> None:
        async with ctx.typing():
            try:
                layout = await self.fetch_fortnite_shop_layout()
            except Exception as exc:
                return await ctx.fail(f"Could not fetch the Fortnite shop: {exc}")

            if not layout.sections:
                return await ctx.warn("The shop is currently empty.")

            from .improper.shop_renderer import render_shop_image

            try:
                image_bytes = await render_shop_image(layout)
            except Exception as exc:
                return await ctx.fail(f"Failed to render shop image: {exc}")

        file = discord.File(io.BytesIO(image_bytes), filename="fortnite_shop.png")
        total_items = sum(len(s.items) for s in layout.sections)
        embed = panel_embed(
            title="Fortnite Item Shop",
            color=color.base,
            lines=[f"**{layout.date}**"],
            footer=f"{total_items} items",
            timestamp=False,
        )
        embed.set_image(url="attachment://fortnite_shop.png")
        await ctx.send(embed=embed, file=file)

    @fortnite.command(
        name="cosmetic",
        description="look up a fortnite cosmetic",
        aliases=["item", "skin"],
    )
    @describe(name="Cosmetic name to search for")
    async def fortnite_cosmetic(self, ctx: Context, *, name: str) -> None:
        async with ctx.typing():
            cosmetic = await self.fetch_fortnite_cosmetic(name)
        if not cosmetic:
            return await ctx.warn(f"No cosmetics found matching `{name}`.")

        embed = panel_embed(title=cosmetic.name, color=color.base, lines=[], timestamp=False)
        embed.add_field(name="Type", value=cosmetic.type_name, inline=True)
        embed.add_field(name="Rarity", value=cosmetic.rarity.title(), inline=True)
        if cosmetic.price is not None:
            embed.add_field(name="Price", value=f"{cosmetic.price} V-Bucks", inline=True)
        if cosmetic.image_url:
            embed.set_thumbnail(url=cosmetic.image_url)
        await ctx.send(embed=embed)

    @hybrid(
        name="fortniteshop",
        description="view the current fortnite item shop",
        aliases=["fnshop"],
    )
    async def fortniteshop(self, ctx: Context) -> None:
        await self.fortnite_itemshop.callback(self, ctx)

async def setup(bot: Vain):
    await bot.add_cog(Fortnite(bot))
