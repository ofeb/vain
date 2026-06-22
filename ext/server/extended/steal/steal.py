from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

import discord
from discord.ext.commands import group, CommandError

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.managers.values import color, emojis



if TYPE_CHECKING:
    from core.bleed import Bleed

class StealPaginateView(discord.ui.View):
    def __init__(self, ctx, pages: list[discord.Embed], emojis_to_steal: list):
        super().__init__(timeout=60.0)
        self.ctx = ctx
        self.pages = pages
        self.emojis_to_steal = emojis_to_steal
        self.index = 0
        self.message: Optional[discord.Message] = None

    def _current(self) -> dict:
        return {"embed": self.pages[self.index], "view": self}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message(
            embed=discord.Embed(
                color=color.warn,
                description=f"{emojis.warn} {interaction.user.mention}: You're not the **author** of this embed!",
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    @discord.ui.button(
        style=discord.ButtonStyle.primary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.previous),
    )
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(**self._current())

    @discord.ui.button(
        style=discord.ButtonStyle.primary,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.next),
    )
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index + 1) % len(self.pages)
        await interaction.response.edit_message(**self._current())

    @discord.ui.button(
        style=discord.ButtonStyle.secondary,
        emoji="✂",
        label="Steal",
    )
    async def steal_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        emoji_data = self.emojis_to_steal[self.index]
        try:
            if emoji_data.get("url"):
                emoji = await interaction.guild.create_custom_emoji(
                    name=emoji_data["name"],
                    image=await self._fetch_image(emoji_data["url"]),
                )
                await interaction.response.send_message(
                    embed=discord.Embed(
                        color=color.base,
                        description=f"{emojis.approve} Stole {emoji} as `:{emoji.name}:`",
                    ),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        color=color.warn,
                        description=f"{emojis.warn} Cannot steal Unicode emoji.",
                    ),
                    ephemeral=True,
                )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                embed=discord.Embed(
                    color=color.warn,
                    description=f"{emojis.warn} Failed to steal: {e}",
                ),
                ephemeral=True,
            )

    async def _fetch_image(self, url: str) -> bytes:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.read()

    @discord.ui.button(
        style=discord.ButtonStyle.danger,
        emoji=discord.PartialEmoji.from_str(emojis.paginator.cancel),
    )
    async def cancel_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer()
        if interaction.message is not None:
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass
        self.stop()

    async def start(self) -> discord.Message:
        self.message = await self.ctx.send(**self._current())
        return self.message


def _parse_emoji(text: str) -> list[dict]:
    results = []
    custom_pattern = r'<a?:([a-zA-Z0-9_]+):(\d+)>'
    for match in re.finditer(custom_pattern, text):
        name = match.group(1)
        emoji_id = match.group(2)
        animated = text[match.start():match.start()+3] == '<a:'
        ext = 'gif' if animated else 'png'
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
                    return await ctx.fail("Could not find that channel")
                message = await channel.fetch_message(message_id)
                emojis_found = _parse_emoji(message.content)
                for embed in message.embeds:
                    if embed.description:
                        emojis_found.extend(_parse_emoji(embed.description))
            except Exception:
                return await ctx.fail("No emojis found in that message")

        if not emojis_found:
            return await ctx.fail("No emojis found")

        stolen = []
        for emoji_data in emojis_found:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(emoji_data["url"]) as resp:
                        image_data = await resp.read()
                emoji = await ctx.guild.create_custom_emoji(name=emoji_data["name"], image=image_data)
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
            return await ctx.fail("No custom emojis found in the last 100 messages")

        unique = {}
        for e in emojis_found:
            if e["id"] not in unique:
                unique[e["id"]] = e
        emojis_found = list(unique.values())

        pages = []
        for i, emoji_data in enumerate(emojis_found, start=1):
            embed = discord.Embed(
                color=color.base,
                description=f"**Emoji:** `:{emoji_data['name']}:`\n**ID:** {emoji_data['id']}",
            )
            embed.set_thumbnail(url=emoji_data["url"])
            embed.set_footer(text=f"{i}/{len(emojis_found)} \u2219 Module: server")
            pages.append(embed)

        view = StealPaginateView(ctx, pages, emojis_found)
        await view.start()

    def _parse_message_link(self, link: str) -> tuple[int, int]:
        pattern = r'discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)'
        match = re.search(pattern, link)
        if not match:
            raise ValueError("Invalid message link")
        return int(match.group(2)), int(match.group(3))
