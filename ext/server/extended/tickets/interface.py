from __future__ import annotations

from discord import ActionRow, Message
from discord.components import Button as ButtonComponent
from discord.components import SelectMenu as SelectMenuComponent
from discord.ui import Button, Select, View


class Interface(View):
    """Rebuild a panel view from an existing message's components."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @classmethod
    def from_message(cls, message: Message, /, **kwargs: object) -> "Interface":
        
        _ = kwargs
        view = cls()
        for component in message.components:
            if not isinstance(component, ActionRow):
                continue
            for child in component.children:
                if isinstance(child, ButtonComponent):
                    view.add_item(Button.from_component(child))
                elif isinstance(child, SelectMenuComponent):
                    view.add_item(Select.from_component(child))
        return view

    def buttons(self) -> list[Button]:
        return [c for c in self.children if isinstance(c, Button)]

    def selects(self) -> list[Select]:
        return [c for c in self.children if isinstance(c, Select)]

    def ticket_buttons(self) -> list[Button]:
        out: list[Button] = []
        for button in self.buttons():
            cid = button.custom_id or ""
            if cid.startswith("ticket.create"):
                out.append(button)
        return out
