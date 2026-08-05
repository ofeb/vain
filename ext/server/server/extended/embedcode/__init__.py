from __future__ import annotations
from typing import TYPE_CHECKING

import re

import discord
from discord.ext.commands import hybrid_command, CommandError

from core.discord.package import Package
from core.discord.hybrid import describe
from core.managers.permissions import has_permissions
from config import color, emojis

from core.discord.views.embed import panel_embed

if TYPE_CHECKING:
    from core.vain import Vain

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
                embed=panel_embed(
                    title="Embed Code",
                    color=color.base,
                    lines=[f"```{code}```"],
                    timestamp=False,
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
        """Export as vain tagscript: {embed}$v{title: …}$v{description: …}"""
        parts = ["{embed}"]
        if embed.title:
            parts.append(f"$v{{title: {embed.title}}}")
        if embed.description:
            parts.append(f"$v{{description: {embed.description}}}")
        if embed.color:
            parts.append(f"$v{{color: #{embed.color.value:06x}}}")
        if embed.url:
            parts.append(f"$v{{url: {embed.url}}}")
        if embed.author and embed.author.name:
            bits = [embed.author.name]
            if embed.author.icon_url:
                bits.append(embed.author.icon_url)
            elif embed.author.url:
                bits.append("")
            if embed.author.url:
                bits.append(embed.author.url)
            parts.append(f"$v{{author: {' && '.join(bits)}}}")
        if embed.footer and embed.footer.text:
            fbits = [embed.footer.text]
            if embed.footer.icon_url:
                fbits.append(embed.footer.icon_url)
            parts.append(f"$v{{footer: {' && '.join(fbits)}}}")
        if embed.timestamp:
            parts.append("$v{timestamp}")
        if embed.image and embed.image.url:
            parts.append(f"$v{{image: {embed.image.url}}}")
        if embed.thumbnail and embed.thumbnail.url:
            parts.append(f"$v{{thumbnail: {embed.thumbnail.url}}}")
        for field in embed.fields:
            tail = " && inline" if field.inline else ""
            parts.append(
                f"$v{{field: {field.name or 'Field'} && {field.value or '​'}{tail}}}"
            )
        return "".join(parts)
