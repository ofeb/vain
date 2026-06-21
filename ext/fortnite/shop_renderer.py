"""Render FNBR shop rotations as a horizontal multi-column grid image."""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("bleed.fortnite.shop")

TILE = 132
NAME_H = 34
HEADER_H = 40
SECTION_PAD = 14
COLUMN_GAP = 18
BG = (12, 16, 28)
HEADER_BG = (18, 24, 40)
TEXT = (235, 240, 255)
MUTED = (140, 150, 170)

RARITY_COLORS: dict[str, tuple[int, int, int]] = {
    "common": (140, 144, 148),
    "uncommon": (60, 170, 58),
    "rare": (73, 172, 242),
    "epic": (177, 91, 226),
    "legendary": (222, 146, 42),
    "mythic": (255, 215, 0),
    "exotic": (60, 200, 120),
    "icon": (30, 180, 255),
    "gaminglegends": (20, 120, 200),
    "marvel": (180, 30, 30),
    "dc": (45, 45, 120),
    "starwars": (25, 25, 25),
    "frozen": (120, 210, 255),
    "lava": (255, 90, 30),
    "shadow": (55, 55, 75),
    "slurp": (40, 180, 255),
    "dark": (120, 60, 180),
}


@dataclass(slots=True)
class ShopTile:
    item_id: str
    name: str
    price: str
    rarity: str
    image_url: str


@dataclass(slots=True)
class ShopSection:
    display_name: str
    items: list[ShopTile]


@dataclass(slots=True)
class ShopLayout:
    date: str
    sections: list[ShopSection]


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rarity_color(rarity: str) -> tuple[int, int, int]:
    return RARITY_COLORS.get(rarity.lower().replace(" ", ""), (90, 98, 118))


def _items_per_row(count: int) -> int:
    if count >= 20:
        return 6
    if count >= 12:
        return 5
    if count >= 8:
        return 4
    return min(count, 6) or 1


def _section_size(section: ShopSection) -> tuple[int, int]:
    per_row = _items_per_row(len(section.items))
    rows = max(1, (len(section.items) + per_row - 1) // per_row)
    width = per_row * TILE + max(0, per_row - 1) * 6
    height = HEADER_H + rows * (TILE + NAME_H + 6) + SECTION_PAD
    return width, height


def _distribute_columns(sections: list[ShopSection], columns: int = 4) -> list[list[ShopSection]]:
    buckets: list[list[ShopSection]] = [[] for _ in range(columns)]
    heights = [0] * columns
    for section in sections:
        idx = heights.index(min(heights))
        buckets[idx].append(section)
        heights[idx] += _section_size(section)[1]
    return buckets


async def _fetch_tile_image(http: Any, url: str) -> Image.Image | None:
    if not url or url is False:
        return None
    try:
        data = await http.read("GET", url)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def _draw_tile(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    tile: ShopTile,
    image: Image.Image | None,
    x: int,
    y: int,
) -> None:
    color = _rarity_color(tile.rarity)
    draw.rectangle((x, y, x + TILE, y + TILE), fill=color)
    if image is not None:
        icon = image.copy()
        icon.thumbnail((TILE - 16, TILE - 16), Image.Resampling.LANCZOS)
        ox = x + (TILE - icon.width) // 2
        oy = y + (TILE - icon.height) // 2
        canvas.paste(icon, (ox, oy), icon)
    name = tile.name if len(tile.name) <= 18 else tile.name[:16] + ".."
    draw.rectangle((x, y + TILE, x + TILE, y + TILE + NAME_H), fill=(10, 12, 20))
    draw.text((x + 6, y + TILE + 4), name, font=_font(11), fill=TEXT)
    draw.text((x + 6, y + TILE + 18), f"{tile.price} V", font=_font(10), fill=MUTED)


def _draw_section(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    section: ShopSection,
    images: dict[str, Image.Image | None],
    x: int,
    y: int,
) -> int:
    per_row = _items_per_row(len(section.items))
    section_w = per_row * TILE + max(0, per_row - 1) * 6
    draw.rectangle((x, y, x + section_w, y + HEADER_H), fill=HEADER_BG)
    draw.text((x + 8, y + 10), section.display_name.upper(), font=_font(15, bold=True), fill=TEXT)
    y += HEADER_H + 4
    for index, tile in enumerate(section.items):
        row = index // per_row
        col = index % per_row
        tx = x + col * (TILE + 6)
        ty = y + row * (TILE + NAME_H + 6)
        _draw_tile(canvas, draw, tile, images.get(tile.item_id), tx, ty)
    _, height = _section_size(section)
    return height


async def render_shop_image(layout: ShopLayout, http: Any) -> bytes:
    """Build a wide horizontal FNBR-style shop collage."""
    if not layout.sections:
        raise ValueError("shop has no sections")

    columns = _distribute_columns(layout.sections, 4)
    col_widths = [
        max((_section_size(section)[0] for section in col), default=TILE) for col in columns
    ]
    col_heights = [
        sum(_section_size(section)[1] for section in col) + SECTION_PAD * max(0, len(col) - 1)
        for col in columns
    ]

    title_h = 54
    width = sum(col_widths) + COLUMN_GAP * (len(columns) - 1) + 28
    height = max(col_heights, default=200) + title_h + 24

    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)
    draw.text((14, 12), "FORTNITE ITEM SHOP", font=_font(22, bold=True), fill=TEXT)
    draw.text((14, 34), layout.date, font=_font(13), fill=MUTED)

    urls = {tile.item_id: tile.image_url for section in layout.sections for tile in section.items}
    image_results = await asyncio.gather(
        *(_fetch_tile_image(http, url) for url in urls.values()),
        return_exceptions=True,
    )
    images: dict[str, Image.Image | None] = {}
    for item_id, result in zip(urls.keys(), image_results):
        images[item_id] = result if isinstance(result, Image.Image) else None

    x_offset = 14
    for col_index, column in enumerate(columns):
        y_offset = title_h
        for section in column:
            used = _draw_section(canvas, draw, section, images, x_offset, y_offset)
            y_offset += used + SECTION_PAD
        x_offset += col_widths[col_index] + COLUMN_GAP

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
