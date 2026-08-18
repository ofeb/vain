from __future__ import annotations
from typing import TYPE_CHECKING, Any

import contextlib
import re

import discord
from discord import ui
from discord.ext import commands
from discord.ext.commands import hybrid_command, CommandError

from core.discord.package import Package
from core.discord.hybrid import hybrid, describe
from core.managers.permissions import has_permissions
from config import color

if TYPE_CHECKING:
    from core.vain import Vain


class _ModifyCodeView(discord.ui.View):
    def __init__(self, *, owner_id: int, kind: str, code: str):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.kind = kind  
        self.code = code
        label = "Modify container" if kind == "container" else "Modify embed"
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
        btn.callback = self._modify
        self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the person who ran the command can use this.", ephemeral=True)
            return False
        return True

    async def _modify(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            from ext.utility.improper.builders import EmbedBuilderView, ContainerBuilderView
        except Exception:
            try:
                from utility.improper.builders import EmbedBuilderView, ContainerBuilderView
            except Exception as exc:
                return await interaction.followup.send(f"Couldn't open builder\n> -# {exc}", ephemeral=True)

        accent = getattr(interaction.client, "color", None) or 0x2B2D31
        if self.kind == "container":
            builder = ContainerBuilderView(interaction.user.id, accent=int(accent))
        else:
            builder = EmbedBuilderView(interaction.user.id, accent=int(accent))

        
        try:
            _apply_script_to_builder(builder, self.code)
        except Exception:
            pass

        channel = interaction.channel
        try:
            preview_content, preview_layout = builder._preview_container() if self.kind == "container" else (None, None)
            if self.kind == "container":
                await builder._refresh_content_message(preview_content, channel)
                m = await channel.send(view=builder._controls())
                builder.message = m
                try:
                    preview = await channel.send(content=None, view=preview_layout)
                    builder.preview_message = preview
                except Exception:
                    builder.preview_message = None
            else:
                
                if hasattr(builder, "start"):
                    await builder.start(interaction)
                else:
                    m = await channel.send(view=builder)
                    builder.message = m
            await interaction.followup.send(
                f"Opened **{'container' if self.kind == 'container' else 'embed'} builder** with your code preloaded where possible.",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Couldn't open builder\n> -# {exc}", ephemeral=True)


def _apply_script_to_builder(builder: Any, code: str) -> None:
    """Parse common $v{key: value} chunks into builder.data when present."""
    data = getattr(builder, "data", None)
    if not isinstance(data, dict):
        return
    text = code or ""
    for m in re.finditer(r"\$v\{(\w+)\s*:\s*(.*?)\}", text, re.DOTALL):
        key = m.group(1).lower().strip()
        val = m.group(2).strip()
        if key in {"description", "desc"}:
            data["description"] = val
        elif key == "title":
            data["title"] = val
        elif key == "footer":
            if "text:" in val:
                
                parts = [p.strip() for p in val.split("&&")]
                for part in parts:
                    if part.lower().startswith("text:"):
                        data["footer"] = part.split(":", 1)[1].strip()
                    elif part.lower().startswith("icon:"):
                        data["footer_icon"] = part.split(":", 1)[1].strip()
            else:
                data["footer"] = val
        elif key == "color":
            data["color"] = val.lstrip("#")
        elif key == "image":
            data["image"] = val.split("&&")[0].strip()
        elif key == "thumbnail":
            data["thumbnail"] = val
        elif key == "author":
            parts = [p.strip() for p in val.split("&&")]
            for part in parts:
                low = part.lower()
                if low.startswith("name:"):
                    data["author"] = part.split(":", 1)[1].strip()
                elif low.startswith("icon:"):
                    data["author_icon"] = part.split(":", 1)[1].strip()
                elif low.startswith("url:"):
                    data["author_url"] = part.split(":", 1)[1].strip()
                elif ":" not in part and not data.get("author"):
                    data["author"] = part


class Embedcode(Package):
    """copy embed or container code from a message"""

    @hybrid(
        name="embedcode",
        aliases=["copyembed", "ec"],
        description="Copy the embed code (or container code) from a message",
        example=",embedcode (reply) or ,embedcode <message link/id>",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(message="Message link, id, or leave empty to use a reply")
    @has_permissions(manage_messages=True)
    async def embedcode(self, ctx, *, message: str = None):
        msg = await self._resolve_message(ctx, message)
        if msg is None:
            return await ctx.warn(
                "Reply to a message or pass a link / id\n"
                f"> -# **usage:** {ctx.cmd('embedcode')} (reply)"
            )

        kind = "embed"
        title = "Embed Code"
        if msg.embeds:
            code = self._embed_to_code(msg.embeds[0])
        else:
            layout = self._message_layout(msg)
            if layout is None:
                if (msg.content or "").strip():
                    code = f"{{embed}}$v{{description: {msg.content.strip()}}}"
                else:
                    return await ctx.warn("That message has no embeds, container, or text")
            else:
                code = self._container_to_code(layout)
                title = "Container Code"
                kind = "container"

        await self._deliver_code(ctx, title=title, code=code, kind=kind)

    @hybrid(
        name="containercode",
        aliases=["ccode", "containerc", "copycontainer"],
        description="Copy the container code (or embed code) from a message",
        example=",containercode (reply) or ,containercode <message link/id>",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(message="Message link, id, or leave empty to use a reply")
    @has_permissions(manage_messages=True)
    async def containercode(self, ctx, *, message: str = None):
        msg = await self._resolve_message(ctx, message)
        if msg is None:
            return await ctx.warn(
                "Reply to a message or pass a link / id\n"
                f"> -# **usage:** {ctx.cmd('containercode')} (reply)"
            )

        layout = self._message_layout(msg)
        if layout is not None:
            code = self._container_to_code(layout)
            title, kind = "Container Code", "container"
        elif msg.embeds:
            code = self._embed_to_code(msg.embeds[0])
            title, kind = "Embed Code", "embed"
        elif (msg.content or "").strip():
            code = f"{{container}}$v{{description: {msg.content.strip()}}}"
            title, kind = "Container Code", "container"
        else:
            return await ctx.warn("That message has no container, embeds, or text")

        await self._deliver_code(ctx, title=title, code=code, kind=kind)

    async def _deliver_code(self, ctx, *, title: str, code: str, kind: str) -> None:
        view = _ModifyCodeView(owner_id=ctx.author.id, kind=kind, code=code)
        try:
            await ctx.author.send(content=self._code_dm_embed(code))
            await ctx.success(f"{title} sent to your DMs!", view=view)
        except discord.Forbidden:
            
            preview = code if len(code) <= 1800 else code[:1800] + "…"
            await ctx.success(
                f"{title} (couldn't DM you — check privacy settings)\n```\n{preview}\n```",
                view=view,
            )

    async def _resolve_message(self, ctx, raw: str | None) -> discord.Message | None:
        
        if ctx.message and ctx.message.reference:
            ref = ctx.message.reference.resolved
            if isinstance(ref, discord.Message):
                return ref
            mid = ctx.message.reference.message_id
            if mid:
                with contextlib.suppress(Exception):
                    return await ctx.channel.fetch_message(mid)

        if not raw or not str(raw).strip():
            return None

        text = str(raw).strip()
        
        msg = await self._fetch_message(ctx, text)
        if msg is not None:
            return msg
        
        if text.isdigit():
            with contextlib.suppress(Exception):
                return await ctx.channel.fetch_message(int(text))
        return None


    def _code_dm_embed(self, code: str) -> str:
        """Copy-friendly plain-text script in a fenced code block."""
        return f"`{code}`"

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
            parts.append(f"$v{{title: {self._clean_script_text(embed.title)}}}")
        if embed.description:
            parts.append(f"$v{{description: {self._clean_script_text(embed.description)}}}")
        if embed.color:
            parts.append(f"$v{{color: #{embed.color.value:06x}}}")
        if embed.url:
            parts.append(f"$v{{url: {embed.url}}}")
        if embed.author and embed.author.name:
            bits = [self._clean_script_text(embed.author.name)]
            if embed.author.icon_url:
                bits.append(embed.author.icon_url)
            elif embed.author.url:
                bits.append("")
            if embed.author.url:
                bits.append(embed.author.url)
            parts.append(f"$v{{author: {' && '.join(bits)}}}")
        if embed.footer and embed.footer.text:
            fbits = [self._clean_script_text(embed.footer.text)]
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
                "$v{field: "
                f"{self._clean_script_text(field.name or 'Field')} && "
                f"{self._clean_script_text(field.value or '​')}{tail}"
                "}"
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
            children = list(getattr(container, "children", []) or [])
            for index, item in enumerate(children):
                if isinstance(item, ui.Separator) and self._next_item_is_button(
                    children, index
                ):
                    continue
                self._container_item_to_code(parts, item)
        return "".join(parts)

    @staticmethod
    def _next_item_is_button(items: list, index: int) -> bool:
        """True when the separator directly precedes a button row.

        The parser auto-inserts a separator before buttons, so emitting one
        here produces a duplicate on round-trip.
        """
        siblings = items[index + 1 :]
        if not siblings:
            return False
        nxt = siblings[0]
        if isinstance(nxt, ui.Button):
            return True
        if isinstance(nxt, ui.ActionRow):
            return any(
                isinstance(child, ui.Button)
                for child in (getattr(nxt, "children", []) or [])
            )
        return False

    def _container_item_to_code(self, parts: list[str], item: Any) -> None:
        if isinstance(item, ui.TextDisplay):
            text = self._clean_script_text(getattr(item, "content", "") or "").strip()
            if text.startswith("## "):
                parts.append(f"$v{{title: {text[3:].strip()}}}")
            elif text.startswith("> -# ") and "\\n" not in text:
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
            body = self._clean_script_text(
                "".join(
                    str(getattr(c, "content", "") or "")
                    for c in (getattr(item, "children", []) or [])
                    if isinstance(c, ui.TextDisplay)
                )
            ).strip()
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
    def _clean_script_text(text: Any) -> str:
        """Normalise a fetched text block into script payload form.

        Preserves blockquote (``> ``) and subtext (``-# ``) prefixes so the
        generated script round-trips into the exact same rendered layout.
        """
        lines: list[str] = []
        for raw in str(text or "").splitlines():
            lines.append(raw.rstrip())
        return "\\n".join(lines).rstrip("\\n")

    @staticmethod
    def _button_style_name(style: Any) -> str:
        return {
            discord.ButtonStyle.link: "url",
            discord.ButtonStyle.primary: "blue",
            discord.ButtonStyle.success: "green",
            discord.ButtonStyle.secondary: "grey",
            discord.ButtonStyle.danger: "red",
        }.get(style, "grey")
