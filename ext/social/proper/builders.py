"""Interactive embed (eb) and container (cb) builders with live previews.

Embed builder  → classic Discord embeds + link/styled buttons
Container builder → Components V2 LayoutView (TextDisplay, Section+Thumbnail,
                    MediaGallery, Separator, ActionRow buttons)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import ui

from core.discord.ctx import Context
from core.discord.hybrid import hybrid

if TYPE_CHECKING:
    from core.vain import Vain

_MAX_BUILDER_BUTTONS = 25
_MAX_FIELDS = 25
_BUTTON_STYLE_NOTE = "url · blurple · green · red · grey"
_HEADER_EB = (
    "**Embed Builder** · live preview below\n"
    "-# Pick a field → modal → preview updates. **Approve** DMs you the script."
)
_HEADER_CB = (
    "**Container Builder** · live Components V2 preview below\n"
    "-# Pick a field → modal → preview updates. **Approve** DMs you the script."
)


def _normalize_btn_style(raw: str | None) -> str:
    s = (raw or "url").strip().lower()
    if s in {"url", "link", "u"}:
        return "url"
    if s in {"blurple", "blue", "primary", "blurp"}:
        return "blurple"
    if s in {"green", "success", "g"}:
        return "green"
    if s in {"red", "danger", "r"}:
        return "red"
    if s in {"grey", "gray", "secondary"}:
        return "grey"
    return "url"


def _discord_btn_style(name: str) -> discord.ButtonStyle:
    return {
        "url": discord.ButtonStyle.link,
        "blurple": discord.ButtonStyle.primary,
        "green": discord.ButtonStyle.success,
        "red": discord.ButtonStyle.danger,
        "grey": discord.ButtonStyle.secondary,
    }.get(_normalize_btn_style(name), discord.ButtonStyle.link)


def _button_script_chunk(btn: dict[str, str]) -> str:
    style = _normalize_btn_style(btn.get("style"))
    label = (btn.get("label") or "Button").strip() or "Button"
    url = (btn.get("url") or "").strip()
    emoji = (btn.get("emoji") or "").strip()
    if style == "url":
        target = url or "https://discord.com"
        bit = f"$v{{button: {target} && {label}"
        if emoji:
            bit += f" && {emoji}"
        return bit + "}"
    target = emoji or url or "✨"
    return f"$v{{button: {style} && {label} && {target}}}"


def _make_preview_button(btn: dict[str, str], *, index: int) -> discord.ui.Button:
    style_name = _normalize_btn_style(btn.get("style"))
    label = ((btn.get("label") or "Button").strip() or "Button")[:80]
    url = (btn.get("url") or "").strip()
    emoji = (btn.get("emoji") or "").strip() or None
    style = _discord_btn_style(style_name)
    if style == discord.ButtonStyle.link:
        href = (
            url
            if url.startswith(("http://", "https://"))
            else (f"https://{url}" if url else "https://discord.com")
        )
        return discord.ui.Button(
            style=discord.ButtonStyle.link,
            label=label,
            url=href,
            emoji=emoji,
        )
    return discord.ui.Button(
        style=style,
        label=label,
        emoji=emoji,
        disabled=True,
        custom_id=f"builder:preview:{index}",
    )


def _strip_subtext(text: str) -> str:
    cleaned = str(text or "").strip()
    while cleaned.startswith("-#"):
        cleaned = cleaned[2:].lstrip()
    return cleaned


class _BuilderModal(discord.ui.Modal):
    """Multi-field modal used by both builders."""

    def __init__(
        self,
        title: str,
        fields: list[tuple[str, str, bool, int, str]],
    ):
        
        super().__init__(title=title[:45])
        self.keys: list[str] = []
        self.values: dict[str, str] = {}
        self._submitted = False
        for key, label, paragraph, maxlen, default in fields[:5]:
            self.keys.append(key)
            item = discord.ui.TextInput(
                label=label[:45],
                style=(
                    discord.TextStyle.paragraph
                    if paragraph
                    else discord.TextStyle.short
                ),
                required=False,
                max_length=min(int(maxlen), 4000),
                default=(default or "")[: min(int(maxlen), 4000)] or None,
            )
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        for key, child in zip(self.keys, self.children):
            if isinstance(child, discord.ui.TextInput):
                self.values[key] = child.value or ""
        self._submitted = True
        if not interaction.response.is_done():
            await interaction.response.defer()


class _BuilderControls(discord.ui.View):
    """Select + Approve/Cancel. Preview buttons live on a separate message."""

    def __init__(
        self,
        owner: "_BaseBuilder",
        *,
        field_options: list[discord.SelectOption],
    ):
        super().__init__(timeout=600)
        self.owner = owner

        select = discord.ui.Select(
            placeholder="Choose what to edit...",
            min_values=1,
            max_values=1,
            options=field_options[:25],
            row=0,
            custom_id="builder:field",
        )
        select.callback = self._on_select
        self.add_item(select)

        approve = discord.ui.Button(
            label="Approve & DM Script",
            style=discord.ButtonStyle.success,
            row=1,
            custom_id="builder:approve",
        )
        cancel = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            row=1,
            custom_id="builder:cancel",
        )
        approve.callback = self._on_approve
        cancel.callback = self._on_cancel
        self.add_item(approve)
        self.add_item(cancel)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user and inter.user.id == self.owner.author_id:
            return True
        if not inter.response.is_done():
            await inter.response.send_message(
                f"Only <@{self.owner.author_id}> can use this.",
                ephemeral=True,
            )
        return False

    async def _on_select(self, inter: discord.Interaction) -> None:
        data = inter.data or {}
        values = list(data.get("values") or []) if isinstance(data, dict) else []
        key = values[0] if values else ""
        if key:
            await self.owner.handle_field(inter, key)

    async def _on_approve(self, inter: discord.Interaction) -> None:
        await self.owner.handle_approve(inter)

    async def _on_cancel(self, inter: discord.Interaction) -> None:
        await self.owner.handle_cancel(inter)

    async def on_timeout(self) -> None:
        await self.owner.handle_timeout()


class _BaseBuilder:
    """Shared state for embed / container builders."""

    kind: str = "embed"
    header: str = ""

    def __init__(self, author_id: int, accent: int | None = None):
        self.author_id = author_id
        self.data: dict[str, str] = {
            "content": "",
            "title": "",
            "description": "",
            "color": f"{(accent if accent is not None else 0x2B2D31):06x}",
            "author": "",
            "author_icon": "",
            "author_url": "",
            "footer": "",
            "footer_icon": "",
            "footer_timestamp": "0",
            "image": "",
            "thumbnail": "",
            "url": "",
            "divider": "0",
        }
        self.fields: list[dict[str, str]] = []  
        self.buttons: list[dict[str, str]] = []
        self.message: discord.Message | None = None
        self.preview_message: discord.Message | None = None
        self._stopped = False

    
    
    

    def _accent(self) -> int:
        raw = (self.data.get("color") or "2b2d31").lstrip("#")
        try:
            return int(raw, 16) & 0xFFFFFF
        except ValueError:
            return 0x2B2D31

    def _truthy(self, key: str) -> bool:
        return (self.data.get(key) or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "y",
            "enable",
        }

    def _field_options(self) -> list[discord.SelectOption]:
        opts: list[discord.SelectOption] = [
            discord.SelectOption(
                label="Content (message text)",
                value="content",
                description="Plain text above the embed/container",
            ),
            discord.SelectOption(label="Title", value="title"),
            discord.SelectOption(label="Description", value="description"),
            discord.SelectOption(label="Color (hex)", value="color"),
            discord.SelectOption(
                label="Author",
                value="author",
                description="name · icon url · url",
            ),
            discord.SelectOption(
                label="Footer",
                value="footer",
                description="text · icon · timestamp yes/no",
            ),
            discord.SelectOption(label="Image URL", value="image"),
            discord.SelectOption(label="Thumbnail URL", value="thumbnail"),
        ]
        if self.kind == "embed":
            opts.append(
                discord.SelectOption(
                    label="Embed URL (title link)",
                    value="url",
                    description="Clickable title URL",
                )
            )
            opts.append(
                discord.SelectOption(
                    label=f"Add Field ({len(self.fields)}/{_MAX_FIELDS})",
                    value="field",
                    description="name · value · inline yes/no",
                )
            )
            if self.fields:
                opts.append(
                    discord.SelectOption(
                        label="Remove last field",
                        value="field_remove",
                    )
                )
                opts.append(
                    discord.SelectOption(
                        label="Clear all fields",
                        value="field_clear",
                    )
                )
        else:
            opts.append(
                discord.SelectOption(
                    label="Divider / Separator",
                    value="divider",
                    description="Toggle a separator line",
                )
            )
            opts.append(
                discord.SelectOption(
                    label=f"Add Field-like block ({len(self.fields)}/{_MAX_FIELDS})",
                    value="field",
                    description="bold name + value text block",
                )
            )
            if self.fields:
                opts.append(
                    discord.SelectOption(
                        label="Remove last field block",
                        value="field_remove",
                    )
                )
            opts.append(
                discord.SelectOption(
                    label="New Action Row break",
                    value="actionrow",
                    description="Start a fresh button row in the script",
                )
            )

        n = len(self.buttons)
        opts.append(
            discord.SelectOption(
                label=f"Add Button ({n}/{_MAX_BUILDER_BUTTONS})",
                value="button",
                description=_BUTTON_STYLE_NOTE,
            )
        )
        if n:
            opts.append(
                discord.SelectOption(
                    label="Remove last button",
                    value="button_remove",
                    description=f"{n} button(s) attached",
                )
            )
            opts.append(
                discord.SelectOption(
                    label="Clear all buttons",
                    value="button_clear",
                )
            )
        return opts[:25]

    def _controls(self) -> _BuilderControls:
        return _BuilderControls(self, field_options=self._field_options())

    
    
    

    def _to_script(self) -> str:
        mode = "{embed}" if self.kind == "embed" else "{container}"
        parts = [mode]
        if self.data.get("content"):
            parts.append(f"$v{{content: {self.data['content']}}}")
        if self.data.get("title"):
            parts.append(f"$v{{title: {self.data['title']}}}")
        if self.data.get("description"):
            parts.append(f"$v{{description: {self.data['description']}}}")
        if self.data.get("color"):
            parts.append(f"$v{{color: #{self.data['color'].lstrip('#')}}}")
        if self.data.get("url") and self.kind == "embed":
            parts.append(f"$v{{url: {self.data['url']}}}")
        if self.data.get("author"):
            bits = [self.data["author"]]
            if self.data.get("author_icon"):
                bits.append(self.data["author_icon"])
            elif self.data.get("author_url"):
                bits.append("")  
            if self.data.get("author_url"):
                bits.append(self.data["author_url"])
            parts.append(f"$v{{author: {' && '.join(bits)}}}")
        if self.data.get("footer"):
            fbits = [self.data["footer"]]
            if self.data.get("footer_icon"):
                fbits.append(self.data["footer_icon"])
            parts.append(f"$v{{footer: {' && '.join(fbits)}}}")
        if self._truthy("footer_timestamp"):
            parts.append("$v{timestamp}")
        if self.kind == "container" and self._truthy("divider"):
            parts.append("$v{divider}")
        if self.data.get("image"):
            parts.append(f"$v{{image: {self.data['image']}}}")
        if self.data.get("thumbnail"):
            parts.append(f"$v{{thumbnail: {self.data['thumbnail']}}}")
        for field in self.fields[:_MAX_FIELDS]:
            name = field.get("name") or "Field"
            value = field.get("value") or "​"
            inline = field.get("inline") == "1"
            if self.kind == "embed":
                tail = " && inline" if inline else ""
                parts.append(f"$v{{field: {name} && {value}{tail}}}")
            else:
                parts.append(f"$v{{field: {name} && {value}}}")
        
        for i, btn in enumerate(self.buttons[:_MAX_BUILDER_BUTTONS]):
            if self.kind == "container" and i > 0 and i % 5 == 0:
                parts.append("$v{actionrow}")
            parts.append(_button_script_chunk(btn))
        if len(parts) == 1:
            return f"{mode}$v{{description: }}"
        return "".join(parts)

    
    
    

    def _preview_embed(self) -> discord.Embed:
        emb = discord.Embed(
            title=self.data.get("title") or None,
            description=self.data.get("description") or None,
            color=self._accent(),
            url=(self.data.get("url") or None) or None,
        )
        if self.data.get("author"):
            kwargs: dict[str, Any] = {"name": self.data["author"]}
            if self.data.get("author_icon"):
                kwargs["icon_url"] = self.data["author_icon"]
            if self.data.get("author_url"):
                kwargs["url"] = self.data["author_url"]
            try:
                emb.set_author(**kwargs)
            except Exception:
                emb.set_author(name=self.data["author"])
        if self.data.get("footer"):
            try:
                if self.data.get("footer_icon"):
                    emb.set_footer(
                        text=self.data["footer"],
                        icon_url=self.data["footer_icon"],
                    )
                else:
                    emb.set_footer(text=self.data["footer"])
            except Exception:
                emb.set_footer(text=self.data["footer"])
        if self._truthy("footer_timestamp"):
            emb.timestamp = discord.utils.utcnow()
        if self.data.get("image"):
            try:
                emb.set_image(url=self.data["image"])
            except Exception:
                pass
        if self.data.get("thumbnail"):
            try:
                emb.set_thumbnail(url=self.data["thumbnail"])
            except Exception:
                pass
        for field in self.fields[:_MAX_FIELDS]:
            try:
                emb.add_field(
                    name=(field.get("name") or "Field")[:256],
                    value=(field.get("value") or "​")[:1024],
                    inline=field.get("inline") == "1",
                )
            except Exception:
                pass
        has_any = any(
            (
                emb.title,
                emb.description,
                emb.fields,
                self.data.get("author"),
                self.data.get("footer"),
                self.data.get("image"),
                self.data.get("thumbnail"),
                self.buttons,
                self.data.get("content"),
            )
        )
        if not has_any or (not emb.title and not emb.description and not emb.fields):
            if not emb.description:
                emb.description = "​"
        return emb

    def _preview_container(self) -> ui.LayoutView:
        layout = ui.LayoutView(timeout=None)
        container = ui.Container()

        lines: list[str] = []
        if self.data.get("author"):
            lines.append(f"**{self.data['author']}**")
        if self.data.get("title"):
            lines.append(f"## {self.data['title']}")
        if self.data.get("description"):
            lines.append(self.data["description"])
        for field in self.fields[:_MAX_FIELDS]:
            name = field.get("name") or "Field"
            value = field.get("value") or "​"
            lines.append(f"**{name}**\n{value}")
        if self.data.get("footer"):
            foot = _strip_subtext(self.data["footer"])
            if self._truthy("footer_timestamp"):
                now = discord.utils.utcnow()
                foot = f"{foot} · Today at {now.strftime('%H:%M')}" if foot else f"Today at {now.strftime('%H:%M')}"
            if foot:
                lines.append(f"-# {foot}")
        elif self._truthy("footer_timestamp"):
            now = discord.utils.utcnow()
            lines.append(f"-# Today at {now.strftime('%H:%M')}")

        body = "\n".join(lines) if lines else "​"
        accessory = (
            (self.data.get("thumbnail") or "").strip()
            or (self.data.get("author_icon") or "").strip()
        )
        if accessory.startswith("http"):
            try:
                container.add_item(
                    ui.Section(
                        ui.TextDisplay(body),
                        accessory=ui.Thumbnail(media=accessory),
                    )
                )
            except Exception:
                container.add_item(ui.TextDisplay(body))
        else:
            container.add_item(ui.TextDisplay(body))

        if self._truthy("divider"):
            try:
                container.add_item(ui.Separator(visible=True))
            except Exception:
                pass

        image = (self.data.get("image") or "").strip()
        if image.startswith("http"):
            try:
                gallery = ui.MediaGallery()
                gallery.add_item(media=image)
                container.add_item(gallery)
            except Exception:
                try:
                    container.add_item(ui.MediaGallery(discord.MediaGalleryItem(image)))
                except Exception:
                    pass

        if self.buttons:
            try:
                container.add_item(ui.Separator(visible=True))
            except Exception:
                pass
            for i in range(0, min(len(self.buttons), _MAX_BUILDER_BUTTONS), 5):
                row = ui.ActionRow()
                for j, btn in enumerate(self.buttons[i : i + 5]):
                    try:
                        row.add_item(_make_preview_button(btn, index=i + j))
                    except Exception:
                        pass
                if getattr(row, "children", None):
                    try:
                        container.add_item(row)
                    except Exception:
                        pass

        layout.add_item(container)
        return layout

    async def refresh(self) -> None:
        if self._stopped or not self.message:
            return
        content_prefix = ""
        if self.data.get("content"):
            content_prefix = f"{self.data['content']}\n\n"
        try:
            if self.kind == "embed":
                await self.message.edit(
                    content=f"{content_prefix}{self.header}",
                    embed=self._preview_embed(),
                    view=self._controls(),
                )
            else:
                await self.message.edit(
                    content=f"{content_prefix}{self.header}",
                    view=self._controls(),
                )
                if self.preview_message is not None:
                    try:
                        await self.preview_message.edit(
                            content=None,
                            view=self._preview_container(),
                        )
                    except Exception:
                        pass
        except Exception:
            pass

    
    
    

    async def _run_modal(
        self,
        inter: discord.Interaction,
        title: str,
        fields: list[tuple[str, str, bool, int, str]],
    ) -> dict[str, str] | None:
        modal = _BuilderModal(title, fields)
        await inter.response.send_modal(modal)
        timed_out = await modal.wait()
        if timed_out and not modal._submitted:
            return None
        return modal.values or None

    async def handle_field(self, inter: discord.Interaction, key: str) -> None:
        if key == "button":
            if len(self.buttons) >= _MAX_BUILDER_BUTTONS:
                await inter.response.send_message(
                    f"Max **{_MAX_BUILDER_BUTTONS}** buttons.",
                    ephemeral=True,
                )
                return
            values = await self._run_modal(
                inter,
                f"Add Button ({len(self.buttons) + 1}/{_MAX_BUILDER_BUTTONS})",
                [
                    ("label", "Label", False, 80, ""),
                    ("url", "URL (for style url)", False, 500, ""),
                    ("emoji", "Emoji (optional)", False, 100, ""),
                    ("style", "Style: url blurple green red grey", False, 20, "url"),
                ],
            )
            if not values:
                return
            label = (values.get("label") or "").strip() or "Button"
            url = (values.get("url") or "").strip()
            emoji = (values.get("emoji") or "").strip()
            style = _normalize_btn_style(values.get("style") or "url")
            if style == "url" and not url:
                url = "https://discord.com"
            self.buttons.append(
                {"label": label, "url": url, "emoji": emoji, "style": style}
            )
            await self.refresh()
            return

        if key == "button_remove":
            if self.buttons:
                self.buttons.pop()
            if not inter.response.is_done():
                await inter.response.defer()
            await self.refresh()
            return

        if key == "button_clear":
            self.buttons.clear()
            if not inter.response.is_done():
                await inter.response.defer()
            await self.refresh()
            return

        if key == "field":
            if len(self.fields) >= _MAX_FIELDS:
                await inter.response.send_message(
                    f"Max **{_MAX_FIELDS}** fields.",
                    ephemeral=True,
                )
                return
            values = await self._run_modal(
                inter,
                f"Add Field ({len(self.fields) + 1}/{_MAX_FIELDS})",
                [
                    ("name", "Field name", False, 256, ""),
                    ("value", "Field value", True, 1024, ""),
                    ("inline", "Inline? yes/no (embed only)", False, 10, "no"),
                ],
            )
            if not values:
                return
            name = (values.get("name") or "").strip() or "Field"
            value = (values.get("value") or "").strip() or "​"
            inline_raw = (values.get("inline") or "").lower().strip()
            inline = "1" if inline_raw in {"yes", "y", "true", "1", "on", "inline"} else "0"
            self.fields.append({"name": name, "value": value, "inline": inline})
            await self.refresh()
            return

        if key == "field_remove":
            if self.fields:
                self.fields.pop()
            if not inter.response.is_done():
                await inter.response.defer()
            await self.refresh()
            return

        if key == "field_clear":
            self.fields.clear()
            if not inter.response.is_done():
                await inter.response.defer()
            await self.refresh()
            return

        if key == "actionrow":
            
            
            
            if not inter.response.is_done():
                await inter.response.send_message(
                    "Next buttons will start a **new action row** in the script "
                    "(every 5 buttons also auto-break).",
                    ephemeral=True,
                )
            return

        if key == "divider":
            values = await self._run_modal(
                inter,
                "Divider / Separator",
                [("divider", "on or off", False, 10, "on" if self._truthy("divider") else "off")],
            )
            if values:
                val = (values.get("divider") or "").lower().strip()
                self.data["divider"] = (
                    "1" if val in {"on", "yes", "true", "1", "enable"} else "0"
                )
            await self.refresh()
            return

        if key == "author":
            values = await self._run_modal(
                inter,
                "Author",
                [
                    ("author", "Name", False, 256, self.data.get("author") or ""),
                    ("author_icon", "Icon URL", False, 500, self.data.get("author_icon") or ""),
                    ("author_url", "URL", False, 500, self.data.get("author_url") or ""),
                ],
            )
            if values:
                for k in ("author", "author_icon", "author_url"):
                    if k in values:
                        self.data[k] = (values[k] or "").strip()
            await self.refresh()
            return

        if key == "footer":
            values = await self._run_modal(
                inter,
                "Footer",
                [
                    ("footer", "Text", True, 2048, self.data.get("footer") or ""),
                    ("footer_icon", "Icon URL", False, 500, self.data.get("footer_icon") or ""),
                    (
                        "footer_timestamp",
                        "Timestamp yes/no",
                        False,
                        10,
                        "yes" if self._truthy("footer_timestamp") else "no",
                    ),
                ],
            )
            if values:
                if "footer" in values:
                    self.data["footer"] = _strip_subtext(values.get("footer") or "")
                if "footer_icon" in values:
                    self.data["footer_icon"] = (values.get("footer_icon") or "").strip()
                ts = (values.get("footer_timestamp") or "").lower().strip()
                self.data["footer_timestamp"] = (
                    "1" if ts in {"on", "yes", "true", "1", "y"} else "0"
                )
            await self.refresh()
            return

        labels = {
            "content": ("Content / message text", True, 2000),
            "title": ("Title", False, 256),
            "description": ("Description", True, 4000),
            "color": ("Color hex (e.g. 5865F2)", False, 20),
            "image": ("Image URL", False, 500),
            "thumbnail": ("Thumbnail URL", False, 500),
            "url": ("Title URL", False, 500),
        }
        if key not in labels:
            if not inter.response.is_done():
                await inter.response.send_message("Unknown field.", ephemeral=True)
            return
        label, paragraph, maxlen = labels[key]
        values = await self._run_modal(
            inter,
            f"Edit {label}",
            [(key, label, paragraph, maxlen, self.data.get(key) or "")],
        )
        if values and key in values:
            self.data[key] = (values[key] or "").strip()
            if key == "color":
                self.data[key] = self.data[key].lstrip("#")
        await self.refresh()

    async def handle_approve(self, inter: discord.Interaction) -> None:
        script = self._to_script()
        dm_ok = False
        try:
            await inter.user.send(f"`{script}`")
            dm_ok = True
        except Exception:
            pass
        if not inter.response.is_done():
            if dm_ok:
                await inter.response.send_message(
                    "Script sent to your **DMs**. Live preview stays above.",
                    ephemeral=True,
                )
            else:
                
                chunk = script[:1800]
                await inter.response.send_message(
                    f"Could not DM you — script:\n```\n{chunk}\n```",
                    ephemeral=True,
                )
        self._stopped = True
        try:
            self.stop_controls()
        except Exception:
            pass

    def stop_controls(self) -> None:
        if self.message and self.message.components is not None:
            pass

    async def handle_cancel(self, inter: discord.Interaction) -> None:
        self._stopped = True
        name = "Embed" if self.kind == "embed" else "Container"
        try:
            if not inter.response.is_done():
                await inter.response.edit_message(
                    content=f"{name} builder cancelled.",
                    embed=None,
                    view=None,
                )
        except Exception:
            pass
        if self.preview_message is not None:
            try:
                await self.preview_message.delete()
            except Exception:
                pass

    async def handle_timeout(self) -> None:
        self._stopped = True
        if self.message:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass


class EmbedBuilderView(_BaseBuilder):
    kind = "embed"
    header = ""


class ContainerBuilderView(_BaseBuilder):
    kind = "container"
    header = ""


async def register_builders(bot: "Vain") -> None:
    """Register ,embedbuilder / ,containerbuilder hybrid commands on the bot."""

    @hybrid(
        name="embedbuilder",
        aliases=["eb"],
        description="Interactive embed builder with live preview. Approve DMs the script.",
        example=",embedbuilder",
    )
    async def _run_eb(ctx: Context):
        accent = getattr(ctx.bot, "color", None) or 0x2B2D31
        builder = EmbedBuilderView(ctx.author.id, accent=int(accent))
        m = await ctx.send(
            content=builder.header,
            embed=builder._preview_embed(),
            view=builder._controls(),
            raw_embed=True,
        )
        builder.message = m

    @hybrid(
        name="containerbuilder",
        aliases=["cb"],
        description="Interactive Components V2 container builder with live preview. Approve DMs the script.",
        example=",containerbuilder",
    )
    async def _run_cb(ctx: Context):
        accent = getattr(ctx.bot, "color", None) or 0x2B2D31
        builder = ContainerBuilderView(ctx.author.id, accent=int(accent))
        m = await ctx.send(
            content=builder.header,
            view=builder._controls(),
        )
        builder.message = m
        try:
            preview = await ctx.send(view=builder._preview_container())
            builder.preview_message = preview
        except Exception:
            builder.preview_message = None

    
    for name in ("embedbuilder", "containerbuilder", "eb", "cb"):
        existing = bot.get_command(name)
        if existing is not None:
            bot.remove_command(existing.name)

    bot.add_command(_run_eb)
    bot.add_command(_run_cb)
