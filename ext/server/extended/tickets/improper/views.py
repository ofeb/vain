from __future__ import annotations

import re
from typing import Any, Optional

import discord

from config import emojis

from ..settings import Settings


def _parse_emoji(value: str | None) -> discord.PartialEmoji | str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.match(r"<a?:(\w+):(\d+)>", text)
    if match:
        animated = text.startswith("<a:")
        return discord.PartialEmoji(
            name=match.group(1), id=int(match.group(2)), animated=animated
        )
    return text


def ticket_emoji(name: str, fallback: str) -> discord.PartialEmoji | str | None:
    raw = getattr(getattr(emojis, "ticket", None), name, None) or fallback
    return _parse_emoji(str(raw))


async def _ephemeral(
    interaction: discord.Interaction, content: str, *, followup: bool = False
) -> None:
    embed = discord.Embed(color=0x2B2D31, description=content)
    if followup or interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def require_ticket_staff(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await _ephemeral(interaction, "This can only be used in a server.")
        return False

    settings = await Settings.fetch(interaction.client, interaction.guild)
    if not settings.is_staff(interaction.user):
        await _ephemeral(
            interaction,
            "Only **ticket staff** can use these buttons.",
        )
        return False
    return True


class TicketControlView(discord.ui.View):
    """Persistent staff controls attached to every open ticket."""

    def __init__(self, cog: Optional[Any] = None) -> None:
        super().__init__(timeout=None)
        self.cog = cog

        
        self.clear_items()
        self.add_item(
            discord.ui.Button(
                label="Claim",
                style=discord.ButtonStyle.primary,
                custom_id="ticket:control:claim",
                emoji=ticket_emoji("claim", "🙋"),
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Close",
                style=discord.ButtonStyle.danger,
                custom_id="ticket:control:close",
                emoji=ticket_emoji("close", "🔒"),
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Transcript",
                style=discord.ButtonStyle.secondary,
                custom_id="ticket:control:transcript",
                emoji=ticket_emoji("transcript", "📄"),
            )
        )
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.callback = self._make_callback(child.custom_id or "")

    def _make_callback(self, custom_id: str):
        async def _callback(interaction: discord.Interaction) -> None:
            if not await require_ticket_staff(interaction):
                return
            cog = self._resolve_cog(interaction)
            if cog is None:
                await _ephemeral(interaction, "Ticket system is not loaded.")
                return
            if custom_id.endswith(":claim"):
                await cog.claim_ticket(interaction)
            elif custom_id.endswith(":close"):
                await cog.close_ticket(interaction)
            elif custom_id.endswith(":transcript"):
                await cog.transcript_ticket(interaction)

        return _callback

    def _resolve_cog(self, interaction: discord.Interaction) -> Any:
        if self.cog is not None:
            return self.cog
        get_cog = getattr(interaction.client, "get_cog", None)
        if callable(get_cog):
            return get_cog("Tickets")
        return None


class OpeningButtonEmojiSelect(discord.ui.LayoutView):
    """Pick which opening button to update the emoji for."""

    def __init__(self, cog: Any, buttons: list[dict]) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id: int | None = None
        self._buttons = buttons
        self._build()

    def _build(self) -> None:
        self.clear_items()
        container = discord.ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(discord.ui.TextDisplay("Select a ticket opening button to edit..."))

        chunks = [self._buttons[i:i + 25] for i in range(0, len(self._buttons), 25)]
        for idx, chunk in enumerate(chunks):
            options = []
            for row in chunk:
                label = str(row.get("label") or row.get("id") or "Button")[:100]
                emoji = _parse_emoji(row.get("emoji"))
                options.append(
                    discord.SelectOption(
                        label=label,
                        value=str(row["id"]),
                        description=f"id: {row['id']}"[:100],
                        emoji=emoji,
                    )
                )
            row = discord.ui.ActionRow()
            ph = "Select a button..."
            if len(chunks) > 1:
                ph = f"{ph} ({idx + 1}/{len(chunks)})"
            select = discord.ui.Select(
                placeholder=ph,
                min_values=1,
                max_values=1,
                options=options,
            )

            async def _cb(interaction: discord.Interaction, _sel: discord.ui.Select = select) -> None:
                if self.author_id and interaction.user.id != self.author_id:
                    await interaction.response.send_message("Not for you.", ephemeral=True)
                    return
                button_id = _sel.values[0]
                await interaction.response.send_modal(
                    OpeningButtonEmojiModal(self.cog, button_id)
                )

            select.callback = _cb
            row.add_item(select)
            container.add_item(row)
        self.add_item(container)

    async def start(self, ctx) -> None:
        self.author_id = ctx.author.id
        msg = await ctx.send(view=self)
        await self.wait()
        with contextlib.suppress(discord.HTTPException):
            await msg.edit(view=None)


class OpeningButtonEmojiModal(discord.ui.Modal, title="Set button emoji"):
    emoji = discord.ui.TextInput(
        label="Emoji",
        placeholder="🎫 or <:name:id>  (leave empty to clear)",
        required=False,
        max_length=100,
    )

    def __init__(self, cog: Any, button_id: str) -> None:
        super().__init__()
        self.cog = cog
        self.button_id = button_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.set_opening_button_emoji(
            interaction, self.button_id, str(self.emoji.value or "").strip() or None
        )


class OpeningButtonEmojiView(discord.ui.View):
    def __init__(self, cog: Any, buttons: list[dict]) -> None:
        super().__init__(timeout=120)
        self.add_item(OpeningButtonEmojiSelect(cog, buttons))


class OpeningButtonAddModal(discord.ui.Modal, title="Add ticket opening button"):
    label = discord.ui.TextInput(
        label="Label",
        placeholder="Open Ticket",
        default="Open Ticket",
        required=True,
        max_length=80,
    )
    emoji = discord.ui.TextInput(
        label="Emoji (optional)",
        placeholder="🎫 or <:name:id>",
        required=False,
        max_length=100,
    )
    style = discord.ui.TextInput(
        label="Style",
        placeholder="green / blurple / grey / red",
        default="green",
        required=False,
        max_length=16,
    )
    identifier = discord.ui.TextInput(
        label="Identifier (optional)",
        placeholder="support",
        required=False,
        max_length=32,
    )

    def __init__(self, cog: Any) -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.add_opening_button_from_modal(
            interaction,
            label=str(self.label.value).strip(),
            emoji=str(self.emoji.value or "").strip() or None,
            style=str(self.style.value or "green").strip().lower(),
            identifier=str(self.identifier.value or "").strip() or None,
        )


STYLE_MAP = {
    "blurple": discord.ButtonStyle.primary,
    "primary": discord.ButtonStyle.primary,
    "grey": discord.ButtonStyle.secondary,
    "gray": discord.ButtonStyle.secondary,
    "secondary": discord.ButtonStyle.secondary,
    "green": discord.ButtonStyle.success,
    "success": discord.ButtonStyle.success,
    "red": discord.ButtonStyle.danger,
    "danger": discord.ButtonStyle.danger,
}


class TicketOpenView(discord.ui.View):
    """Persistent panel view that registers opening buttons/dropdowns for bot.add_view()."""

    def __init__(self, cog: Any, panel_id: int, options: list[dict], panel_type: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.panel_id = panel_id
        self.options = options
        self.panel_type = panel_type

        if panel_type == "dropdown":
            chunks = [options[i:i + 25] for i in range(0, len(options), 25)]
            for idx, chunk in enumerate(chunks):
                ph = "Select an option to open a ticket..."
                if len(chunks) > 1:
                    ph = f"{ph} ({idx + 1}/{len(chunks)})"
                select = discord.ui.Select(
                    custom_id=f"ticket.create:{panel_id}:{idx}" if len(chunks) > 1 else f"ticket.create:{panel_id}",
                    placeholder=ph,
                    min_values=1,
                    max_values=1,
                    options=[
                        discord.SelectOption(
                            label=(str(opt.get("label") or opt.get("id") or "Option"))[:100],
                            value=(str(opt.get("id") or opt.get("label")))[:100],
                            description=((opt.get("description") or "")[:100]) or None,
                            emoji=_parse_emoji(opt.get("emoji")),
                        )
                        for opt in chunk
                    ],
                )
                select.callback = self._dropdown_callback
                self.add_item(select)
        else:
            for opt in options:
                label = str(opt.get("label") or opt.get("id") or "Open Ticket")[:80]
                emoji = _parse_emoji(opt.get("emoji"))
                style_str = str(opt.get("style") or "green").lower()
                style = STYLE_MAP.get(style_str, discord.ButtonStyle.success)
                identifier = str(opt.get("id") or label).lower().replace(" ", "_")
                button = discord.ui.Button(
                    label=label,
                    style=style,
                    custom_id=f"ticket.create:{identifier}",
                    emoji=emoji,
                )
                button.callback = self._button_callback
                self.add_item(button)

    async def _button_callback(self, interaction: discord.Interaction) -> None:
        pass

    async def _dropdown_callback(self, interaction: discord.Interaction) -> None:
        pass
