from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import discord
from discord import ui

from core.discord.ctx import layout_from_items

if TYPE_CHECKING:
    from . import VoiceMaster

VM = {
    "claim": "<:voicemaster_claim:1539664937188597810>",
    "delete": "<:voicemaster_delete:1539664938673635428>",
    "disconnect": "<:voicemaster_disconnect:1539664940112019577>",
    "hide": "<:voicemaster_hide:1539664941714383023>",
    "limit": "<:voicemaster_limit:1539664942645518500>",
    "lock": "<:voicemaster_lock:1539664944293740646>",
    "rename": "<:voicemaster_rename:1539664945346781205>",
    "unlock": "<:voicemaster_unlock:1539664948236390450>",
    "reveal": "<:voicemaster_reveal:1539664946957262989>",
    "status": "<:voicemaster_status:1539689399896375336>",
}


def _clear(container: ui.Container) -> None:
    for attr in ("accent_color", "accent_colour"):
        if hasattr(container, attr):
            with contextlib.suppress(Exception):
                setattr(container, attr, None)


def _container_msg(text: str, *, mention: str = "") -> ui.LayoutView:
    c = ui.Container()
    _clear(c)
    c.add_item(ui.TextDisplay(text))
    if mention:
        c.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        c.add_item(ui.TextDisplay(mention))
    return layout_from_items([c], timeout=None)


async def _reply(interaction: discord.Interaction, *, view: ui.LayoutView) -> None:
    with contextlib.suppress(discord.InteractionResponded):
        await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(view=view, ephemeral=True)


def _kick_response(
    interaction: discord.Interaction,
    count: int,
    members: list[discord.Member],
) -> ui.LayoutView:
    word = "user" if count == 1 else "users"
    mentions = " ".join(m.mention for m in members)
    return _container_msg(
        f"{interaction.user.mention}: i have **kicked** the {word} from your voice channel",
        mention=mentions,
    )


class StatusModal(ui.Modal, title="Channel Status"):
    status_text = ui.TextInput(
        label="Status text",
        placeholder="e.g. vibing, gaming, chill session",
        max_length=100,
        required=False,
    )
    status_emoji = ui.TextInput(
        label="Emoji",
        placeholder="e.g. 🎵, 🎮, 🎧",
        max_length=20,
        required=False,
    )
    save_future = ui.TextInput(
        label="Save for future channels? (yes/no)",
        placeholder="yes or no",
        max_length=3,
        required=False,
    )

    def __init__(self, *, current_text: str = "", current_emoji: str = "") -> None:
        super().__init__()
        if current_text:
            self.status_text.default = current_text
        if current_emoji:
            self.status_emoji.default = current_emoji


class DisconnectMembers(ui.Select):
    def __init__(self, member: discord.Member, cog: "VoiceMaster") -> None:
        self.member = member
        self.guild = member.guild
        self.channel = member.voice.channel
        self.cog = cog
        super().__init__(
            placeholder="Choose members...",
            min_values=1,
            max_values=len(self.channel.members),
            options=[
                discord.SelectOption(
                    value=str(m.id),
                    label=f"{m} ({m.id})",
                    emoji="👤",
                )
                for m in self.channel.members
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        disconnected: list[discord.Member] = []
        for raw_id in self.values:
            target = self.guild.get_member(int(raw_id))
            if target is None or target.voice is None or target.voice.channel != self.channel:
                continue
            try:
                await target.move_to(None)
                disconnected.append(target)
            except discord.HTTPException:
                pass
        await _reply(interaction, view=_kick_response(interaction, len(disconnected), disconnected))


class VoiceInterface(ui.View):
    def __init__(self, cog: "VoiceMaster") -> None:
        self.cog = cog
        super().__init__(timeout=None)

    async def _get_owner_id(self, channel_id: int) -> int | None:
        return await self.cog.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster_channels WHERE channel_id = $1",
            channel_id,
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        if not isinstance(user, discord.Member) or user.voice is None or user.voice.channel is None:
            await _reply(interaction, view=_container_msg(f"{user.mention}: you're not connected to a **voice channel**"))
            return False

        owner_id = await self._get_owner_id(user.voice.channel.id)
        if not owner_id:
            await _reply(interaction, view=_container_msg(f"{user.mention}: you're not in a **voicemaster** channel"))
            return False

        custom_id = (interaction.data or {}).get("custom_id")
        if custom_id == "voicemaster:claim":
            if user.id == owner_id:
                await _reply(interaction, view=_container_msg(f"{user.mention}: you already **own** this voice channel"))
                return False
            if owner_id in (m.id for m in user.voice.channel.members):
                await _reply(interaction, view=_container_msg(f"{user.mention}: you can't claim this channel, the owner is still here"))
                return False
            return True

        if user.id != owner_id:
            await _reply(interaction, view=_container_msg(f"{user.mention}: you **don't** own this voice channel"))
            return False

        return True

    @ui.button(emoji=VM["claim"], custom_id="voicemaster:claim")
    async def claim(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel = interaction.user.voice.channel
        await self.cog.bot.db.execute(
            "UPDATE voicemaster_channels SET owner_id = $2 WHERE channel_id = $1",
            channel.id, interaction.user.id,
        )
        if channel.name.endswith("channel"):
            with contextlib.suppress(discord.HTTPException):
                await channel.edit(name=f"{interaction.user.display_name}'s channel")
        await _reply(interaction, view=_container_msg(f"{interaction.user.mention}: you are now the **owner** of this channel"))

    @ui.button(emoji=VM["delete"], custom_id="voicemaster:delete")
    async def delete(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel = interaction.user.voice.channel
        await self.cog.bot.db.execute(
            "DELETE FROM voicemaster_channels WHERE channel_id = $1", channel.id,
        )
        with contextlib.suppress(discord.HTTPException):
            await channel.delete()
        await _reply(interaction, view=_container_msg(f"{interaction.user.mention}: your voice channel has been **deleted**"))

    @ui.button(emoji=VM["disconnect"], custom_id="voicemaster:disconnect")
    async def disconnect(self, interaction: discord.Interaction, button: ui.Button) -> None:
        view = ui.LayoutView(timeout=None)
        view.add_item(DisconnectMembers(interaction.user, self.cog))
        await _reply(interaction, view=view)

    @ui.button(emoji=VM["hide"], custom_id="voicemaster:hide")
    async def hide(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel = interaction.user.voice.channel
        await channel.set_permissions(
            interaction.guild.default_role, view_channel=False,
            reason=f"VoiceMaster: {interaction.user} hid channel",
        )
        await _reply(interaction, view=_container_msg(f"{interaction.user.mention}: your voice channel has been **hidden**"))

    @ui.button(emoji=VM["reveal"], custom_id="voicemaster:reveal")
    async def reveal(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel = interaction.user.voice.channel
        await channel.set_permissions(
            interaction.guild.default_role, view_channel=None,
            reason=f"VoiceMaster: {interaction.user} revealed channel",
        )
        await _reply(interaction, view=_container_msg(f"{interaction.user.mention}: your voice channel has been **revealed**"))

    @ui.button(emoji=VM["limit"], custom_id="voicemaster:limit")
    async def limit(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel = interaction.user.voice.channel
        current = channel.user_limit or 0
        if current >= 99:
            await _reply(interaction, view=_container_msg(f"{interaction.user.mention}: limit can't exceed **99 members**"))
            return
        await channel.edit(user_limit=current + 1, reason=f"VoiceMaster: {interaction.user} increased limit")
        await _reply(interaction, view=_container_msg(f"{interaction.user.mention}: limit updated to **{current + 1}**"))

    @ui.button(emoji=VM["lock"], custom_id="voicemaster:lock")
    async def lock(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel = interaction.user.voice.channel
        await channel.set_permissions(
            interaction.guild.default_role, connect=False,
            reason=f"VoiceMaster: {interaction.user} locked channel",
        )
        await _reply(interaction, view=_container_msg(f"{interaction.user.mention}: your voice channel has been **locked**"))

    @ui.button(emoji=VM["unlock"], custom_id="voicemaster:unlock")
    async def unlock(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel = interaction.user.voice.channel
        await channel.set_permissions(
            interaction.guild.default_role, connect=None,
            reason=f"VoiceMaster: {interaction.user} unlocked channel",
        )
        await _reply(interaction, view=_container_msg(f"{interaction.user.mention}: your voice channel has been **unlocked**"))

    @ui.button(emoji=VM["rename"], custom_id="voicemaster:rename")
    async def rename(self, interaction: discord.Interaction, button: ui.Button) -> None:
        modal = ui.Modal(title="Rename Channel")
        name_input = ui.TextInput(label="New name", placeholder="enter channel name...", max_length=100)
        modal.add_item(name_input)

        async def cb(mi: discord.Interaction) -> None:
            new_name = name_input.value.strip()
            if not new_name:
                await mi.response.send_message("name cannot be empty", ephemeral=True)
                return
            ch = interaction.user.voice.channel
            await ch.edit(name=new_name, reason=f"VoiceMaster: {interaction.user} renamed")
            await _reply(mi, view=_container_msg(f"{mi.user.mention}: channel renamed to **{new_name}**"))

        modal.on_submit = cb
        await interaction.response.send_modal(modal)

    @ui.button(emoji=VM["status"], custom_id="voicemaster:status")
    async def status(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel = interaction.user.voice.channel
        row = await self.cog.bot.db.fetchrow(
            "SELECT status_text, status_emoji FROM voicemaster_channels WHERE channel_id = $1",
            channel.id,
        )
        current_text = row["status_text"] if row else ""
        current_emoji = row["status_emoji"] if row else ""
        modal = StatusModal(current_text=current_text or "", current_emoji=current_emoji or "")

        async def cb(mi: discord.Interaction) -> None:
            text = modal.status_text.value.strip() if modal.status_text.value else ""
            emoji = modal.status_emoji.value.strip() if modal.status_emoji.value else ""
            save = modal.save_future.value.strip().lower() in ("yes", "y", "true", "1") if modal.save_future.value else False

            await self.cog.bot.db.execute(
                "UPDATE voicemaster_channels SET status_text = $1, status_emoji = $2 WHERE channel_id = $3",
                text, emoji, channel.id,
            )

            if save:
                await self.cog.bot.db.execute(
                    "UPDATE voicemaster_configuration SET default_status_text = $1, default_status_emoji = $2 WHERE guild_id = $3",
                    text, emoji, interaction.guild.id,
                )

            parts = []
            if emoji and text:
                parts.append(f"{emoji} {text}")
            elif text:
                parts.append(text)
            elif emoji:
                parts.append(emoji)
            else:
                parts.append("status **cleared**")

            display = parts[0]
            await _reply(mi, view=_container_msg(f"{mi.user.mention}: channel status set to **{display}**"))

        modal.on_submit = cb
        await interaction.response.send_modal(modal)
