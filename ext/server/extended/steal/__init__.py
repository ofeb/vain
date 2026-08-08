from __future__ import annotations

import re
from io import BytesIO
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from discord import ui
from discord.ext.commands import group

from core.discord.package import Package
from core.discord.views.paginate import PaginateView, needs_pagination
from core.managers.permissions import has_permissions
from config import color, emojis

from core.discord.views.embed import compose, body, caption, reply_embed

if TYPE_CHECKING:
    from core.discord.ctx import Context


class _StealButton(ui.Button):
    """Stable steal button for LayoutView rebuilds."""

    def __init__(self, parent: "StealPaginateView", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._steal_parent = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view or self._steal_parent
        if isinstance(view, StealPaginateView):
            await view._steal_cb(interaction)


class StealPaginateView(PaginateView):
    def __init__(
        self,
        ctx: Context,
        pages: list[discord.Embed],
        items: list,
        *,
        kind: str = "emoji",
        search_options: list[discord.SelectOption] | None = None,
    ):
        self.items = items
        self.kind = kind
        super().__init__(
            ctx,
            pages,
            search_options=search_options,
            search_title="Jump by name",
            search_placeholder="Search by name…",
        )

    def _page_container(self) -> ui.Container:
        container = super()._page_container()
        
        try:
            row = ui.ActionRow()
            row.add_item(
                _StealButton(
                    self,
                    style=discord.ButtonStyle.secondary,
                    emoji="✂",
                    label="Steal",
                    custom_id=f"vain:steal:{self.kind}:{id(self)}",
                )
            )
            container.add_item(row)
        except Exception:
            pass
        return container

    async def _steal_cb(self, interaction: discord.Interaction) -> None:
        if not self.items:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            return
        item = self.items[self.index]
        guild = interaction.guild
        if guild is None:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=reply_embed(
                        color=color.warn,
                        message=f"{emojis.warn} Guild only.",
                    ),
                    ephemeral=True,
                )
            return
        try:
            if self.kind == "sticker":
                await self._steal_sticker(interaction, guild, item)
            else:
                await self._steal_emoji(interaction, guild, item)
        except discord.HTTPException as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=reply_embed(
                        color=color.warn,
                        message=f"{emojis.warn} Failed to steal: {e}",
                    ),
                    ephemeral=True,
                )

    async def _steal_emoji(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        emoji_data: dict,
    ) -> None:
        if not emoji_data.get("url"):
            await interaction.response.send_message(
                embed=reply_embed(
                    color=color.warn,
                    message=f"{emojis.warn} Cannot steal Unicode emoji.",
                ),
                ephemeral=True,
            )
            return
        async with aiohttp.ClientSession() as session:
            async with session.get(emoji_data["url"]) as resp:
                image_data = await resp.read()
        emoji = await guild.create_custom_emoji(
            name=emoji_data["name"],
            image=image_data,
        )
        await interaction.response.send_message(
            embed=reply_embed(
                color=color.base,
                message=f"{emojis.approve} Stole {emoji} as `:{emoji.name}:`",
            ),
            ephemeral=True,
        )

    async def _steal_sticker(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        sticker_data: dict,
    ) -> None:
        url = sticker_data.get("url")
        name = (sticker_data.get("name") or "sticker")[:30]
        if not url:
            await interaction.response.send_message(
                embed=reply_embed(
                    color=color.warn,
                    message=f"{emojis.warn} Cannot steal that sticker.",
                ),
                ephemeral=True,
            )
            return
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                image_data = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/png")
        filename = "sticker.png"
        if "gif" in content_type:
            filename = "sticker.gif"
        elif "json" in content_type:
            filename = "sticker.json"
        file = discord.File(BytesIO(image_data), filename=filename)
        user = interaction.user
        sticker = await guild.create_sticker(
            name=name,
            description=sticker_data.get("description") or f"Stolen by {user}",
            emoji=sticker_data.get("emoji") or "✂️",
            file=file,
            reason=f"Sticker steal by {user} ({user.id})",
        )
        await interaction.response.send_message(
            embed=reply_embed(
                color=color.base,
                message=f"{emojis.approve} Stole sticker **{sticker.name}**",
            ),
            ephemeral=True,
        )


def _parse_emoji(text: str) -> list[dict]:
    results = []
    custom_pattern = r"<a?:([a-zA-Z0-9_]+):(\d+)>"
    for match in re.finditer(custom_pattern, text):
        name = match.group(1)
        emoji_id = match.group(2)
        animated = text[match.start() : match.start() + 3] == "<a:"
        ext = "gif" if animated else "png"
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=128"
        results.append({"name": name, "id": emoji_id, "url": url, "animated": animated})
    return results


def _sticker_payload(sticker: Any) -> dict:
    name = getattr(sticker, "name", None) or "sticker"
    sid = getattr(sticker, "id", None)
    url = getattr(sticker, "url", None)
    if not url and sid:
        url = f"https://media.discordapp.net/stickers/{sid}.png?size=320"
    description = getattr(sticker, "description", None) or ""
    emoji = "✂️"
    tags = getattr(sticker, "emoji", None) or getattr(sticker, "tags", None)
    if tags:
        emoji = str(tags).split(",")[0].strip() or emoji
    clean = re.sub(r"[^a-zA-Z0-9_]", "", str(name))[:30] or "sticker"
    return {
        "name": clean,
        "id": str(sid or ""),
        "url": str(url or ""),
        "description": str(description)[:100],
        "emoji": emoji,
    }


class Steal(Package):
    """steal emojis and stickers from messages"""

    @group(
        name="steal",
        description="Steal emojis from a message or scan recent messages for emojis",
        invoke_without_command=True,
        example=",steal <emoji or message link>",
        guild_only=True,
    )
    @has_permissions(manage_emojis=True)
    async def steal(self, ctx, *, target: str | None = None):
        """steal emojis"""
        if target:
            return await self._steal_specific(ctx, target)
        return await self._steal_scan(ctx)

    async def _steal_specific(self, ctx, target: str):
        emojis_found = _parse_emoji(target)

        if not emojis_found:
            
            try:
                channel_id, message_id = self._parse_message_link(target)
                channel = ctx.guild.get_channel(channel_id)
                if not channel:
                    return await ctx.warn("Could not find that channel")
                message = await channel.fetch_message(message_id)
                emojis_found = _parse_emoji(message.content)
                for embed in message.embeds:
                    if embed.description:
                        emojis_found.extend(_parse_emoji(embed.description))
            except Exception:
                emojis_found = []

        if not emojis_found:
            
            needle = target.strip().strip(":").lower()
            if needle and re.fullmatch(r"[a-zA-Z0-9_]{2,32}", needle):
                seen: dict[str, dict] = {}
                async for message in ctx.channel.history(limit=100):
                    for entry in _parse_emoji(message.content or ""):
                        if entry["name"].lower() == needle and entry["id"] not in seen:
                            seen[entry["id"]] = entry
                    for embed in message.embeds:
                        if embed.description:
                            for entry in _parse_emoji(embed.description):
                                if (
                                    entry["name"].lower() == needle
                                    and entry["id"] not in seen
                                ):
                                    seen[entry["id"]] = entry
                    if seen:
                        break
                emojis_found = list(seen.values())

        if not emojis_found:
            return await ctx.warn("No emojis found")

        stolen = []
        for emoji_data in emojis_found:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(emoji_data["url"]) as resp:
                        image_data = await resp.read()
                emoji = await ctx.guild.create_custom_emoji(
                    name=emoji_data["name"],
                    image=image_data,
                )
                stolen.append(emoji)
            except discord.HTTPException:
                continue

        if not stolen:
            return await ctx.fail("Failed to steal any emojis")

        return await ctx.success(
            f"Stole **{len(stolen)}** emojis: {' '.join(str(e) for e in stolen)}"
        )

    async def _steal_scan(self, ctx):
        await ctx.typing()
        emojis_found: list[dict] = []

        async for message in ctx.channel.history(limit=100):
            emojis_found.extend(_parse_emoji(message.content))
            for embed in message.embeds:
                if embed.description:
                    emojis_found.extend(_parse_emoji(embed.description))

        if not emojis_found:
            return await ctx.warn("No custom emojis found in the last 100 messages")

        unique: dict[str, dict] = {}
        for entry in emojis_found:
            if entry["id"] not in unique:
                unique[entry["id"]] = entry
        emojis_found = list(unique.values())

        pages = []
        search_options = []
        for i, emoji_data in enumerate(emojis_found, start=1):
            name = emoji_data["name"]
            embed = discord.Embed(
                color=color.base,
                description=compose(
                    body(
                        f"**Emoji:** `:{name}:`",
                        f"**ID:** {emoji_data['id']}",
                    ),
                    caption(f"{name} · {i}/{len(emojis_found)}"),
                ),
            )
            embed.set_thumbnail(url=emoji_data["url"])
            pages.append(embed)
            search_options.append(
                discord.SelectOption(
                    label=f":{name}:"[:100],
                    value=str(i - 1),
                    description=f"ID {emoji_data['id']}"[:100],
                )
            )

        view = StealPaginateView(
            ctx,
            pages,
            emojis_found,
            kind="emoji",
            search_options=search_options[:25],
        )
        await view.start()

    def _parse_message_link(self, link: str) -> tuple[int, int]:
        pattern = r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
        match = re.search(pattern, link)
        if not match:
            raise ValueError("Invalid message link")
        return int(match.group(2)), int(match.group(3))

    @group(
        name="stickersteal",
        aliases=["stealsticker", "ss"],
        description="Steal stickers from a message or scan recent messages",
        invoke_without_command=True,
        example=",stickersteal <message link>",
        guild_only=True,
    )
    @has_permissions(manage_emojis=True)
    async def stickersteal(self, ctx, *, target: str | None = None):
        """steal stickers"""
        if target:
            return await self._sticker_specific(ctx, target)
        return await self._sticker_scan(ctx)

    async def _sticker_specific(self, ctx, target: str):
        stickers_found: list[dict] = []

        if ctx.message.stickers:
            stickers_found.extend(_sticker_payload(s) for s in ctx.message.stickers)

        if not stickers_found:
            try:
                channel_id, message_id = self._parse_message_link(target)
                channel = ctx.guild.get_channel(channel_id)
                if not channel:
                    return await ctx.warn("Could not find that channel")
                message = await channel.fetch_message(message_id)
                stickers_found = [_sticker_payload(s) for s in message.stickers]
            except Exception:
                return await ctx.warn("No stickers found in that message")

        if not stickers_found:
            return await ctx.warn("No stickers found")

        stolen = []
        for data in stickers_found:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(data["url"]) as resp:
                        image_data = await resp.read()
                        content_type = resp.headers.get("Content-Type", "image/png")
                filename = "sticker.png"
                if "gif" in content_type:
                    filename = "sticker.gif"
                elif "json" in content_type:
                    filename = "sticker.json"
                file = discord.File(BytesIO(image_data), filename=filename)
                sticker = await ctx.guild.create_sticker(
                    name=data["name"],
                    description=data.get("description") or f"Stolen by {ctx.author}",
                    emoji=data.get("emoji") or "✂️",
                    file=file,
                    reason=f"Sticker steal by {ctx.author} ({ctx.author.id})",
                )
                stolen.append(sticker)
            except discord.HTTPException:
                continue

        if not stolen:
            return await ctx.fail("Failed to steal any stickers")

        names = ", ".join(f"`{s.name}`" for s in stolen)
        return await ctx.success(f"Stole **{len(stolen)}** sticker(s): {names}")

    async def _sticker_scan(self, ctx):
        await ctx.typing()
        found: list[dict] = []

        async for message in ctx.channel.history(limit=100):
            for s in message.stickers:
                found.append(_sticker_payload(s))

        if not found:
            return await ctx.warn("No stickers found in the last 100 messages")

        unique: dict[str, dict] = {}
        for entry in found:
            key = entry.get("id") or entry.get("url") or ""
            if key and key not in unique:
                unique[key] = entry
        found = list(unique.values())

        pages = []
        search_options = []
        for i, data in enumerate(found, start=1):
            name = data["name"]
            embed = discord.Embed(
                color=color.base,
                description=compose(
                    body(
                        f"**Sticker:** `{name}`",
                        f"**ID:** {data.get('id') or '—'}",
                    ),
                    caption(f"{name} · {i}/{len(found)}"),
                ),
            )
            if data.get("url"):
                embed.set_thumbnail(url=data["url"])
            pages.append(embed)
            search_options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=str(i - 1),
                    description=f"ID {data.get('id') or '—'}"[:100],
                )
            )

        view = StealPaginateView(
            ctx,
            pages,
            found,
            kind="sticker",
            search_options=search_options[:25],
        )
        await view.start()
