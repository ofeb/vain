from __future__ import annotations

import re
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord.ext.commands import CommandError, group

from core.discord.package import Package
from core.discord.views.paginate import PaginateView, needs_pagination
from core.managers.permissions import has_permissions
from config import color, emojis

from core.discord.views.embed import compose, body, caption, reply_embed

if TYPE_CHECKING:
    from core.discord.ctx import Context

class StealPaginateView(PaginateView):
    def __init__(self, ctx: Context, pages: list[discord.Embed], emojis_to_steal: list):
        super().__init__(ctx, pages)
        self.emojis_to_steal = emojis_to_steal
        steal_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji="✂",
            label="Steal",
        )
        steal_btn.callback = self._steal_cb
        self.add_item(steal_btn)

    async def _steal_cb(self, interaction: discord.Interaction) -> None:
        emoji_data = self.emojis_to_steal[self.index]
        try:
            if emoji_data.get("url"):
                async with aiohttp.ClientSession() as session:
                    async with session.get(emoji_data["url"]) as resp:
                        image_data = await resp.read()
                emoji = await interaction.guild.create_custom_emoji(
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
            else:
                await interaction.response.send_message(
                    embed=reply_embed(
                        color=color.warn,
                        message=f"{emojis.warn} Cannot steal Unicode emoji.",
                    ),
                    ephemeral=True,
                )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                embed=reply_embed(
                    color=color.warn,
                    message=f"{emojis.warn} Failed to steal: {e}",
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

class Steal(Package):
    """steal emojis from messages"""

    @group(
        name="steal",
        description="Steal emojis from a message or scan recent messages for emojis",
        invoke_without_command=True,
        example=",steal <emoji or message link>",
        guild_only=True,
    )
    @has_permissions(manage_emojis=True)
    async def steal(self, ctx, *, target: str = None):
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
                return await ctx.warn("No emojis found in that message")

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

        return await ctx.success(f"Stole **{len(stolen)}** emojis: {' '.join(str(e) for e in stolen)}")

    async def _steal_scan(self, ctx):
        await ctx.typing()
        emojis_found = []

        async for message in ctx.channel.history(limit=100):
            emojis_found.extend(_parse_emoji(message.content))
            for embed in message.embeds:
                if embed.description:
                    emojis_found.extend(_parse_emoji(embed.description))

        if not emojis_found:
            return await ctx.warn("No custom emojis found in the last 100 messages")

        unique = {}
        for entry in emojis_found:
            if entry["id"] not in unique:
                unique[entry["id"]] = entry
        emojis_found = list(unique.values())

        pages = []
        for i, emoji_data in enumerate(emojis_found, start=1):
            embed = discord.Embed(
                color=color.base,
                description=compose(
                    body(
                        f"**Emoji:** `:{emoji_data['name']}:`",
                        f"**ID:** {emoji_data['id']}",
                    ),
                    caption(f"{i}/{len(emojis_found)}"),
                ),
            )
            embed.set_thumbnail(url=emoji_data["url"])
            pages.append(embed)

        if not needs_pagination(pages):
            return await ctx.send(embed=pages[0])
        view = StealPaginateView(ctx, pages, emojis_found)
        await view.start()

    def _parse_message_link(self, link: str) -> tuple[int, int]:
        pattern = r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
        match = re.search(pattern, link)
        if not match:
            raise ValueError("Invalid message link")
        return int(match.group(2)), int(match.group(3))
