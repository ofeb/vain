"""Interactive embed (eb) and container (cb) builders with live previews."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ui

from core.discord.ctx import Context
from core.discord.hybrid import hybrid

if TYPE_CHECKING:
    from core.vain import Vain

_MAX_BUILDER_BUTTONS = 25
_BUTTON_STYLE_NOTE = "url · blurple · green · red · grey  (emoji optional)"
_HEADER_EB = (
    "**Embed Builder** · live preview below\n"
    "-# Select a field → fill modal → preview updates. Approve DMs you the script."
)
_HEADER_CB = (
    "**Container Builder** · live preview below\n"
    "-# Select a field → fill modal → preview updates. Approve DMs you the script."
)


def _normalize_btn_style(raw: str | None) -> str:
    """Canonical button style name for scripts: url|blurple|green|red|grey."""
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
    """Serialize one button into embed/container script syntax."""
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


def _make_preview_button(
    btn: dict[str, str], *, index: int, v2: bool = False
) -> discord.ui.Button:
    """Build a Discord button for live preview (link or disabled styled)."""
    style_name = _normalize_btn_style(btn.get("style"))
    label = ((btn.get("label") or "Button").strip() or "Button")[:80]
    url = (btn.get("url") or "").strip()
    emoji = (btn.get("emoji") or "").strip() or None
    style = _discord_btn_style(style_name)
    if style == discord.ButtonStyle.link:
        href = (
            url
            if url.startswith("http")
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
        custom_id=f"{'cb' if v2 else 'eb'}:preview:{index}",
    )


class _BuilderModal(discord.ui.Modal):
    """Generic single/multi-field modal for embed & container builders."""

    def __init__(self, title: str, fields: list[tuple[str, str, bool, int]]):
        super().__init__(title=title[:45])
        self.keys: list[str] = []
        self.values: dict[str, str] = {}
        for key, label, paragraph, maxlen in fields[:5]:
            self.keys.append(key)
            style = (
                discord.TextStyle.paragraph if paragraph else discord.TextStyle.short
            )
            item = discord.ui.TextInput(
                label=label[:45],
                style=style,
                required=False,
                max_length=min(maxlen, 4000),
            )
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        for key, child in zip(self.keys, self.children):
            if isinstance(child, discord.ui.TextInput):
                self.values[key] = child.value or ""
        await interaction.response.defer()


class _BuilderControls(discord.ui.View):
    """Shared select + approve/cancel controls for eb/cb (classic View)."""

    def __init__(
        self, owner: "_BaseBuilder", *, field_options: list[discord.SelectOption]
    ):
        super().__init__(timeout=300)
        self.owner = owner
        select = discord.ui.Select(
            placeholder="Choose what to edit...",
            min_values=1,
            max_values=1,
            options=field_options,
            row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

        approve = discord.ui.Button(
            label="Approve & DM Script",
            style=discord.ButtonStyle.success,
            row=4,
        )
        cancel = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            row=4,
        )
        approve.callback = self._on_approve
        cancel.callback = self._on_cancel
        self.add_item(approve)
        self.add_item(cancel)

        
        
        for i, btn in enumerate(owner.buttons[:15]):
            row = 1 + (i // 5)
            if row > 3:
                break
            try:
                item = _make_preview_button(btn, index=i, v2=False)
                item.row = row
                self.add_item(item)
            except Exception:
                pass

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id == self.owner.author_id:
            return True
        await inter.response.send_message(
            f"Only <@{self.owner.author_id}> can use this.",
            ephemeral=True,
        )
        return False

    async def _on_select(self, inter: discord.Interaction) -> None:
        data = inter.data or {}
        values = list(data.get("values") or []) if isinstance(data, dict) else []
        key = values[0] if values else ""
        await self.owner.handle_field(inter, key)

    async def _on_approve(self, inter: discord.Interaction) -> None:
        await self.owner.handle_approve(inter)

    async def _on_cancel(self, inter: discord.Interaction) -> None:
        await self.owner.handle_cancel(inter)

    async def on_timeout(self) -> None:
        await self.owner.handle_timeout()


class _BaseBuilder:
    """Shared field data + button list for eb / cb."""

    kind: str = "embed"
    header: str = _HEADER_EB

    def __init__(self, author_id: int, accent: int | None = None):
        self.author_id = author_id
        self.data: dict[str, str] = {
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
            "divider": "0",
        }
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

    def _field_options(self) -> list[discord.SelectOption]:
        opts = [
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
        if self.kind == "container":
            opts.append(
                discord.SelectOption(
                    label="Divider on/off",
                    value="divider",
                    description="Toggle separator",
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
        return opts

    def _controls(self) -> _BuilderControls:
        return _BuilderControls(self, field_options=self._field_options())

    def _to_script(self) -> str:
        mode = "{embed}" if self.kind == "embed" else "{container}"
        parts = [mode]
        if self.data.get("title"):
            parts.append(f"$v{{title: {self.data['title']}}}")
        if self.data.get("description"):
            parts.append(f"$v{{description: {self.data['description']}}}")
        if self.data.get("color"):
            parts.append(f"$v{{color: #{self.data['color'].lstrip('#')}}}")
        if self.data.get("author"):
            bits = [self.data["author"]]
            if self.data.get("author_icon"):
                bits.append(self.data["author_icon"])
            if self.data.get("author_url"):
                
                if not self.data.get("author_icon"):
                    bits.append("")  
                bits.append(self.data["author_url"])
            parts.append(f"$v{{author: {' && '.join(bits)}}}")
        if self.data.get("footer"):
            fbits = [self.data["footer"]]
            if self.data.get("footer_icon"):
                fbits.append(self.data["footer_icon"])
            parts.append(f"$v{{footer: {' && '.join(fbits)}}}")
        if self.data.get("footer_timestamp") in {"1", "true", "yes", "on"}:
            parts.append("$v{timestamp}")
        if self.kind == "container" and self.data.get("divider") in {
            "1",
            "true",
            "yes",
            "on",
        }:
            parts.append("$v{divider}")
        if self.data.get("image"):
            parts.append(f"$v{{image: {self.data['image']}}}")
        if self.data.get("thumbnail"):
            parts.append(f"$v{{thumbnail: {self.data['thumbnail']}}}")
        for btn in self.buttons[:_MAX_BUILDER_BUTTONS]:
            parts.append(_button_script_chunk(btn))
        if len(parts) == 1:
            return f"{mode}$v{{description: }}"
        return "".join(parts)

    def _preview_embed(self) -> discord.Embed:
        emb = discord.Embed(
            title=self.data.get("title") or None,
            description=self.data.get("description") or None,
            color=self._accent(),
        )
        if self.data.get("author"):
            kwargs: dict = {"name": self.data["author"]}
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
        if self.data.get("footer_timestamp") in {"1", "true", "yes", "on"}:
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
            )
        )
        if not has_any:
            emb.description = "\u200b"
        elif not emb.title and not emb.description:
            emb.description = "\u200b"
        return emb

    def _preview_container(self) -> ui.LayoutView:
        """Visual empty/filled container for cb live preview."""
        layout = ui.LayoutView(timeout=None)
        container = ui.Container(accent_colour=self._accent())

        lines: list[str] = []
        if self.data.get("author"):
            lines.append(f"**{self.data['author']}**")
        if self.data.get("title"):
            lines.append(f"## {self.data['title']}")
        if self.data.get("description"):
            lines.append(self.data["description"])
        if self.data.get("footer"):
            foot = self.data["footer"]
            if self.data.get("footer_timestamp") in {"1", "true", "yes", "on"}:
                now = discord.utils.utcnow()
                foot = f"{foot} · Today at {now.strftime('%H:%M')}"
            lines.append(f"-# {foot}")
        elif self.data.get("footer_timestamp") in {"1", "true", "yes", "on"}:
            now = discord.utils.utcnow()
            lines.append(f"-# Today at {now.strftime('%H:%M')}")

        body = "\n".join(lines) if lines else "\u200b"
        
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

        if self.data.get("divider") in {"1", "true", "yes", "on"}:
            container.add_item(ui.Separator(visible=True))

        image = (self.data.get("image") or "").strip()
        if image.startswith("http"):
            try:
                container.add_item(ui.MediaGallery(discord.MediaGalleryItem(image)))
            except Exception:
                pass

        
        if self.buttons:
            container.add_item(ui.Separator(visible=True))
            for i in range(0, min(len(self.buttons), _MAX_BUILDER_BUTTONS), 5):
                row = ui.ActionRow()
                for j, btn in enumerate(self.buttons[i : i + 5]):
                    try:
                        row.add_item(_make_preview_button(btn, index=i + j, v2=True))
                    except Exception:
                        pass
                if row.children:
                    container.add_item(row)

        layout.add_item(container)
        return layout

    async def refresh(self) -> None:
        if self._stopped or not self.message:
            return
        try:
            if self.kind == "embed":
                await self.message.edit(
                    content=self.header,
                    embed=self._preview_embed(),
                    view=self._controls(),
                )
            else:
                await self.message.edit(
                    content=self.header,
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

    async def handle_field(self, inter: discord.Interaction, key: str) -> None:
        if key == "button":
            if len(self.buttons) >= _MAX_BUILDER_BUTTONS:
                await inter.response.send_message(
                    f"Max **{_MAX_BUILDER_BUTTONS}** buttons.",
                    ephemeral=True,
                )
                return
            modal = _BuilderModal(
                f"Add Button ({len(self.buttons) + 1}/{_MAX_BUILDER_BUTTONS})",
                [
                    ("label", "Label / title", False, 80),
                    ("url", "URL (required for style url)", False, 500),
                    ("emoji", "Emoji (optional)", False, 100),
                    (
                        "style",
                        "Style: url blurple green red grey",
                        False,
                        20,
                    ),
                ],
            )
            await inter.response.send_modal(modal)
            await modal.wait()
            if not modal.values:
                return
            label = (modal.values.get("label") or "").strip() or "Button"
            url = (modal.values.get("url") or "").strip()
            emoji = (modal.values.get("emoji") or "").strip()
            style = _normalize_btn_style(modal.values.get("style") or "url")
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

        if key == "divider":
            modal = _BuilderModal(
                "Divider",
                [("divider", "on or off", False, 10)],
            )
            await inter.response.send_modal(modal)
            await modal.wait()
            if modal.values:
                val = (modal.values.get("divider") or "").lower().strip()
                self.data["divider"] = (
                    "1" if val in {"on", "yes", "true", "1", "enable"} else "0"
                )
            await self.refresh()
            return

        if key == "author":
            modal = _BuilderModal(
                "Author",
                [
                    ("author", "Name", False, 256),
                    ("author_icon", "Icon URL (optional)", False, 500),
                    ("author_url", "URL (optional)", False, 500),
                ],
            )
            await inter.response.send_modal(modal)
            await modal.wait()
            if modal.values:
                for k in ("author", "author_icon", "author_url"):
                    if k in modal.values:
                        self.data[k] = (modal.values[k] or "").strip()
            await self.refresh()
            return

        if key == "footer":
            modal = _BuilderModal(
                "Footer",
                [
                    ("footer", "Text", True, 2048),
                    ("footer_icon", "Icon URL (optional)", False, 500),
                    (
                        "footer_timestamp",
                        "Timestamp yes/no (Today at HH:MM)",
                        False,
                        10,
                    ),
                ],
            )
            await inter.response.send_modal(modal)
            await modal.wait()
            if modal.values:
                if "footer" in modal.values:
                    self.data["footer"] = (modal.values["footer"] or "").strip()
                if "footer_icon" in modal.values:
                    self.data["footer_icon"] = (
                        modal.values["footer_icon"] or ""
                    ).strip()
                ts = (modal.values.get("footer_timestamp") or "").lower().strip()
                self.data["footer_timestamp"] = (
                    "1" if ts in {"on", "yes", "true", "1", "y"} else "0"
                )
            await self.refresh()
            return

        labels = {
            "title": "Title",
            "description": "Description",
            "color": "Color hex (e.g. 5865F2)",
            "image": "Image URL",
            "thumbnail": "Thumbnail URL",
        }
        modal = _BuilderModal(
            f"Edit {labels.get(key, key)}",
            [
                (
                    key,
                    labels.get(key, key),
                    key in {"description"},
                    4000
                    if key == "description"
                    else 500
                    if key in {"image", "thumbnail"}
                    else 256,
                )
            ],
        )
        if self.data.get(key) and modal.children:
            child = modal.children[0]
            if isinstance(child, discord.ui.TextInput):
                child.default = (self.data[key] or "")[: child.max_length]
        await inter.response.send_modal(modal)
        await modal.wait()
        if modal.values and key in modal.values:
            self.data[key] = modal.values[key]
        await self.refresh()

    async def handle_approve(self, inter: discord.Interaction) -> None:
        script = self._to_script()
        label = "embed" if self.kind == "embed" else "container"
        paste = (
            "`,ce` / `,createembed`"
            if self.kind == "embed"
            else "`,cc` / `,createcontainer`"
        )
        dm_ok = False
        try:
            await inter.user.send(
                f"**Your {label} script** — paste with {paste}:\n```\n{script}\n```"
            )
            dm_ok = True
        except Exception:
            pass
        if dm_ok:
            await inter.response.send_message(
                "Script sent to your **DMs**. Live preview stays above.",
                ephemeral=True,
            )
        else:
            await inter.response.send_message(
                f"Could not DM you — script:\n```\n{script[:1800]}\n```",
                ephemeral=True,
            )
        self._stopped = True

    async def handle_cancel(self, inter: discord.Interaction) -> None:
        self._stopped = True
        name = "Embed" if self.kind == "embed" else "Container"
        try:
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
    header = _HEADER_EB


class ContainerBuilderView(_BaseBuilder):
    kind = "container"
    header = _HEADER_CB


async def register_builders(bot: "Vain") -> None:
    """Register ,embedbuilder / ,containerbuilder hybrid commands on the bot."""

    @hybrid(
        name="embedbuilder",
        aliases=["eb"],
        description="Interactive embed builder with live classic embed preview. Approve DMs the script.",
        example=",embedbuilder",
    )
    async def _run_eb(ctx: Context):
        builder = EmbedBuilderView(ctx.author.id)
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
        description="Interactive container builder with live visual container preview. Approve DMs the script.",
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

    bot.add_command(_run_eb)
    bot.add_command(_run_cb)
