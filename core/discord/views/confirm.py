"""Yes/no confirmation view (Approve / Deny).

C2 container style: blue approve, red deny, no emojis.
"""

from __future__ import annotations

import asyncio

import contextlib
from enum import Enum

import discord
from discord import ui
from discord.ext.commands import Context

from config import color


def _build_confirm_layout(message: str) -> ui.LayoutView:
    """Build a C2 layout with the message text inside the container."""
    container = ui.Container()
    for attr in ("accent_color", "accent_colour", "color", "colour"):
        if hasattr(container, attr):
            with contextlib.suppress(Exception):
                setattr(container, attr, None)
    container.add_item(ui.TextDisplay(message or "Are you sure you want to do this?"))
    
    view = ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


def _build_confirm_layout(message: str) -> ui.LayoutView:
    """Build a C2 layout with the message text inside the container."""
    container = ui.Container()
    for attr in ("accent_color", "accent_colour", "color", "colour"):
        if hasattr(container, attr):
            with contextlib.suppress(Exception):
                setattr(container, attr, None)
    container.add_item(ui.TextDisplay(message or "Are you sure you want to do this?"))
    return ui.LayoutView(timeout=None, items=[container])


class ConfirmView(discord.ui.View):
    """Two-button Approve / Deny confirmation (invoker-only)."""

    def __init__(
        self,
        ctx: Context,
        *,
        member: discord.abc.User | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.member = member or ctx.author
        self.value: bool | None = None
        self.message: discord.Message | None = None

        self.clear_items()

        approve = discord.ui.Button(
            label="Approve",
            style=discord.ButtonStyle.primary,
        )
        deny = discord.ui.Button(
            label="Deny",
            style=discord.ButtonStyle.danger,
        )
        approve.callback = self._approve  # type: ignore[method-assign]
        deny.callback = self._deny  # type: ignore[method-assign]
        self.add_item(approve)
        self.add_item(deny)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.member.id:
            await inter.response.send_message(
                f"Only {self.member.mention} can use this.",
                ephemeral=True,
            )
            return False
        return True

    async def _approve(self, inter: discord.Interaction) -> None:
        self.value = True
        await inter.response.defer()
        self.stop()

    async def _deny(self, inter: discord.Interaction) -> None:
        self.value = False
        await inter.response.defer()
        self.stop()

    async def on_timeout(self) -> None:
        self.value = False
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.delete()

    async def prompt(
        self,
        message: str | None = None,
        *,
        embed: discord.Embed | None = None,
        delete_after: bool = True,
        cancel_message: str | None = "Cancelled",
    ) -> bool:
        """Send the prompt and wait for Approve / Deny. Returns True if approved."""
        display_message = message or "Are you sure you want to do this?"
        layout = _build_confirm_layout(display_message)
        self.message = await self.ctx.send(view=layout)
        with contextlib.suppress(discord.HTTPException, Exception):
            await self.message.edit(view=self)
        await self.wait()
        approved = bool(self.value)
        if delete_after and self.message is not None:
            if not approved and cancel_message:
                with contextlib.suppress(Exception):
                    await self.message.edit(
                        embed=self._cancel_warn_embed(cancel_message),
                        view=None,
                    )
                    await asyncio.sleep(5)
            with contextlib.suppress(discord.HTTPException, Exception):
                await self.message.delete()
        return approved

    def _cancel_warn_embed(self, message: str) -> discord.Embed:
        from core.discord.views.embed import reply_embed
        from config import emojis
        emoji = getattr(emojis, "warn", None) or ""
        mention = getattr(self.ctx.author, "mention", "")
        body = f"{emoji} {mention}: {message}".strip()
        emb = reply_embed(message=body)
        try:
            emb.color = int(getattr(color, "warn", 0) or 0) or None
        except Exception:
            pass
        return emb



class ConfirmChoice(Enum):
    APPROVE = "approve"
    DENY = "deny"
    CANCEL = "cancel"


class ThreeButtonConfirmView(discord.ui.View):
    """Three-button Approve / Deny / Cancel confirmation (invoker-only)."""

    def __init__(
        self,
        ctx: Context,
        *,
        member: discord.abc.User | None = None,
        timeout: float = 30.0,
        show_cancel: bool = False,
    ) -> None:
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.member = member or ctx.author
        self.value: ConfirmChoice | None = None
        self.message: discord.Message | None = None
        self._show_cancel = show_cancel

        self.clear_items()

        approve = discord.ui.Button(
            label="Approve",
            style=discord.ButtonStyle.primary,
        )
        deny = discord.ui.Button(
            label="Deny",
            style=discord.ButtonStyle.danger,
        )
        approve.callback = self._approve
        deny.callback = self._deny
        self.add_item(approve)
        self.add_item(deny)

        if show_cancel:
            cancel = discord.ui.Button(
                label="Cancel",
                style=discord.ButtonStyle.danger,
            )
            cancel.callback = self._cancel
            self.add_item(cancel)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.member.id:
            await inter.response.send_message(
                f"Only {self.member.mention} can use this.",
                ephemeral=True,
            )
            return False
        return True

    async def _approve(self, inter: discord.Interaction) -> None:
        self.value = ConfirmChoice.APPROVE
        await inter.response.defer()
        self.stop()

    async def _deny(self, inter: discord.Interaction) -> None:
        self.value = ConfirmChoice.DENY
        await inter.response.defer()
        self.stop()

    async def _cancel(self, inter: discord.Interaction) -> None:
        self.value = ConfirmChoice.CANCEL
        await inter.response.defer()
        self.stop()

    async def on_timeout(self) -> None:
        self.value = ConfirmChoice.CANCEL
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.delete()

    async def prompt(
        self,
        message: str | None = None,
        *,
        embed: discord.Embed | None = None,
        delete_after: bool = True,
        cancel_message: str | None = "Cancelled",
    ) -> ConfirmChoice:
        """Send the prompt and wait for Approve / Deny / Cancel. Returns ConfirmChoice."""
        display_message = message or "Are you sure you want to do this?"
        layout = _build_confirm_layout(display_message)
        self.message = await self.ctx.send(view=layout)
        with contextlib.suppress(discord.HTTPException, Exception):
            await self.message.edit(view=self)
        await self.wait()
        result = self.value or ConfirmChoice.CANCEL
        if delete_after and self.message is not None:
            if result != ConfirmChoice.APPROVE and cancel_message:
                with contextlib.suppress(Exception):
                    from core.discord.views.embed import reply_embed
                    from config import emojis
                    emoji = getattr(emojis, "warn", None) or ""
                    mention = getattr(self.ctx.author, "mention", "")
                    body = f"{emoji} {mention}: {cancel_message}".strip()
                    emb = reply_embed(message=body)
                    try:
                        emb.color = int(getattr(color, "warn", 0) or 0) or None
                    except Exception:
                        pass
                    await self.message.edit(embed=emb, view=None)
                    await asyncio.sleep(5)
            with contextlib.suppress(discord.HTTPException, Exception):
                await self.message.delete()
        return result
