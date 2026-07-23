from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import discord

from config import color

if TYPE_CHECKING:
    from ext.tickets import Tickets


def _parse_emoji(value: str | None) -> discord.PartialEmoji | str | None:
    if not value:
        return None
    match = re.match(r"<a?:(\w+):(\d+)>", value)
    if match:
        animated = value.startswith("<a:")
        return discord.PartialEmoji(name=match.group(1), id=int(match.group(2)), animated=animated)
    return value


class TicketOpenView(discord.ui.View):
    def __init__(self, cog: "Tickets", panel_id: int, options: list[dict], panel_type: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.panel_id = panel_id
        if panel_type == "dropdown" and options:
            self.add_item(TicketSelect(cog, panel_id, options))
        else:
            for option in options[:25]:
                self.add_item(TicketOpenButton(cog, panel_id, option))


class TicketOpenButton(discord.ui.Button):
    def __init__(self, cog: "Tickets", panel_id: int, option: dict) -> None:
        emoji = _parse_emoji(option.get("emoji"))
        super().__init__(
            label=str(option.get("label") or option.get("name"))[:80],
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id=f"ticket:open:{panel_id}:{option['id']}",
        )
        self.cog = cog
        self.panel_id = panel_id
        self.option_id = int(option["id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.open_ticket(interaction, self.panel_id, self.option_id)


class TicketSelect(discord.ui.Select):
    def __init__(self, cog: "Tickets", panel_id: int, options: list[dict]) -> None:
        select_options = []
        for option in options[:25]:
            emoji = _parse_emoji(option.get("emoji"))
            select_options.append(
                discord.SelectOption(
                    label=str(option.get("label") or option.get("name"))[:100],
                    description=(option.get("description") or "")[:100] or None,
                    emoji=emoji,
                    value=str(option["id"]),
                )
            )
        super().__init__(
            placeholder="Select a ticket type",
            min_values=1,
            max_values=1,
            options=select_options,
            custom_id=f"ticket:select:{panel_id}",
        )
        self.cog = cog
        self.panel_id = panel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.open_ticket(interaction, self.panel_id, int(self.values[0]))


class TicketControlView(discord.ui.View):
    def __init__(self, cog: "Tickets") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, custom_id="ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.claim_ticket(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.close_ticket(interaction)

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, custom_id="ticket:transcript")
    async def transcript(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.transcript_ticket(interaction)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="ticket:delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.delete_ticket(interaction)


class TicketFormModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Tickets",
        panel_id: int,
        option_id: int,
        questions: list[dict],
    ) -> None:
        title = "Ticket Questions"
        super().__init__(title=title[:45])
        self.cog = cog
        self.panel_id = panel_id
        self.option_id = option_id
        self.question_keys: list[str] = []
        for index, question in enumerate(questions[:5]):
            key = str(question.get("key") or f"q{index + 1}")
            self.question_keys.append(key)
            self.add_item(
                discord.ui.TextInput(
                    label=str(question.get("label") or key)[:45],
                    placeholder=str(question.get("placeholder") or "")[:100] or None,
                    required=bool(question.get("required", True)),
                    style=discord.TextStyle.paragraph if question.get("long") else discord.TextStyle.short,
                    max_length=1024,
                )
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        answers = {
            key: child.value
            for key, child in zip(self.question_keys, self.children)
            if isinstance(child, discord.ui.TextInput)
        }
        await self.cog.create_ticket_channel(
            interaction,
            self.panel_id,
            self.option_id,
            answers,
        )
