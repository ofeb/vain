from __future__ import annotations
from typing import TYPE_CHECKING, Any

import contextlib
import re

import discord
from discord import ui
from discord.ext.commands import hybrid_command, CommandError

from core.discord.package import Package
from core.discord.hybrid import describe
from core.managers.permissions import has_permissions
from config import color, emojis

from core.discord.views.embed import panel_embed

if TYPE_CHECKING:
    from core.vain import Vain


class Embedcode(Package):
    """copy embed or container code from a message"""

    @hybrid_command(
        name="embedcode",
        aliases=["copyembed", "ec"],
        description="Copy the embed code (or container code) from a message",
        example=",embedcode https://discord.com/channels/123/456/789",
        guild_only=True,
    )
    @describe(message="Message link to copy from")
    @has_permissions(manage_messages=True)
    async def embedcode(self, ctx, *, message: str):
        """copy embed code (or container code) from a message"""
        msg = await self._fetch_message(ctx, message)
        if msg is None:
            return

        if msg.embeds:
            code = self._embed_to_code(msg.embeds[0])
            title = "Embed Code"
        else:
            layout = self._message_layout(msg)
            if layout is None:
                return await ctx.warn("That message has no embeds or container code")
            code = self._container_to_code(layout)
            title = "Container Code"

        if len(code) > 2000:
            return await ctx.warn("Code is too long to send. Check your DMs.")

        try:
            await ctx.author.send(
                embed=panel_embed(
                    title=title,
                    color=color.base,
                    lines=[f"```{code}```"],
                    timestamp=False,
                )
            )
            await ctx.success(f"{title} sent to your DMs!")
        except discord.Forbidden:
            await ctx.warn("Could not DM you. Check your privacy settings.")

    @hybrid_command(
        name="containercode",
        aliases=["ccode", "containerc", "copycontainer"],
        description="Copy the container code (or embed code) from a message",
        example=",containercode https://discord.com/channels/123/456/789",
        guild_only=True,
    )
    @describe(message="Message link to copy from")
    @has_permissions(manage_messages=True)
    async def containercode(self, ctx, *, message: str):
        """copy container code (or embed code) from a message"""
        msg = await self._fetch_message(ctx, message)
        if msg is None:
            return

        layout = self._message_layout(msg)
        if layout is not None:
            code = self._container_to_code(layout)
            title = "Container Code"
        elif msg.embeds:
            code = self._embed_to_code(msg.embeds[0])
            title = "Embed Code"
        else:
            return await ctx.warn("That message has no container code or embeds")

        if len(code) > 2000:
            return await ctx.warn("Code is too long to send. Check your DMs.")

        try:
            await ctx.author.send(
                embed=panel_embed(
                    title=title,
                    color=color.base,
                    lines=[f"```{code}```"],
                    timestamp=False,
                )
            )
            await ctx.success(f"{title} sent to your DMs!")
        except discord.Forbidden:
            await ctx.warn("Could not DM you. Check your privacy settings.")

    async def _fetch_message(self, ctx, link: str) -> discord.Message | None:
        try:
            channel_id, message_id = self._parse_message_link(link)
        except CommandError as error:
            await ctx.warn(str(error))
            return None

        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            await ctx.fail("Could not find that channel")
            return None

        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound:
            await ctx.fail("Message not found")
        except discord.HTTPException:
            await ctx.fail("Could not fetch message")
        return None

    def _message_layout(self, msg: discord.Message) -> Any | None:
        """Reconstruct a LayoutView from a fetched message, or None."""
        with contextlib.suppress(Exception):
            view = ui.LayoutView.from_message(msg)
            if isinstance(view, ui.LayoutView) and getattr(view, "children", None):
                return view
        return None

    def _parse_message_link(self, link: str) -> tuple[int, int]:
        pattern = r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
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

    def _container_to_code(self, layout: Any) -> str:
        """Export a LayoutView back to a {container} script."""
        parts: list[str] = ["{container}"]
        containers = [
            child
            for child in (getattr(layout, "children", []) or [])
            if isinstance(child, ui.Container)
        ]
        if not containers:
            containers = [layout]

        for container in containers:
            accent = getattr(container, "accent_colour", None)
            if accent is not None:
                with contextlib.suppress(Exception):
                    parts.append(f"$v{{color: #{int(accent) & 0xFFFFFF:06x}}}")
            for item in list(getattr(container, "children", []) or []):
                self._container_item_to_code(parts, item)
        return "".join(parts)

    def _container_item_to_code(self, parts: list[str], item: Any) -> None:
        if isinstance(item, ui.TextDisplay):
            text = str(getattr(item, "content", "") or "").rstrip("\n")
            if text.startswith("## "):
                parts.append(f"$v{{title: {text[3:].strip()}}}")
            elif text.startswith("-# ") and "\n" not in text:
                parts.append(f"$v{{footer: {text[3:].strip()}}}")
            elif text:
                parts.append(f"$v{{description: {text}}}")
            return

        if isinstance(item, ui.Separator):
            visible = bool(getattr(item, "visible", True))
            spacing = getattr(item, "spacing", None)
            spacing_code = "1"
            if spacing is not None:
                raw = getattr(spacing, "value", spacing)
                try:
                    if int(raw) == 2:
                        spacing_code = "2"
                except (TypeError, ValueError):
                    if str(spacing).lower() in {"large", "2", "lg"}:
                        spacing_code = "2"
            parts.append(
                f"$v{{separator: divider: {str(visible).lower()} && spacing: {spacing_code}}}"
            )
            return

        if isinstance(item, ui.Button):
            parts.append(self._button_to_code(item))
            return

        if isinstance(item, ui.ActionRow):
            for child in list(getattr(item, "children", []) or []):
                self._container_item_to_code(parts, child)
            return

        if isinstance(item, ui.Section):
            body = "".join(
                str(getattr(c, "content", "") or "")
                for c in (getattr(item, "children", []) or [])
                if isinstance(c, ui.TextDisplay)
            ).rstrip("\n")
            accessory = getattr(item, "accessory", None)
            if isinstance(accessory, ui.MediaGallery):
                urls = [
                    getattr(getattr(i, "media", None), "url", None)
                    or getattr(i, "url", None)
                    for i in (getattr(accessory, "items", []) or [])
                ]
                urls = [u for u in urls if u]
                if body:
                    parts.append(f"$v{{description: {body}}}")
                if urls:
                    parts.append(f"$v{{image: {' && '.join(urls)}}}")
            elif isinstance(accessory, ui.Thumbnail):
                url = getattr(getattr(accessory, "media", None), "url", None)
                if body:
                    parts.append(f"$v{{description: {body}}}")
                if url:
                    parts.append(f"$v{{thumbnail: {url}}}")
            elif body:
                parts.append(f"$v{{description: {body}}}")
            return

        if isinstance(item, ui.MediaGallery):
            urls = [
                getattr(getattr(i, "media", None), "url", None)
                or getattr(i, "url", None)
                for i in (getattr(item, "items", []) or [])
            ]
            urls = [u for u in urls if u]
            if urls:
                parts.append(f"$v{{image: {' && '.join(urls)}}}")
            return

        if isinstance(item, ui.Thumbnail):
            url = getattr(getattr(item, "media", None), "url", None)
            if url:
                parts.append(f"$v{{thumbnail: {url}}}")
            return

    def _button_to_code(self, button: Any) -> str:
        style = self._button_style_name(getattr(button, "style", None))
        label = str(getattr(button, "label", None) or "").strip()
        emoji = getattr(button, "emoji", None)
        url = getattr(button, "url", None)
        disabled = bool(getattr(button, "disabled", False))

        bits: list[str] = []
        if label:
            bits.append(f"label: {label}")
        if emoji is not None:
            bits.append(f"emoji: {emoji}")
        if style == "url" and url:
            bits.append(f"url: {url}")
        else:
            bits.append(f"style: {style}")
        if disabled and style != "url":
            bits.append("disabled: true")
        return f"$v{{button: {' && '.join(bits)}}}"

    @staticmethod
    def _button_style_name(style: Any) -> str:
        return {
            discord.ButtonStyle.link: "url",
            discord.ButtonStyle.primary: "blue",
            discord.ButtonStyle.success: "green",
            discord.ButtonStyle.secondary: "grey",
            discord.ButtonStyle.danger: "red",
        }.get(style, "grey")
