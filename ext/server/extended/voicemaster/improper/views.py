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


def _strike(text: str) -> str:
    """Wrap text in Discord strikethrough markdown."""
    return f"~~{text}~~"


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
    allowed_mentions = discord.AllowedMentions.none()

    if interaction.response.is_done():
        await interaction.followup.send(
            view=view,
            ephemeral=True,
            allowed_mentions=allowed_mentions,
        )
        return

    await interaction.response.send_message(
        view=view,
        ephemeral=True,
        allowed_mentions=allowed_mentions,
    )

def _kick_response(
    interaction: discord.Interaction,
    count: int,
    members: list[discord.Member],
) -> ui.LayoutView:
    word = "user" if count == 1 else "users"

    mentions = " ".join(
        member.mention
        for member in members
    )

    return _container_msg(
        f"{interaction.user.display_name}: i have **kicked** the {word} from your voice channel",
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


class LimitModal(ui.Modal, title="Voice Channel Limit"):
    amount = ui.TextInput(
        label="Amount to allow",
        placeholder="Enter a number from 0 to 99",
        max_length=2,
        required=False,
    )

    has_limit = ui.TextInput(
        label="Will the voice channel have a limit on how many can join?",
        placeholder="yes or no",
        max_length=3,
        required=False,
    )

    def __init__(
        self,
        *,
        current_limit: int = 0,
    ) -> None:
        super().__init__()

        if current_limit:
            self.amount.default = str(current_limit)

        self.has_limit.default = "yes"


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

        options = [
            discord.SelectOption(
                value=str(target.id),
                label=f"{target} ({target.id})",
                emoji="👤",
            )
            for target in members
        ]

        super().__init__(
            placeholder="Choose members...",
            min_values=1,
            max_values=max(1, len(options)),
            options=options,
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


ALL_BUTTONS = frozenset({
    "claim", "delete", "disconnect", "hide", "limit",
    "lock", "rename", "reveal", "status", "unlock",
})


class VoiceInterface(ui.LayoutView):
    _cog_ref: "VoiceMaster | None" = None

    def __init__(
        self,
        cog: "VoiceMaster" = None,
        guild: discord.Guild = None,
        *,
        channel: discord.VoiceChannel | None = None,
        disabled_buttons: set[str] | None = None,
    ) -> None:
        self.cog = cog or VoiceInterface._cog_ref
        self.guild = guild
        self._channel_state = self._get_channel_state(channel) if channel else {"locked": False, "hidden": False}
        self._disabled_buttons: set[str] = disabled_buttons or set()

        super().__init__(timeout=None)

        self._build()

    @staticmethod
    def _get_channel_state(channel: discord.VoiceChannel | None) -> dict:
        if channel is None or not isinstance(channel, discord.VoiceChannel):
            return {"locked": False, "hidden": False}
        try:
            overwrites = channel.overwrites_for(channel.guild.default_role)
            locked = overwrites.connect is False
            hidden = overwrites.view_channel is False
            return {"locked": locked, "hidden": hidden}
        except Exception:
            return {"locked": False, "hidden": False}

    def _build(self) -> None:
        container = ui.Container()
        _clear(container)

        header = (
            "## **voice controls**\n"
            "> -# **manage** your **voice channel** using the controls\n> -# use `help voicemaster` to see all commands"
        )

        container.add_item(
            ui.TextDisplay(header)
        )

        container.add_item(
            ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            )
        )

        db_disabled = self._disabled_buttons

        def is_disabled(name: str) -> bool:
            return name in db_disabled

        def _label(name: str) -> str:
            return _strike(name) if is_disabled(name) else name

        controls = (
            "### button usage\n"
            f"> {VM['lock']} - **{_label('lock')}** the channel\n"
            f"> {VM['unlock']} - **{_label('unlock')}** the channel\n"
            f"> {VM['hide']} - **{_label('hide')}** the channel\n"
            f"> {VM['reveal']} - **{_label('reveal')}** the channel\n"
            f"> {VM['claim']} - **{_label('claim')}** the channel\n"
            f"> {VM['status']} - set the channel **{_label('status')}**\n"
            f"> {VM['disconnect']} - **{_label('disconnect')}** members\n"
            f"> {VM['limit']} - set the channel **{_label('limit')}**\n"
            f"> {VM['rename']} - **{_label('rename')}** the channel\n"
            f"> {VM['delete']} - **{_label('delete')}** the channel"
        )

        container.add_item(
            ui.TextDisplay(controls)
        )

        container.add_item(
            ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            )
        )

        buttons = {
            "lock": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["lock"],
                custom_id="voicemaster:lock",
                disabled=is_disabled("lock"),
            ),
            "unlock": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["unlock"],
                custom_id="voicemaster:unlock",
                disabled=is_disabled("unlock"),
            ),
            "hide": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["hide"],
                custom_id="voicemaster:hide",
                disabled=is_disabled("hide"),
            ),
            "reveal": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["reveal"],
                custom_id="voicemaster:reveal",
                disabled=is_disabled("reveal"),
            ),
            "claim": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["claim"],
                custom_id="voicemaster:claim",
                disabled=is_disabled("claim"),
            ),
            "status": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["status"],
                custom_id="voicemaster:status",
                disabled=is_disabled("status"),
            ),
            "disconnect": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["disconnect"],
                custom_id="voicemaster:disconnect",
                disabled=is_disabled("disconnect"),
            ),
            "limit": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["limit"],
                custom_id="voicemaster:limit",
                disabled=is_disabled("limit"),
            ),
            "rename": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["rename"],
                custom_id="voicemaster:rename",
                disabled=is_disabled("rename"),
            ),
            "delete": ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=VM["delete"],
                custom_id="voicemaster:delete",
                disabled=is_disabled("delete"),
            ),
        }

        buttons["lock"].callback = self._lock
        buttons["unlock"].callback = self._unlock
        buttons["hide"].callback = self._hide
        buttons["reveal"].callback = self._reveal
        buttons["claim"].callback = self._claim
        buttons["status"].callback = self._status
        buttons["disconnect"].callback = self._disconnect
        buttons["limit"].callback = self._limit
        buttons["rename"].callback = self._rename
        buttons["delete"].callback = self._delete

        row1 = ui.ActionRow(
            buttons["lock"],
            buttons["unlock"],
            buttons["hide"],
            buttons["reveal"],
            buttons["claim"],
        )

        row2 = ui.ActionRow(
            buttons["status"],
            buttons["disconnect"],
            buttons["limit"],
            buttons["rename"],
            buttons["delete"],
        )

        container.add_item(row1)
        container.add_item(row2)

        container.add_item(
            ui.TextDisplay(
                "-# to use the controls, you must **own** the voice channel you are in"
            )
        )

        self.add_item(container)

    def apply_disabled(self, disabled_buttons: set[str] | None) -> bool:
        """Re-render this panel for a new disabled-button set.

        Returns True when the set changed (caller should edit the message).
        """
        new = {b for b in (disabled_buttons or set()) if b}
        if new == self._disabled_buttons:
            return False
        self._disabled_buttons = new
        self.clear_items()
        self._build()
        return True

    async def _refresh_panel(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
    ) -> None:
        """Refresh the panel with updated button states."""
        new_view = VoiceInterface(self.cog, self.guild, channel=channel, disabled_buttons=self._disabled_buttons)
        try:
            await interaction.message.edit(view=new_view)
        except discord.HTTPException:
            pass
        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.display_name}: channel updated"
            ),
        )

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
                    f"{user.display_name}: you're not connected to a **voice channel**"
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
                    f"{user.display_name}: you're not in a **voicemaster** channel"
                ),
            )
            return False

        custom_id = (interaction.data or {}).get(
            "custom_id"
        )

        if custom_id == "voicemaster:claim":
            if user.id == owner_id:
                await _reply(
                    interaction,
                    view=_container_msg(
                        f"{user.display_name}: you already **own** this voice channel"
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
                        f"{user.display_name}: you can't claim this channel, "
                        "the owner is still here"
                    ),
                )
                return False

            return True

        if user.id != owner_id:
            await _reply(
                interaction,
                view=_container_msg(
                    f"{user.display_name}: you **don't** own this voice channel"
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
                    name=f"{interaction.user.display_name}'s channel"
                )

        await _reply(
            interaction,
            view=_container_msg(
                f"{interaction.user.display_name}: you are now the **owner** of this channel"
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
                f"{interaction.user.display_name}: your voice channel has been **deleted**"
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
                f"{interaction.user.display_name}: choose members to **disconnect**"
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

        await self.cog._move_to_private_category(channel)

        await self._refresh_panel(interaction, channel)

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

        await self.cog._move_to_original_category(channel)

        await self._refresh_panel(interaction, channel)

    async def _limit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.user.voice.channel

        modal = LimitModal(
            current_limit=channel.user_limit,
        )

        async def callback(
            modal_interaction: discord.Interaction,
        ) -> None:
            raw_amount = (
                modal.amount.value.strip()
                if modal.amount.value
                else ""
            )

            raw_has_limit = (
                modal.has_limit.value.strip().lower()
                if modal.has_limit.value
                else "yes"
            )

            if not raw_amount:
                amount = 0
            else:
                try:
                    amount = int(raw_amount)
                except ValueError:
                    await _reply(
                        modal_interaction,
                        view=_container_msg(
                            f"{modal_interaction.user.display_name}: "
                            "amount must be a valid **number**"
                        ),
                    )
                    return

            if amount < 0 or amount > 99:
                await _reply(
                    modal_interaction,
                    view=_container_msg(
                        f"{modal_interaction.user.display_name}: "
                        "amount must be between **0** and **99**"
                    ),
                )
                return

            if raw_has_limit in {
                "no",
                "n",
                "false",
                "0",
            }:
                has_limit = False
            elif raw_has_limit in {
                "",
                "yes",
                "y",
                "true",
                "1",
            }:
                has_limit = True
            else:
                await _reply(
                    modal_interaction,
                    view=_container_msg(
                        f"{modal_interaction.user.display_name}: "
                        "the limit option must be **yes** or **no**"
                    ),
                )
                return

            user_limit = amount if has_limit else 0

            await channel.edit(
                user_limit=user_limit,
                reason=f"VoiceMaster: {modal_interaction.user} changed channel limit",
            )

            if has_limit:
                message = (
                    f"{modal_interaction.user.display_name}: "
                    f"voice channel limit set to **{amount}** users"
                )
            else:
                message = (
                    f"{modal_interaction.user.display_name}: "
                    "voice channel limit has been **disabled**"
                )

            await _reply(
                modal_interaction,
                view=_container_msg(message),
            )

        modal.on_submit = callback

        await interaction.response.send_modal(modal)

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

        await self.cog._move_to_private_category(channel)

        await self._refresh_panel(interaction, channel)

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

        await self.cog._move_to_original_category(channel)

        await self._refresh_panel(interaction, channel)

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
                await _reply(
                    modal_interaction,
                    view=_container_msg(
                        f"{modal_interaction.user.display_name}: "
                        "name cannot be empty"
                    ),
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
                    f"{modal_interaction.user.display_name}: "
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
                    f"{modal_interaction.user.display_name}: "
                    f"channel status set to **{display}**"
                ),
            )

        modal.on_submit = callback

        await interaction.response.send_modal(modal)