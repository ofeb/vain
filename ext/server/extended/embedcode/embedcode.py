from __future__ import annotations
from typing import TYPE_CHECKING

import re

import discord
from discord.ext.commands import hybrid_command, CommandError

from core.discord.package import Package
from core.discord.hybrid import describe
from core.managers.permissions import has_permissions
from core.managers.values import color, emojis



if TYPE_CHECKING:
    from core.bleed import Bleed

class Embedcode(Package):
    """copy embed code from a message"""

    @hybrid_command(
        name="embedcode",
        aliases=["copyembed", "ec"],
        description="Copy the embed code from a message",
        example=",embedcode https://discord.com/channels/123/456/789",
        guild_only=True,
    )
    @describe(message="Message link to copy embed from")
    @has_permissions(manage_messages=True)
    async def embedcode(self, ctx, *, message: str):
        """copy embed code from message"""
        channel_id, message_id = self._parse_message_link(message)

        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            return await ctx.fail("Could not find that channel")

        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            return await ctx.fail("Message not found")
        except discord.HTTPException:
            return await ctx.fail("Could not fetch message")

        if not msg.embeds:
            return await ctx.warn("That message has no embeds")

        embed = msg.embeds[0]
        code = self._embed_to_code(embed)

        if len(code) > 2000:
            return await ctx.warn("Embed code is too long to send. Check your DMs.")

        try:
            await ctx.author.send(
                embed=discord.Embed(
                    title="Embed Code",
                    description=f"```{code}```",
                    color=color.base,
                )
            )
            await ctx.success("Embed code sent to your DMs!")
        except discord.Forbidden:
            await ctx.warn("Could not DM you. Check your privacy settings.")

    def _parse_message_link(self, link: str) -> tuple[int, int]:
        pattern = r'discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)'
        match = re.search(pattern, link)
        if not match:
            raise CommandError("Invalid message link. Use a **Discord message link**.")
        return int(match.group(2)), int(match.group(3))

    def _embed_to_code(self, embed: discord.Embed) -> str:
        lines = ["{embed}"]

        if embed.title:
            lines.append(f"{{title: {embed.title}}}")

        if embed.description:
            lines.append(f"{{description: {embed.description}}}")

        if embed.color:
            color_hex = f"#{embed.color.value:06x}"
            lines.append(f"{{color: {color_hex}}}")

        if embed.author:
            author = embed.author
            if author.name:
                author_text = author.name
                if author.url:
                    author_text += f" | {author.url}"
                if author.icon_url:
                    author_text += f" | {author.icon_url}"
                lines.append(f"{{author: {author_text}}}")

        if embed.footer:
            footer = embed.footer
            if footer.text:
                footer_text = footer.text
                if footer.icon_url:
                    footer_text += f" | {footer.icon_url}"
                lines.append(f"{{footer: {footer_text}}}")

        if embed.image:
            lines.append(f"{{image: {embed.image.url}}}")

        if embed.thumbnail:
            lines.append(f"{{thumbnail: {embed.thumbnail.url}}}")

        for field in embed.fields:
            field_text = field.value or ""
            lines.append(f"{{field: {field.name} | {field_text} | {str(field.inline).lower()}}}")

        return "\n".join(lines)
