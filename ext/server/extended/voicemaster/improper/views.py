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
    container = ui.Container()
    _clear(container)
    container.add_item(ui.TextDisplay(text))

    if mention:
        container.add_item(
            ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            )
        )
        container.add_item(ui.TextDisplay(mention))

    return layout_from_items([container], timeout=None)


async def _reply(
    interaction: discord.Interaction,
    *,
    view: ui.LayoutView,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(
            view=view,
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        view=view,
        ephemeral=True,
    )


def _kick_response(
    interaction: discord.Interaction,
    count: int,
    members: list[discord.Member],
) -> ui.LayoutView:
    word = "user" if count == 1 else "users"
    mentions = " ".join(member.mention for member in members)

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

    def __init__(
        self,
        *,
        current_text: str = "",
        current_emoji: str = "",
    ) -> None:
        super().__init__()

        if current_text:
            self.status_text.default = current_text

        if current_emoji:
            self.status_emoji.default = current_emoji


class DisconnectMembers(ui.Select):
    def __init__(
        self,
        member: discord.Member,
        cog: "VoiceMaster",
    ) -> None:
        self.member = member
        self.guild = member.guild
        self.channel = member.voice.channel
        self.cog = cog

        members = list(self.channel.members)

        super().__init__(
            placeholder="Choose members...",
            min_values=1,
            max_values=max(1, len(members)),
            options=[
                discord.SelectOption(
                    value=str(target.id),
                    label=f"{target} ({target.id})",
                    emoji="👤",
                )
                for target in members
            ],
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        disconnected: list[discord.Member] = []

        for raw_id in self.values:
            target = self.guild.get_member(int(raw_id))

            if (
                target is None
                or target.voice is None
                or target.voice.channel != self.channel
            ):
                continue

            try:
                await target.move_to(None)
                disconnected.append(target)
            except discord.HTTPException:
                continue

        await _reply(
            interaction,
            view=_kick_response(
                interaction,
                len(disconnected),
                disconnected,
            ),
        )


class VoiceInterface(ui.LayoutView):
    def __init__(
        self,
        cog: "VoiceMaster",
        guild: discord.Guild,
    ) -> None:
        self.cog = cog
        self.guild = guild

        super().__init__(timeout=None)

        self._build()

    def _build(self) -> None:
        container = ui.Container()
        _clear(container)

        server_icon = self.guild.icon.url if self.guild.icon else None

        header = (
            f"## {self.guild.name}\n"
            f"-# Manage temporary voice channels in **{self.guild.name}**."
        )

        if server_icon:
            container.add_item(
                ui.Section(
                    ui.TextDisplay(header),
                    accessory=ui.Thumbnail(
                        media=server_icon,
                    ),
                )
            )
        else:
            container.add_item(
                ui.TextDisplay(header),
            )

        container.add_item(
            ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            )
        )

        controls = (
            "### Controls\n"
            f"{VM['claim']} — **Claim** the channel\n"
            f"{VM['delete']} — **Delete** the channel\n"
            f"{VM['disconnect']} — **Disconnect** member(s)\n"
            f"{VM['hide']} — **Hide** the channel\n"
            f"{VM['reveal']} — **Reveal** the channel\n"
            f"{VM['limit']} — Set a user **limit**\n"
            f"{VM['lock']} — **Lock** the channel\n"
            f"{VM['unlock']} — **Unlock** the channel\n"
            f"{VM['rename']} — **Rename** the channel"
        )

        if server_icon:
            container.add_item(
                ui.Section(
                    ui.TextDisplay(controls),
                    accessory=ui.Thumbnail(
                        media=server_icon,
                    ),
                )
            )
        else:
            container.add_item(
                ui.TextDisplay(controls),
            )

        container.add_item(
            ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            )
        )

        buttons = {
            "claim": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["claim"],
                custom_id="voicemaster:claim",
            ),
            "delete": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["delete"],
                custom_id="voicemaster:delete",
            ),
            "disconnect": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["disconnect"],
                custom_id="voicemaster:disconnect",
            ),
            "hide": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["hide"],
                custom_id="voicemaster:hide",
            ),
            "reveal": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["reveal"],
                custom_id="voicemaster:reveal",
            ),
            "limit": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["limit"],
                custom_id="voicemaster:limit",
            ),
            "lock": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["lock"],
                custom_id="voicemaster:lock",
            ),
            "unlock": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["unlock"],
                custom_id="voicemaster:unlock",
            ),
            "rename": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["rename"],
                custom_id="voicemaster:rename",
            ),
            "status": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["status"],
                custom_id="voicemaster:status",
            ),
        }

        buttons["claim"].callback = self._claim
        buttons["delete"].callback = self._delete
        buttons["disconnect"].callback = self._disconnect
        buttons["hide"].callback = self._hide
        buttons["reveal"].callback = self._reveal
        buttons["limit"].callback = self._limit
        buttons["lock"].callback = self._lock
        buttons["unlock"].callback = self._unlock
        buttons["rename"].callback = self._rename
        buttons["status"].callback = self._status

        row1 = ui.ActionRow(
            buttons["lock"],
            buttons["unlock"],
            buttons["claim"],
            buttons["delete"],
            buttons["disconnect"],
        )

        row2 = ui.ActionRow(
            buttons["hide"],
            buttons["reveal"],
            buttons["limit"],
            buttons["rename"],
            buttons["status"],
        )

        container.add_item(row1)
        container.add_item(row2)

        container.add_item(
            ui.TextDisplay(
                "-# You must own the voice channel to use these controls."
            )
        )

        self.add_item(container)

    async def _get_owner_id(
        self,
        channel_id: int,
    ) -> int | None:
        return await self.cog.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster_channels WHERE channel_id = $1",
            channel_id,
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        user = interaction.user

        if (
            not isinstance(user, discord.Member)
            or user.voice is None
            or user.voice.channel is None
        ):
            await _reply(
                interaction,
                view=_container_msg(
                    f"{user.mention}: you're not connected to a **voice channel**"
                ),
            )
            return False

        owner_id = await self._get_owner_id(
            user.voice.channel.id,
        )

        if not owner_id:
            await _reply(
                interaction,
                view=_container_msg(
                    f"{user.mention}: you're not in a **voicemaster** channel"
                ),
            )
            return False

        custom_id = (interaction.data or {}).get("custom_id")

        if custom_id == "voicemaster:claim":
            if user.id == owner_id:
                await _reply(
                    interaction,
                    view=_container_msg(
                        f"{user.mention}: you already **own** this voice channel"
                    ),
                )
                return False

            if owner_id in (
                member.id
                for member in user.voice.channel.members
            ):
                await _reply(
                    interaction,
                    view=_container_msg(
                        f"{user.mention}: you can't claim this channel, "
                        "the owner is still here"
                    ),
                )
                return False

            return True

        if user.id != owner_id:
            await _reply(
                interaction,
                view=_container_msg(
                    f"{user.mention}: you **don't** own this voice channel"
                ),
            )
            return False

        return True

    async def _claim(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel

        await self.cog.bot.db.execute(
            "UPDATE voicemaster_channels SET owner_id = $2 WHERE channel_id = $1",
            channel.id,
            interaction.user.id,
        )

        if channel.name.endswith("channel"):
            with contextlib.suppress(discord.HTTPException):
                await channel.edit(
                    name=f"{interaction.user.display_name}'s channel",
                )

        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.mention}: you are now the **owner** of this channel"
            ),
        )

    async def _delete(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel

        await self.cog.bot.db.execute(
            "DELETE FROM voicemaster_channels WHERE channel_id = $1",
            channel.id,
        )

        with contextlib.suppress(discord.HTTPException):
            await channel.delete()

        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.mention}: your voice channel has been **deleted**"
            ),
        )

    async def _disconnect(
        self,
        interaction: discord.Interaction,
    ) -> None:
        container = ui.Container()
        _clear(container)

        container.add_item(
            ui.TextDisplay(
                f"{interaction.user.mention}: choose members to **disconnect**"
            )
        )

        row = ui.ActionRow()
        row.add_item(
            DisconnectMembers(
                interaction.user,
                self.cog,
            )
        )

        container.add_item(row)

        view = ui.LayoutView(timeout=None)
        view.add_item(container)

        await _reply(
            interaction,
            view=view,
        )

    async def _hide(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel

        await channel.set_permissions(
            interaction.guild.default_role,
            view_channel=False,
            reason=f"VoiceMaster: {interaction.user} hid channel",
        )

        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.mention}: your voice channel has been **hidden**"
            ),
        )

    async def _reveal(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel

        await channel.set_permissions(
            interaction.guild.default_role,
            view_channel=None,
            reason=f"VoiceMaster: {interaction.user} revealed channel",
        )

        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.mention}: your voice channel has been **revealed**"
            ),
        )

    async def _limit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel
        current = channel.user_limit or 0

        if current >= 99:
            await _reply(
                interaction,
                view=_container_msg(
                    f"{interaction.user.mention}: limit can't exceed **99 members**"
                ),
            )
            return

        await channel.edit(
            user_limit=current + 1,
            reason=f"VoiceMaster: {interaction.user} increased limit",
        )

        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.mention}: limit updated to **{current + 1}**"
            ),
        )

    async def _lock(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel

        await channel.set_permissions(
            interaction.guild.default_role,
            connect=False,
            reason=f"VoiceMaster: {interaction.user} locked channel",
        )

        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.mention}: your voice channel has been **locked**"
            ),
        )

    async def _unlock(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel

        await channel.set_permissions(
            interaction.guild.default_role,
            connect=None,
            reason=f"VoiceMaster: {interaction.user} unlocked channel",
        )

        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.mention}: your voice channel has been **unlocked**"
            ),
        )

    async def _rename(
        self,
        interaction: discord.Interaction,
    ) -> None:
        modal = ui.Modal(
            title="Rename Channel",
        )

        name_input = ui.TextInput(
            label="New name",
            placeholder="enter channel name...",
            max_length=100,
        )

        modal.add_item(name_input)

        async def callback(
            modal_interaction: discord.Interaction,
        ) -> None:
            new_name = name_input.value.strip()

            if not new_name:
                await modal_interaction.response.send_message(
                    "name cannot be empty",
                    ephemeral=True,
                )
                return

            channel = modal_interaction.user.voice.channel

            await channel.edit(
                name=new_name,
                reason=f"VoiceMaster: {modal_interaction.user} renamed",
            )

            await _reply(
                modal_interaction,
                view=_container_msg(
                    f"{modal_interaction.user.mention}: "
                    f"channel renamed to **{new_name}**"
                ),
            )

        modal.on_submit = callback

        await interaction.response.send_modal(modal)

    async def _status(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel

        row = await self.cog.bot.db.fetchrow(
            "SELECT status_text, status_emoji "
            "FROM voicemaster_channels "
            "WHERE channel_id = $1",
            channel.id,
        )

        current_text = row["status_text"] if row else ""
        current_emoji = row["status_emoji"] if row else ""

        modal = StatusModal(
            current_text=current_text or "",
            current_emoji=current_emoji or "",
        )

        async def callback(
            modal_interaction: discord.Interaction,
        ) -> None:
            text = (
                modal.status_text.value.strip()
                if modal.status_text.value
                else ""
            )

            emoji = (
                modal.status_emoji.value.strip()
                if modal.status_emoji.value
                else ""
            )

            save = (
                modal.save_future.value.strip().lower()
                in ("yes", "y", "true", "1")
                if modal.save_future.value
                else False
            )

            await self.cog.bot.db.execute(
                "UPDATE voicemaster_channels "
                "SET status_text = $1, status_emoji = $2 "
                "WHERE channel_id = $3",
                text,
                emoji,
                channel.id,
            )

            if save:
                await self.cog.bot.db.execute(
                    "UPDATE voicemaster_configuration "
                    "SET default_status_text = $1, default_status_emoji = $2 "
                    "WHERE guild_id = $3",
                    text,
                    emoji,
                    modal_interaction.guild.id,
                )

            if emoji and text:
                display = f"{emoji} {text}"
            elif text:
                display = text
            elif emoji:
                display = emoji
            else:
                display = "status **cleared**"

            await _reply(
                modal_interaction,
                view=_container_msg(
                    f"{modal_interaction.user.mention}: "
                    f"channel status set to **{display}**"
                ),
            )

        modal.on_submit = callback

        await interaction.response.send_modal(modal)