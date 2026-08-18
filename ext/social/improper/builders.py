"""Interactive embed (eb) and container (cb) builders with live previews.

Embed builder  → classic Discord embeds + link/styled buttons
Container builder → Components V2 LayoutView (TextDisplay, Section+Thumbnail,
                    MediaGallery, Separator, ActionRow buttons)
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import discord
from discord import ui

from core.discord.ctx import Context
from core.discord.hybrid import hybrid
from core.managers.permissions import has_permissions

if TYPE_CHECKING:
    from core.vain import Vain

_MAX_BUILDER_BUTTONS = 25
_MAX_FIELDS = 25
_MAX_IMAGES = 10
_BUTTON_STYLE_NOTE = "blue · green · red · grey · url"


def _normalize_btn_style(raw: str | None) -> str:
    s = (raw or "grey").strip().lower()
    if s in {"url", "link", "u"}:
        return "url"
    if s in {"blurple", "blue", "primary", "blurp"}:
        return "blue"
    if s in {"green", "success", "g"}:
        return "green"
    if s in {"red", "danger", "r", "yellow", "gold"}:
        return "red"
    if s in {"grey", "gray", "secondary"}:
        return "grey"
    return "grey"


def _discord_btn_style(name: str) -> discord.ButtonStyle:
    return {
        "url": discord.ButtonStyle.link,
        "blue": discord.ButtonStyle.primary,
        "green": discord.ButtonStyle.success,
        "red": discord.ButtonStyle.danger,
        "grey": discord.ButtonStyle.secondary,
    }.get(_normalize_btn_style(name), discord.ButtonStyle.secondary)


def _button_script_chunk(btn: dict[str, str]) -> str:
    """Emit named button form: label: x && style: blue && message: …"""
    style = _normalize_btn_style(btn.get("style"))
    label = (btn.get("label") or "Button").strip() or "Button"
    url = (btn.get("url") or "").strip()
    emoji = (btn.get("emoji") or "").strip()
    message = (btn.get("message") or "").strip()
    parts = [f"label: {label}", f"style: {style}"]
    if style == "url":
        parts.append(f"url: {url or 'https://discord.com'}")
    elif message:
        parts.append(f"message: {message}")
    if emoji:
        parts.append(f"emoji: {emoji}")
    return f"$v{{button: {' && '.join(parts)}}}"


class _PreviewButton(discord.ui.Button):
    """Clickable builder preview button - link opens URL; others show message ephemerally."""

    def __init__(
        self,
        btn: dict[str, str],
        *,
        index: int,
        owner_id: int | None = None,
        row: int | None = None,
    ):
        style_name = _normalize_btn_style(btn.get("style"))
        label = ((btn.get("label") or "Button").strip() or "Button")[:80]
        url = (btn.get("url") or "").strip()
        emoji = (btn.get("emoji") or "").strip() or None
        style = _discord_btn_style(style_name)
        kwargs: dict[str, Any] = {
            "label": label,
            "style": style,
            "disabled": False,
        }
        if emoji:
            kwargs["emoji"] = emoji
        if row is not None:
            kwargs["row"] = row
        self.owner_id = owner_id
        self.message_script = (btn.get("message") or "").strip() or None
        if style == discord.ButtonStyle.link:
            href = (
                url
                if url.startswith(("http://", "https://"))
                else (f"https://{url}" if url else "https://discord.com")
            )
            kwargs["url"] = href
            kwargs["style"] = discord.ButtonStyle.link
            super().__init__(**kwargs)
            return
        kwargs["custom_id"] = f"builder:preview:{index}"
        super().__init__(**kwargs)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.owner_id and interaction.user and interaction.user.id != self.owner_id:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Only <@{self.owner_id}> can use builder preview buttons.",
                    ephemeral=True,
                )
            return
        script = self.message_script
        if not script:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "No message set on this button - add one in the button modal.",
                    ephemeral=True,
                )
            return
        try:
            from core.tools.embed import _send_button_message

            await _send_button_message(interaction, script)
        except Exception:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Couldn't open that button message.",
                    ephemeral=True,
                )


def _make_preview_button(
    btn: dict[str, str],
    *,
    index: int,
    owner_id: int | None = None,
    row: int | None = None,
) -> discord.ui.Button:
    return _PreviewButton(btn, index=index, owner_id=owner_id, row=row)


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
        self._inputs: list[discord.ui.TextInput] = []
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
            self._inputs.append(item)
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        
        pairs = list(zip(self.keys, self._inputs)) if self._inputs else []
        if len(pairs) != len(self.keys):
            pairs = []
            for key, child in zip(self.keys, self.children):
                if isinstance(child, discord.ui.TextInput):
                    pairs.append((key, child))
        for key, child in pairs:
            try:
                self.values[key] = child.value or ""
            except Exception:
                self.values[key] = ""
        self._submitted = True
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass


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


class _ContentControls(discord.ui.View):
    """Content-only select menu for the container builder.

    Lives on its own message (no approve/cancel) so the C2 preview message
    never needs to carry plain content and gets deleted on every edit.
    """

    def __init__(
        self,
        owner: "_BaseBuilder",
        *,
        field_options: list[discord.SelectOption],
    ):
        super().__init__(timeout=600)
        self.owner = owner

        select = discord.ui.Select(
            placeholder="Content options...",
            min_values=1,
            max_values=1,
            options=field_options[:25],
            row=0,
            custom_id="builder:content",
        )
        select.callback = self._on_select
        self.add_item(select)

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


class _BaseBuilder:
    """Shared state for embed / container builders."""

    kind: str = "embed"
    header: str = ""

    def __init__(self, author_id: int, accent: int | None = None):
        self.author_id = author_id

        self.data: dict[str, str] = {
            "content": "",
            "self_destruct": "",
            "title": "",
            "description": "",
            "color": "",
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
            "divider_spacing": "1",
        }
        self.fields: list[dict[str, str]] = []
        self.buttons: list[dict[str, str]] = []
        self.images: list[str] = []
        
        
        self.blocks: list[dict[str, Any]] = []
        self.message: discord.Message | None = None
        self.preview_message: discord.Message | None = None
        self.content_message: discord.Message | None = None
        self._stopped = False
        self._fallback_accent = (
            int(accent) & 0xFFFFFF if accent is not None else 0x2B2D31
        )

    def _block_indices(self, typ: str) -> list[int]:
        return [i for i, b in enumerate(self.blocks) if b.get("type") == typ]

    def _upsert_singleton_block(self, typ: str, payload: dict[str, Any]) -> None:
        """Update the first block of ``typ`` in place, or append a new one."""
        for i, b in enumerate(self.blocks):
            if b.get("type") == typ:
                self.blocks[i] = {"type": typ, **payload}
                return
        self.blocks.append({"type": typ, **payload})

    def _remove_singleton_block(self, typ: str) -> None:
        self.blocks = [b for b in self.blocks if b.get("type") != typ]

    def _sync_block_from_data(self, key: str) -> None:
        """Keep ordered blocks aligned when simple data fields change (container)."""
        if self.kind != "container":
            return
        if key == "title":
            val = (self.data.get("title") or "").strip()
            if val:
                self._upsert_singleton_block("title", {"value": val})
            else:
                self._remove_singleton_block("title")
        elif key == "description":
            val = (self.data.get("description") or "").strip()
            if val:
                self._upsert_singleton_block("description", {"value": val})
            else:
                self._remove_singleton_block("description")
        elif key == "author":
            if (self.data.get("author") or "").strip():
                self._upsert_singleton_block(
                    "author",
                    {
                        "name": self.data.get("author") or "",
                        "icon": self.data.get("author_icon") or "",
                        "url": self.data.get("author_url") or "",
                    },
                )
            else:
                self._remove_singleton_block("author")
        elif key == "footer":
            if (self.data.get("footer") or "").strip() or self._truthy("footer_timestamp"):
                self._upsert_singleton_block(
                    "footer",
                    {
                        "text": self.data.get("footer") or "",
                        "timestamp": "1" if self._truthy("footer_timestamp") else "0",
                    },
                )
            else:
                self._remove_singleton_block("footer")
        elif key == "thumbnail":
            val = (self.data.get("thumbnail") or "").strip()
            if val:
                self._upsert_singleton_block("thumbnail", {"value": val})
            else:
                self._remove_singleton_block("thumbnail")
        elif key == "content":
            
            
            
            val = (self.data.get("content") or "").strip()
            if val:
                self._upsert_singleton_block("content", {"value": val})
            else:
                self._remove_singleton_block("content")
        elif key == "images":
            if self.images:
                self._upsert_singleton_block(
                    "images",
                    {"urls": list(self.images[:_MAX_IMAGES])},
                )
            else:
                self._remove_singleton_block("images")

    def _insert_divider_block(
        self,
        *,
        spacing: str = "1",
        after: str = "",
    ) -> None:
        block = {"type": "divider", "spacing": spacing if spacing in {"1", "2"} else "1"}
        after = (after or "").strip().lower()
        if not after or after in {"end", "bottom", "last", "buttons"}:
            self.blocks.append(block)
            return
        
        target = after
        if target in {"desc", "description"}:
            target = "description"
        elif target in {"img", "image", "gallery", "images"}:
            target = "images"
        elif target in {"field", "fields"}:
            target = "field"
        elif target in {"thumb", "thumbnail"}:
            target = "thumbnail"
        
        idx = None
        for i, b in enumerate(self.blocks):
            if b.get("type") == target:
                idx = i
        if idx is None:
            self.blocks.append(block)
        else:
            self.blocks.insert(idx + 1, block)

    def _pop_last_divider(self) -> bool:
        for i in range(len(self.blocks) - 1, -1, -1):
            if self.blocks[i].get("type") == "divider":
                self.blocks.pop(i)
                return True
        return False

    def _divider_count(self) -> int:
        return sum(1 for b in self.blocks if b.get("type") == "divider")





    def _has_color(self) -> bool:
        return bool((self.data.get("color") or "").strip())

    def _accent(self) -> int | None:
        """Return accent color, or None when color was left optional/empty."""
        raw = (self.data.get("color") or "").strip().lstrip("#")
        if not raw:
            return None
        try:
            return int(raw, 16) & 0xFFFFFF
        except ValueError:
            return None

    def _preview_accent(self) -> int:
        """Accent used only for live preview when no color is set."""
        accent = self._accent()
        return accent if accent is not None else self._fallback_accent

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
        opts: list[discord.SelectOption] = []
        if self.kind == "embed":
            opts.append(
                discord.SelectOption(
                    label="Content (message text)",
                    value="content",
                    description="Plain text above the embed",
                )
            )
        opts.extend(
            [
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
                discord.SelectOption(label="Thumbnail URL", value="thumbnail"),
            ]
        )
        opts.append(
            discord.SelectOption(
                label="Self destruct",
                value="self_destruct",
                description="Auto-delete after 5s / 30s / 1h / mins",
            )
        )
        if (self.data.get("self_destruct") or "").strip():
            opts.append(
                discord.SelectOption(
                    label="Remove self destruct",
                    value="self_destruct_remove",
                    description="Cancel the auto-delete timer",
                )
            )
        if self.kind == "embed":
            opts.append(
                discord.SelectOption(
                    label="Image URL",
                    value="image",
                    description="Single embed image",
                )
            )
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
            n_img = len(self.images)
            head_n = min(n_img, 5)
            tail_n = max(0, n_img - 5)
            opts.append(
                discord.SelectOption(
                    label=f"Images 1–5 ({head_n}/5)",
                    value="images_1_5",
                    description="Gallery images 1 through 5",
                )
            )
            opts.append(
                discord.SelectOption(
                    label=f"Images 6–10 ({tail_n}/5)",
                    value="images_6_10",
                    description="Gallery images 6 through 10",
                )
            )
            if n_img:
                opts.append(
                    discord.SelectOption(
                        label="Clear images",
                        value="images_clear",
                    )
                )
            n_div = self._divider_count()
            opts.append(
                discord.SelectOption(
                    label=f"Add Divider / Separator ({n_div})",
                    value="divider",
                    description="spacing · optional after: title/description/…",
                )
            )
            if n_div:
                opts.append(
                    discord.SelectOption(
                        label="Remove previous divider",
                        value="divider_remove",
                        description="Drop the last divider in order",
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

    def _content_options(self) -> list[discord.SelectOption]:
        opts: list[discord.SelectOption] = [
            discord.SelectOption(
                label="Content (message text)",
                value="content",
                description="Plain text above the container",
            )
        ]
        if (self.data.get("content") or "").strip():
            opts.append(
                discord.SelectOption(
                    label="Remove content",
                    value="content_remove",
                    description="Remove the plain message text",
                )
            )
        return opts

    def _content_controls(self) -> _ContentControls:
        return _ContentControls(self, field_options=self._content_options())

    async def _refresh_content_message(
        self,
        content: str | None,
        channel: Any,
    ) -> None:
        content = (content or "").strip() or None
        view = self._content_controls()
        if self.content_message is not None:
            try:
                await self.content_message.edit(content=content, embed=None, view=view)
                return
            except Exception:
                with contextlib.suppress(Exception):
                    await self.content_message.delete()
                self.content_message = None
        if channel is not None:
            try:
                self.content_message = await channel.send(
                    content=content
                    or "use the dropdown to replace this text with whatever you put in",
                    view=view,
                )
            except Exception:
                self.content_message = None

    def _embed_preview_view(self) -> discord.ui.View:
        """Controls + clickable preview buttons for the embed builder message."""
        view = _BuilderControls(self, field_options=self._field_options())
        
        
        max_preview = min(len(self.buttons), 15)
        for i, btn in enumerate(self.buttons[:max_preview]):
            try:
                view.add_item(
                    _make_preview_button(
                        btn,
                        index=i,
                        owner_id=self.author_id,
                        row=2 + (i // 5),
                    )
                )
            except Exception:
                pass
        return view

    
    
    

    def _to_script(self) -> str:
        mode = "{embed}" if self.kind == "embed" else "{container}"
        parts = [mode]
        
        
        emit_top_content = True
        if self.kind == "container" and self.blocks:
            emit_top_content = not any(b.get("type") == "content" for b in self.blocks)
        if emit_top_content and self.data.get("content"):
            parts.append(f"$v{{content: {self.data['content']}}}")

        color_raw = (self.data.get("color") or "").strip().lstrip("#")
        if color_raw:
            parts.append(f"$v{{color: #{color_raw}}}")
        if self.data.get("url") and self.kind == "embed":
            parts.append(f"$v{{url: {self.data['url']}}}")

        if self.kind == "container" and self.blocks:
            
            for block in self.blocks:
                typ = block.get("type")
                if typ == "content":
                    val = (
                        block.get("value") or self.data.get("content") or ""
                    ).strip()
                    if val:
                        parts.append(f"$v{{content: {val}}}")
                elif typ == "title":
                    val = (block.get("value") or self.data.get("title") or "").strip()
                    if val:
                        parts.append(f"$v{{title: {val}}}")
                elif typ == "description":
                    val = (
                        block.get("value") or self.data.get("description") or ""
                    ).strip()
                    if val:
                        parts.append(f"$v{{description: {val}}}")
                elif typ == "author":
                    name = (block.get("name") or self.data.get("author") or "").strip()
                    if not name:
                        continue
                    named = [f"name: {name}"]
                    icon = (
                        block.get("icon") or self.data.get("author_icon") or ""
                    ).strip()
                    url = (
                        block.get("url") or self.data.get("author_url") or ""
                    ).strip()
                    if icon:
                        named.append(f"icon: {icon}")
                    if url:
                        named.append(f"url: {url}")
                    parts.append(f"$v{{author: {' && '.join(named)}}}")
                elif typ == "footer":
                    text = (
                        block.get("text") or self.data.get("footer") or ""
                    ).strip()
                    if text:
                        named = [f"text: {text}"]
                        if self.data.get("footer_icon"):
                            named.append(f"icon: {self.data['footer_icon']}")
                        parts.append(f"$v{{footer: {' && '.join(named)}}}")
                elif typ == "thumbnail":
                    val = (
                        block.get("value") or self.data.get("thumbnail") or ""
                    ).strip()
                    if val:
                        parts.append(f"$v{{thumbnail: {val}}}")
                elif typ == "images":
                    urls = list(block.get("urls") or self.images or [])[:_MAX_IMAGES]
                    urls = [u for u in urls if u]
                    
                    if urls[:5]:
                        parts.append(f"$v{{image: {' && '.join(urls[:5])}}}")
                    if urls[5:10]:
                        parts.append(f"$v{{image: {' && '.join(urls[5:10])}}}")
                elif typ == "field":
                    name = block.get("name") or "Field"
                    value = block.get("value") or "​"
                    parts.append(f"$v{{field: name: {name} && value: {value}}}")
                elif typ == "divider":
                    spacing = (block.get("spacing") or "1").strip() or "1"
                    parts.append(
                        f"$v{{separator: divider: true && spacing: {spacing}}}"
                    )
        else:
            
            if self.data.get("title"):
                parts.append(f"$v{{title: {self.data['title']}}}")
            if self.data.get("description"):
                parts.append(f"$v{{description: {self.data['description']}}}")
            if self.data.get("author"):
                named = [f"name: {self.data['author']}"]
                if self.data.get("author_icon"):
                    named.append(f"icon: {self.data['author_icon']}")
                if self.data.get("author_url"):
                    named.append(f"url: {self.data['author_url']}")
                parts.append(f"$v{{author: {' && '.join(named)}}}")
            if self.data.get("footer"):
                named = [f"text: {self.data['footer']}"]
                if self.data.get("footer_icon"):
                    named.append(f"icon: {self.data['footer_icon']}")
                parts.append(f"$v{{footer: {' && '.join(named)}}}")
            if self._truthy("footer_timestamp") and self.kind == "embed":
                parts.append("$v{timestamp}")
            if self.kind == "embed" and self.data.get("image"):
                parts.append(f"$v{{image: {self.data['image']}}}")
            if self.kind == "container" and self.images:
                urls = [u for u in self.images[:_MAX_IMAGES] if u]
                if urls[:5]:
                    parts.append(f"$v{{image: {' && '.join(urls[:5])}}}")
                if urls[5:10]:
                    parts.append(f"$v{{image: {' && '.join(urls[5:10])}}}")
            elif self.kind == "container" and self.data.get("image"):
                parts.append(f"$v{{image: {self.data['image']}}}")
            if self.data.get("thumbnail"):
                parts.append(f"$v{{thumbnail: {self.data['thumbnail']}}}")
            for field in self.fields[:_MAX_FIELDS]:
                name = field.get("name") or "Field"
                value = field.get("value") or "​"
                inline = field.get("inline") == "1"
                if self.kind == "embed":
                    named = [f"name: {name}", f"value: {value}"]
                    if inline:
                        named.append("inline: true")
                    parts.append(f"$v{{field: {' && '.join(named)}}}")
                else:
                    parts.append(f"$v{{field: name: {name} && value: {value}}}")

        if self.kind == "embed":
            
            pass

        for btn in self.buttons[:_MAX_BUILDER_BUTTONS]:
            parts.append(_button_script_chunk(btn))
        sd = (self.data.get("self_destruct") or "").strip()
        if sd:
            parts.append(f" --self_destruct {sd}")
        if len(parts) == 1:
            return f"{mode}$v{{description: }}"
        return "".join(parts)

    
    
    

    def _preview_embed(self) -> discord.Embed:
        emb = discord.Embed(
            title=self.data.get("title") or None,
            description=self.data.get("description") or None,
            url=(self.data.get("url") or None) or None,
        )
        
        accent = self._accent()
        if accent is not None:
            emb.color = accent
        else:
            emb.color = self._fallback_accent
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

    def _add_separator(self, container: ui.Container, spacing_raw: str = "1") -> None:
        try:
            large = (spacing_raw or "1").strip() in {"2", "large", "big", "lg"}
            spacing_enum = getattr(discord, "SeparatorSpacing", None)
            if spacing_enum is not None:
                sp = spacing_enum.large if large else spacing_enum.small
                container.add_item(ui.Separator(visible=True, spacing=sp))
            else:
                container.add_item(ui.Separator(visible=True))
        except Exception:
            try:
                container.add_item(ui.Separator(visible=True))
            except Exception:
                pass

    def _add_gallery(self, container: ui.Container, urls: list[str]) -> None:
        """Add gallery item(s); split into groups of 5 (1–5 and 6–10)."""
        image_urls = [u for u in urls[:_MAX_IMAGES] if str(u).startswith("http")]
        if not image_urls:
            return
        for start in range(0, len(image_urls), 5):
            chunk = image_urls[start : start + 5]
            try:
                gallery = ui.MediaGallery()
                for image in chunk:
                    gallery.add_item(media=image)
                container.add_item(gallery)
            except Exception:
                try:
                    container.add_item(
                        ui.MediaGallery(
                            *[discord.MediaGalleryItem(image) for image in chunk]
                        )
                    )
                except Exception:
                    pass

    def _preview_container(self) -> tuple[str | None, ui.LayoutView]:
        layout = ui.LayoutView(timeout=None)
        container = ui.Container()

        _ = self._accent()

        content: str | None = None

        blocks = list(self.blocks) if self.blocks else None
        if not blocks:
            blocks = None
        if blocks is None:
            content = (self.data.get("content") or "").strip() or None
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
                    foot = (
                        f"{foot} · Today at {now.strftime('%H:%M')}"
                        if foot
                        else f"Today at {now.strftime('%H:%M')}"
                    )
                if foot:
                    lines.append(f"> -# {foot}")
            elif self._truthy("footer_timestamp"):
                now = discord.utils.utcnow()
                lines.append(f"> -# Today at {now.strftime('%H:%M')}")

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
                self._add_separator(
                    container, self.data.get("divider_spacing") or "1"
                )

            image_urls = [
                u for u in self.images[:_MAX_IMAGES] if str(u).startswith("http")
            ]
            if not image_urls:
                single = (self.data.get("image") or "").strip()
                if single.startswith("http"):
                    image_urls = [single]
            self._add_gallery(container, image_urls)
        else:
            pending_lines: list[str] = []
            pending_thumb: str | None = None
            content_parts: list[str] = []

            def _flush_text() -> None:
                nonlocal pending_lines, pending_thumb
                if not pending_lines and not pending_thumb:
                    return
                body = "\n".join(pending_lines) if pending_lines else "​"
                accessory = (pending_thumb or "").strip()
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
                pending_lines = []
                pending_thumb = None

            for block in blocks:
                typ = block.get("type")
                if typ == "divider":
                    _flush_text()
                    self._add_separator(container, block.get("spacing") or "1")
                elif typ == "images":
                    _flush_text()
                    urls = list(block.get("urls") or self.images or [])
                    self._add_gallery(container, urls)
                elif typ == "content":
                    _flush_text()
                    val = (block.get("value") or "").strip()
                    if val:
                        content_parts.append(val)
                elif typ == "title":
                    val = (block.get("value") or "").strip()
                    if val:
                        pending_lines.append(f"## {val}")
                elif typ == "description":
                    val = (block.get("value") or "").strip()
                    if val:
                        pending_lines.append(val)
                elif typ == "author":
                    name = (block.get("name") or "").strip()
                    icon = (block.get("icon") or "").strip()
                    if name:
                        pending_lines.append(f"**{name}**")
                    if icon.startswith("http") and not pending_thumb:
                        pending_thumb = icon
                elif typ == "footer":
                    foot = _strip_subtext(block.get("text") or "")
                    if (block.get("timestamp") or "") == "1" or self._truthy(
                        "footer_timestamp"
                    ):
                        now = discord.utils.utcnow()
                        stamp = f"Today at {now.strftime('%H:%M')}"
                        foot = f"{foot} · {stamp}" if foot else stamp
                    if foot:
                        pending_lines.append(f"> -# {foot}")
                elif typ == "field":
                    name = block.get("name") or "Field"
                    value = block.get("value") or "​"
                    pending_lines.append(f"**{name}**\n{value}")
                elif typ == "thumbnail":
                    val = (block.get("value") or "").strip()
                    if val.startswith("http"):
                        pending_thumb = val

            _flush_text()
            
            content = (
                "\n".join(part for part in content_parts if part.strip()).strip()
                or (self.data.get("content") or "").strip()
                or None
            )

            if not getattr(container, "children", None):
                try:
                    container.add_item(ui.TextDisplay("​"))
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
                        row.add_item(
                            _make_preview_button(
                                btn,
                                index=i + j,
                                owner_id=self.author_id,
                            )
                        )
                    except Exception:
                        pass
                if getattr(row, "children", None):
                    try:
                        container.add_item(row)
                    except Exception:
                        pass

        layout.add_item(container)
        return content, layout

    async def refresh(self) -> None:
        if self._stopped or not self.message:
            return

        content = (self.data.get("content") or "").strip() or None
        channel = getattr(self.message, "channel", None)

        if self.kind == "embed":
            view = self._embed_preview_view()
            embed = self._preview_embed()
            try:
                await self.message.edit(content=content, embed=embed, view=view)
            except Exception:
                
                if channel is not None:
                    try:
                        with contextlib.suppress(Exception):
                            await self.message.delete()
                        self.message = await channel.send(
                            content=content, embed=embed, view=view
                        )
                    except Exception:
                        pass
            return

        
        
        
        
        try:
            await self.message.edit(content=None, embed=None, view=self._controls())
        except Exception:
            if channel is not None:
                try:
                    with contextlib.suppress(Exception):
                        await self.message.delete()
                    self.message = await channel.send(view=self._controls())
                except Exception:
                    pass

        preview_content, preview = self._preview_container()
        await self._refresh_content_message(preview_content, channel)

        if self.preview_message is not None:
            try:
                await self.preview_message.edit(content=None, embed=None, view=preview)
                return
            except Exception:
                with contextlib.suppress(Exception):
                    await self.preview_message.delete()
                self.preview_message = None

        if channel is not None:
            try:
                self.preview_message = await channel.send(content=None, view=preview)
            except Exception:
                self.preview_message = None

    async def _run_modal(
        self,
        inter: discord.Interaction,
        title: str,
        fields: list[tuple[str, str, bool, int, str]],
    ) -> dict[str, str] | None:
        modal = _BuilderModal(title, fields)
        try:
            if inter.response.is_done():
                return None
            await inter.response.send_modal(modal)
        except Exception:
            return None
        await modal.wait()
        if not getattr(modal, "_submitted", False):
            return None
        
        out = {str(k): str(v or "") for k, v in dict(modal.values).items()}
        
        for entry in fields[:5]:
            out.setdefault(str(entry[0]), "")
        return out

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
                    ("style", "Style: blue green red grey url", False, 20, "blue"),
                    ("url", "URL (style url only)", False, 500, ""),
                    ("emoji", "Emoji (optional)", False, 100, ""),
                    (
                        "message",
                        "Message (plain / embed / container script)",
                        True,
                        4000,
                        "",
                    ),
                ],
            )
            if not values:
                return
            label = (values.get("label") or "").strip() or "Button"
            url = (values.get("url") or "").strip()
            emoji = (values.get("emoji") or "").strip()
            message = (values.get("message") or "").strip()
            style = _normalize_btn_style(values.get("style") or "blue")
            if style == "url" and not url:
                url = "https://discord.com"
            self.buttons.append(
                {
                    "label": label,
                    "url": url,
                    "emoji": emoji,
                    "style": style,
                    "message": message,
                }
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

        if key == "content_remove":
            self.data["content"] = ""
            self._remove_singleton_block("content")
            if not inter.response.is_done():
                await inter.response.defer()
            await self.refresh()
            return

        if key in {"images", "images_1_5", "images_6_10"}:
            if key == "images_6_10" or (
                key == "images" and len(self.images) >= 5
            ):
                values = await self._run_modal(
                    inter,
                    f"Gallery Images 6–{_MAX_IMAGES}",
                    [
                        (
                            "img6",
                            "Image 6 URL",
                            False,
                            500,
                            self.images[5] if len(self.images) > 5 else "",
                        ),
                        (
                            "img7",
                            "Image 7 URL",
                            False,
                            500,
                            self.images[6] if len(self.images) > 6 else "",
                        ),
                        (
                            "img8",
                            "Image 8 URL",
                            False,
                            500,
                            self.images[7] if len(self.images) > 7 else "",
                        ),
                        (
                            "img9",
                            "Image 9 URL",
                            False,
                            500,
                            self.images[8] if len(self.images) > 8 else "",
                        ),
                        (
                            "img10",
                            "Image 10 URL",
                            False,
                            500,
                            self.images[9] if len(self.images) > 9 else "",
                        ),
                    ],
                )
                if values is None:
                    return
                head = list(self.images[:5])
                while len(head) < 5:
                    head.append("")
                tail = [
                    (values.get("img6") or "").strip(),
                    (values.get("img7") or "").strip(),
                    (values.get("img8") or "").strip(),
                    (values.get("img9") or "").strip(),
                    (values.get("img10") or "").strip(),
                ]
                
                merged = list(head) + tail
                self.images = [u for u in merged if u][:_MAX_IMAGES]
            else:
                values = await self._run_modal(
                    inter,
                    "Gallery Images 1–5",
                    [
                        (
                            "img1",
                            "Image 1 URL",
                            False,
                            500,
                            self.images[0] if len(self.images) > 0 else "",
                        ),
                        (
                            "img2",
                            "Image 2 URL",
                            False,
                            500,
                            self.images[1] if len(self.images) > 1 else "",
                        ),
                        (
                            "img3",
                            "Image 3 URL",
                            False,
                            500,
                            self.images[2] if len(self.images) > 2 else "",
                        ),
                        (
                            "img4",
                            "Image 4 URL",
                            False,
                            500,
                            self.images[3] if len(self.images) > 3 else "",
                        ),
                        (
                            "img5",
                            "Image 5 URL",
                            False,
                            500,
                            self.images[4] if len(self.images) > 4 else "",
                        ),
                    ],
                )
                if values is None:
                    return
                batch = [
                    (values.get("img1") or "").strip(),
                    (values.get("img2") or "").strip(),
                    (values.get("img3") or "").strip(),
                    (values.get("img4") or "").strip(),
                    (values.get("img5") or "").strip(),
                ]
                tail = self.images[5:_MAX_IMAGES] if len(self.images) > 5 else []
                self.images = [u for u in (*batch, *tail) if u][:_MAX_IMAGES]
            self.data["image"] = self.images[0] if self.images else ""
            self._sync_block_from_data("images")
            await self.refresh()
            return

        if key == "images_clear":
            self.images.clear()
            self.data["image"] = ""
            self._remove_singleton_block("images")
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
            inline = (
                "1"
                if inline_raw in {"yes", "y", "true", "1", "on", "inline"}
                else "0"
            )
            entry = {"name": name, "value": value, "inline": inline}
            self.fields.append(entry)
            if self.kind == "container":
                self.blocks.append(
                    {"type": "field", "name": name, "value": value, "inline": inline}
                )
            await self.refresh()
            return

        if key == "field_remove":
            if self.fields:
                self.fields.pop()
            if self.kind == "container":
                for i in range(len(self.blocks) - 1, -1, -1):
                    if self.blocks[i].get("type") == "field":
                        self.blocks.pop(i)
                        break
            if not inter.response.is_done():
                await inter.response.defer()
            await self.refresh()
            return

        if key == "field_clear":
            self.fields.clear()
            if self.kind == "container":
                self.blocks = [b for b in self.blocks if b.get("type") != "field"]
            if not inter.response.is_done():
                await inter.response.defer()
            await self.refresh()
            return

        if key == "divider_remove":
            removed = self._pop_last_divider()
            self.data["divider"] = "1" if self._divider_count() else "0"
            if not inter.response.is_done():
                if removed:
                    await inter.response.defer()
                else:
                    await inter.response.send_message(
                        "No divider to remove.",
                        ephemeral=True,
                    )
                    return
            await self.refresh()
            return

        if key == "divider":
            values = await self._run_modal(
                inter,
                "Divider / Separator",
                [
                    (
                        "divider_spacing",
                        "Spacing 1 (small) or 2 (large)",
                        False,
                        10,
                        self.data.get("divider_spacing") or "1",
                    ),
                    (
                        "after",
                        "Place after (optional): title, description, author, footer, field, images, thumbnail - blank = end",
                        False,
                        40,
                        "",
                    ),
                ],
            )
            if values is None:
                return
            sp = (values.get("divider_spacing") or "1").strip()
            spacing = "2" if sp in {"2", "large", "big", "lg"} else "1"
            self.data["divider_spacing"] = spacing
            after = (values.get("after") or "").strip()
            self._insert_divider_block(spacing=spacing, after=after)
            self.data["divider"] = "1"
            await self.refresh()
            return

        if key == "author":
            values = await self._run_modal(
                inter,
                "Author",
                [
                    ("author", "Name", False, 256, self.data.get("author") or ""),
                    (
                        "author_icon",
                        "Icon URL",
                        False,
                        500,
                        self.data.get("author_icon") or "",
                    ),
                    (
                        "author_url",
                        "URL",
                        False,
                        500,
                        self.data.get("author_url") or "",
                    ),
                ],
            )
            if values:
                for k in ("author", "author_icon", "author_url"):
                    if k in values:
                        self.data[k] = (values[k] or "").strip()
                self._sync_block_from_data("author")
            await self.refresh()
            return

        if key == "footer":
            values = await self._run_modal(
                inter,
                "Footer",
                [
                    ("footer", "Text", True, 2048, self.data.get("footer") or ""),
                    (
                        "footer_icon",
                        "Icon URL",
                        False,
                        500,
                        self.data.get("footer_icon") or "",
                    ),
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
                self._sync_block_from_data("footer")
            await self.refresh()
            return

        if key == "self_destruct":
            values = await self._run_modal(
                inter,
                "Self destruct",
                [
                    (
                        "self_destruct",
                        "Time (5s, 30s, 1h, 5m or seconds)",
                        False,
                        20,
                        self.data.get("self_destruct") or "",
                    )
                ],
            )
            if values is None:
                return
            raw = (values.get("self_destruct") or "").strip()
            if raw and not raw.isdigit():
                from core.tools.moderation_args import parse_duration_seconds

                if parse_duration_seconds(raw) is None:
                    if not inter.response.is_done():
                        await inter.response.send_message(
                            f"Invalid time: `{raw}` - use 5s, 30s, 1h, 5m or seconds.",
                            ephemeral=True,
                        )
                    return
            self.data["self_destruct"] = raw
            await self.refresh()
            return

        if key == "self_destruct_remove":
            self.data["self_destruct"] = ""
            if not inter.response.is_done():
                await inter.response.defer()
            await self.refresh()
            return

        labels = {
            "content": ("Content / message text", True, 2000),
            "title": ("Title", False, 256),
            "description": ("Description", True, 4000),
            "color": ("Color hex (optional - leave empty for none)", False, 20),
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
        if values is None:
            return
        raw = values.get(key, self.data.get(key) or "")
        self.data[key] = (raw or "").strip()
        if key == "color":
            self.data[key] = self.data[key].lstrip("#")
        if key in {"title", "description", "thumbnail", "content", "image"}:
            if key == "image" and self.data[key]:
                
                if not self.images:
                    self.images = [self.data[key]]
                else:
                    self.images[0] = self.data[key]
                self._sync_block_from_data("images")
            else:
                self._sync_block_from_data(key)
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
                    f"Could not DM you - script:\n```\n{chunk}\n```",
                    ephemeral=True,
                )
        self._stopped = True
        try:
            self.stop_controls()
        except Exception:
            pass
        if self.content_message is not None:
            try:
                await self.content_message.edit(view=None)
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
        if self.content_message is not None:
            try:
                await self.content_message.delete()
            except Exception:
                pass

    async def handle_timeout(self) -> None:
        self._stopped = True
        if self.message:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass
        if self.content_message is not None:
            try:
                await self.content_message.edit(view=None)
            except Exception:
                pass


class EmbedBuilderView(_BaseBuilder):
    kind = "embed"
    header = ""


class ContainerBuilderView(_BaseBuilder):
    kind = "container"
    header = ""


async def register_builders(bot: "Vain", cog=None) -> None:
    """Register ,embedbuilder / ,containerbuilder hybrid commands on the bot."""

    @hybrid(
        name="embedbuilder",
        aliases=["eb"],
        description="Interactive embed builder with live preview. Approve DMs the script.",
        example=",embedbuilder",
    )
    @has_permissions(manage_messages=True)
    async def _run_eb(ctx: Context):
        accent = getattr(ctx.bot, "color", None) or 0x2B2D31
        builder = EmbedBuilderView(ctx.author.id, accent=int(accent))
        m = await ctx.send(
            embed=builder._preview_embed(),
            view=builder._embed_preview_view(),
            raw_embed=True,
        )
        builder.message = m

    @hybrid(
        name="containerbuilder",
        aliases=["cb"],
        description="Interactive Components V2 container builder with live preview. Approve DMs the script.",
        example=",containerbuilder",
    )
    @has_permissions(manage_messages=True)
    async def _run_cb(ctx: Context):
        
        accent = getattr(ctx.bot, "color", None) or 0x2B2D31
        builder = ContainerBuilderView(ctx.author.id, accent=int(accent))
        preview_content, preview_layout = builder._preview_container()
        await builder._refresh_content_message(preview_content, ctx.channel)
        m = await ctx.send(view=builder._controls())
        builder.message = m
        try:
            preview = await ctx.send(content=None, view=preview_layout)
            builder.preview_message = preview
        except Exception:
            builder.preview_message = None

    for name in ("embedbuilder", "containerbuilder", "eb", "cb"):
        existing = bot.get_command(name)
        if existing is not None:
            bot.remove_command(existing.name)

    if cog is None:
        cog = bot.get_cog("Snipe")
    for cmd in (_run_eb, _run_cb):
        cmd.cog = cog
        bot.add_command(cmd)
