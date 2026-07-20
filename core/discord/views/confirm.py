"""Yes/no confirmation view (Approve / Deny).

Matches the booster-ban style: only the invoker can click, buttons use
approve/deny emojis, prompt can be a plain string or an embed.
"""

from __future__ import annotations

import contextlib

import discord
from discord.ext.commands import Context

from core.managers.values import color, emojis


def _confirm_embed(message: str) -> discord.Embed:
    return discord.Embed(
        color=color.base,
        description=f"> {message}",
    )


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

        def _emoji(raw: str | None):
            if not raw:
                return None
            try:
                return discord.PartialEmoji.from_str(str(raw))
            except Exception:
                return None

        approve = discord.ui.Button(
            label="Approve",
            style=discord.ButtonStyle.success,
            emoji=_emoji(getattr(emojis, "approve", None)),
        )
        deny = discord.ui.Button(
            label="Deny",
            style=discord.ButtonStyle.danger,
            emoji=_emoji(getattr(emojis, "deny", None)),
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
    ) -> bool:
        """Send the prompt and wait for Approve / Deny. Returns True if approved."""
        if embed is None:
            embed = _confirm_embed(
                message or "Are you sure you want to do this?"
            )
        self.message = await self.ctx.send(embed=embed, view=self)
        await self.wait()
        if delete_after and self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.delete()
        return bool(self.value)
