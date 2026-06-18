from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import discord
from discord import ui
from discord.utils import format_dt

from core.managers.values import emojis, color

if TYPE_CHECKING:
    from .voicemaster import VoiceControl


PANEL_EMOJIS: dict[str, str] = {
    "lock": emojis.lock if hasattr(emojis, 'lock') else "🔒",
    "unlock": emojis.unlock if hasattr(emojis, 'unlock') else "🔓",
    "ghost": emojis.ghost if hasattr(emojis, 'ghost') else "👻",
    "reveal": emojis.reveal if hasattr(emojis, 'reveal') else "👁️",
    "claim": emojis.claim if hasattr(emojis, 'claim') else "📋",
    "disconnect": emojis.disconnect if hasattr(emojis, 'disconnect') else "🔌",
    "activity": emojis.activity if hasattr(emojis, 'activity') else "🎮",
    "information": emojis.information if hasattr(emojis, 'information') else "ℹ️",
    "increase": emojis.increase if hasattr(emojis, 'increase') else "➕",
    "decrease": emojis.decrease if hasattr(emojis, 'decrease') else "➖",
}

ACTIVITY_TYPES: list[dict[str, str]] = [
    {"id": "880218394199220334", "name": "Watch Together", "emoji": "\N{TELEVISION}"},
    {"id": "755827207812677713", "name": "Poker Night", "emoji": "\N{PLAYING CARD BLACK JOKER}"},
    {"id": "832012774040141894", "name": "Chess In The Park", "emoji": "\N{BLACK CHESS PAWN}"},
    {"id": "902271654783242291", "name": "Sketch Heads", "emoji": "\N{LOWER LEFT PENCIL}"},
    {"id": "879863686565621790", "name": "Letter League", "emoji": "\N{INPUT SYMBOL FOR LATIN LETTERS}"},
    {"id": "879863976006127627", "name": "Word Snacks", "emoji": "\N{CANDY}"},
    {"id": "852509694341283871", "name": "SpellCast", "emoji": "\N{SPARKLES}"},
    {"id": "832025144389533716", "name": "Blazing 8s", "emoji": "\N{FIRE}"},
    {"id": "945737671223947305", "name": "Putt Party", "emoji": "\N{FLAG IN HOLE}"},
    {"id": "903769130790969345", "name": "Land-io", "emoji": "\N{DESERT ISLAND}"},
    {"id": "947957217959759964", "name": "Bobble League", "emoji": "\N{SOCCER BALL}"},
    {"id": "950505761862189096", "name": "Know What I Meme", "emoji": "\N{THINKING FACE}"},
    {"id": "1007373802981822582", "name": "Gartic Phone", "emoji": "\N{ARTIST PALETTE}"},
]


async def _reply(
    interaction: discord.Interaction,
    embed: discord.Embed,
    *,
    view: ui.View | None = None,
) -> None:
    """Send a branded embed, choosing response vs. followup as needed."""
    kwargs: dict[str, Any] = {"embed": embed, "ephemeral": True}
    if view is not None:
        kwargs["view"] = view
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


def _success(text: str) -> discord.Embed:
    """Create a success embed."""
    return discord.Embed(
        description=f"{emojis.approve if hasattr(emojis, 'approve') else '✅'} {text}",
        color=color.base,
    )


def _warning(text: str) -> discord.Embed:
    """Create a warning embed."""
    return discord.Embed(
        description=f"{emojis.deny if hasattr(emojis, 'deny') else '❌'} {text}",
        color=color.base,
    )


def _neutral(text: str, emoji: str = "") -> discord.Embed:
    """Create a neutral embed."""
    return discord.Embed(
        description=f"{emoji} {text}",
        color=color.base,
    )


class DisconnectMembers(ui.Select):
    """Dropdown that disconnects selected members from the owner's channel."""

    def __init__(self, member: discord.Member) -> None:
        self.member = member
        self.guild = member.guild
        self.channel = member.voice.channel  # type: ignore[union-attr]
        members_list = [m for m in self.channel.members if m != member]
        super().__init__(
            placeholder="Choose members...",
            min_values=1,
            max_values=len(members_list),
            options=[
                discord.SelectOption(
                    value=str(occupant.id),
                    label=f"{occupant.display_name}",
                    emoji="\N{BUST IN SILHOUETTE}",
                )
                for occupant in members_list
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        disconnected = 0
        failed = 0
        for raw_id in self.values:
            target = self.guild.get_member(int(raw_id))
            if target is None:
                failed += 1
                continue
            if target.voice is None or target.voice.channel != self.channel:
                failed += 1
                continue
            try:
                await target.move_to(None)
                disconnected += 1
            except discord.HTTPException:
                failed += 1

        word = "member" if disconnected == 1 else "members"
        await interaction.followup.send(
            embed=_success(
                f"Successfully **disconnected** `{disconnected}` {word} (`{failed}` failed)",
            ),
            ephemeral=True,
        )


class ActivitySelection(ui.Select):
    """Dropdown that launches an embedded activity via a channel invite."""

    def __init__(self, member: discord.Member) -> None:
        self.member = member
        self.guild = member.guild
        self.channel = member.voice.channel  # type: ignore[union-attr]
        super().__init__(
            placeholder="Choose an activity...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    value=activity["id"],
                    label=activity["name"],
                    emoji=activity["emoji"],
                )
                for activity in ACTIVITY_TYPES
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        try:
            invite = await self.channel.create_invite(
                max_age=0,
                target_type=discord.InviteTarget.embedded_application,
                target_application_id=int(self.values[0]),
                reason=f"VoiceMaster: {self.member} started an activity",
            )
        except discord.HTTPException:
            await interaction.followup.send(
                embed=_warning("Failed to create an **invite** for the selected **activity**!"),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"[Click here to join the activity!]({invite})",
            ephemeral=True,
        )


class VoiceInterface(ui.View):
    """The persistent VoiceMaster button panel."""

    def __init__(self, cog: "VoiceControl") -> None:
        self.cog = cog
        super().__init__(timeout=None)

    async def _get_owner_id(self, channel_id: int) -> int | None:
        """Get the owner ID of a voice channel."""
        return await self.cog.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel_id,
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the user can interact with the interface."""
        user = interaction.user
        if not isinstance(user, discord.Member) or user.voice is None or user.voice.channel is None:
            await _reply(interaction, _warning("You're not connected to a **voice channel**"))
            return False

        owner_id = await self._get_owner_id(user.voice.channel.id)
        if not owner_id:
            await _reply(interaction, _warning("You're not in a **VoiceMaster** channel!"))
            return False

        custom_id = (interaction.data or {}).get("custom_id")
        if custom_id == "voicemaster:claim":
            if user.id == owner_id:
                await _reply(
                    interaction,
                    _warning("You already have **ownership** of this voice channel!"),
                )
                return False
            if owner_id in (member.id for member in user.voice.channel.members):
                await _reply(
                    interaction,
                    _warning("You can't claim this **voice channel**, the owner is still active here."),
                )
                return False
            return True

        if user.id != owner_id:
            await _reply(interaction, _warning("You don't own a **voice channel**!"))
            return False

        return True

    @ui.button(emoji=PANEL_EMOJIS["lock"], custom_id="voicemaster:lock")
    async def lock(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Lock your voice channel."""
        channel = interaction.user.voice.channel  # type: ignore[union-attr]
        await channel.set_permissions(
            interaction.guild.default_role,
            connect=False,
            reason=f"VoiceMaster: {interaction.user} locked voice channel",
        )
        await _reply(interaction, _success("Your **voice channel** has been locked"))

    @ui.button(emoji=PANEL_EMOJIS["unlock"], custom_id="voicemaster:unlock")
    async def unlock(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Unlock your voice channel."""
        channel = interaction.user.voice.channel  # type: ignore[union-attr]
        await channel.set_permissions(
            interaction.guild.default_role,
            connect=None,
            reason=f"VoiceMaster: {interaction.user} unlocked voice channel",
        )
        await _reply(interaction, _success("Your **voice channel** has been unlocked"))

    @ui.button(emoji=PANEL_EMOJIS["ghost"], custom_id="voicemaster:ghost")
    async def ghost(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Hide your voice channel."""
        channel = interaction.user.voice.channel  # type: ignore[union-attr]
        await channel.set_permissions(
            interaction.guild.default_role,
            view_channel=False,
            reason=f"VoiceMaster: {interaction.user} made voice channel hidden",
        )
        await _reply(interaction, _success("Your **voice channel** has been hidden"))

    @ui.button(emoji=PANEL_EMOJIS["reveal"], custom_id="voicemaster:reveal")
    async def reveal(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Reveal your voice channel."""
        channel = interaction.user.voice.channel  # type: ignore[union-attr]
        await channel.set_permissions(
            interaction.guild.default_role,
            view_channel=None,
            reason=f"VoiceMaster: {interaction.user} revealed voice channel",
        )
        await _reply(interaction, _success("Your **voice channel** has been revealed"))

    @ui.button(emoji=PANEL_EMOJIS["claim"], custom_id="voicemaster:claim")
    async def claim(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Claim an inactive voice channel."""
        channel = interaction.user.voice.channel  # type: ignore[union-attr]
        await self.cog.bot.db.execute(
            "UPDATE voicemaster.channels SET owner_id = $2 WHERE channel_id = $1",
            channel.id,
            interaction.user.id,
        )
        if channel.name.endswith("channel"):
            with contextlib.suppress(discord.HTTPException):
                await channel.edit(name=f"{interaction.user.display_name}'s channel")
        await _reply(interaction, _success("You are now the owner of this **channel**!"))

    @ui.button(emoji=PANEL_EMOJIS["disconnect"], custom_id="voicemaster:disconnect")
    async def disconnect(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Disconnect members from your VC."""
        view = ui.View(timeout=None)
        view.add_item(DisconnectMembers(interaction.user))  # type: ignore[arg-type]
        await _reply(
            interaction,
            _neutral("Select members from the **dropdown** to disconnect.", "\N{HAMMER}"),
            view=view,
        )

    @ui.button(emoji=PANEL_EMOJIS["activity"], custom_id="voicemaster:activity")
    async def activity(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Start an activity in your voice channel."""
        view = ui.View(timeout=None)
        view.add_item(ActivitySelection(interaction.user))  # type: ignore[arg-type]
        await _reply(
            interaction,
            _neutral("Select an activity from the **dropdown** to start!", PANEL_EMOJIS["activity"]),
            view=view,
        )

    @ui.button(emoji=PANEL_EMOJIS["information"], custom_id="voicemaster:information")
    async def information(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """See current configuration for current voice channel."""
        with contextlib.suppress(discord.InteractionResponded):
            await interaction.response.defer(ephemeral=True)

        channel = interaction.user.voice.channel  # type: ignore[union-attr]
        locked = channel.permissions_for(interaction.guild.default_role).connect is False

        embed = discord.Embed(
            title=channel.name,
            description=(
                f"**Owner:** {interaction.user.mention} (`{interaction.user.id}`)"
                + "\n**Locked:** "
                + (emojis.approve if locked else emojis.deny)
                + "\n**Created:** "
                + format_dt(channel.created_at, style="R")
                + f"\n**Bitrate:** {int(channel.bitrate / 1000)}kbps"
                + f"\n**Connected:** `{len(channel.members)}`"
                + (f"/`{channel.user_limit}`" if channel.user_limit else "")
            ),
            color=color.base,
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar,
        )

        roles_permitted = [
            target
            for target, overwrite in channel.overwrites.items()
            if overwrite.connect is True and isinstance(target, discord.Role)
        ]
        if roles_permitted:
            embed.add_field(
                name="**Role Permitted**",
                value=", ".join(role.mention for role in roles_permitted),
                inline=False,
            )

        members_permitted = [
            target
            for target, overwrite in channel.overwrites.items()
            if overwrite.connect is True
            and isinstance(target, discord.Member)
            and target != interaction.user
        ]
        if members_permitted:
            embed.add_field(
                name="**Member Permitted**",
                value=", ".join(member.mention for member in members_permitted),
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(emoji=PANEL_EMOJIS["increase"], custom_id="voicemaster:increase")
    async def increase(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Increase the user limit of your voice channel."""
        channel = interaction.user.voice.channel  # type: ignore[union-attr]
        limit = channel.user_limit or 0
        if limit == 99:
            await _reply(
                interaction,
                _warning("Channel member limit cannot be more than **99 members**!"),
            )
            return
        await channel.edit(
            user_limit=limit + 1,
            reason=f"VoiceMaster: {interaction.user} increased voice channel user limit",
        )
        await _reply(
            interaction,
            _success(f"Your **voice channel**'s limit has been updated to `{limit + 1}`"),
        )

    @ui.button(emoji=PANEL_EMOJIS["decrease"], custom_id="voicemaster:decrease")
    async def decrease(self, interaction: discord.Interaction, button: ui.Button) -> None:
        """Decrease the user limit of your voice channel."""
        channel = interaction.user.voice.channel  # type: ignore[union-attr]
        limit = channel.user_limit or 0
        if limit == 0:
            await _reply(
                interaction,
                _warning("Channel member limit must be greater than **0 members**"),
            )
            return
        await channel.edit(
            user_limit=limit - 1,
            reason=f"VoiceMaster: {interaction.user} decreased voice channel user limit",
        )
        await _reply(
            interaction,
            _success(
                "Your **voice channel**'s limit has been **removed**"
                if (limit - 1) == 0
                else f"Your **voice channel**'s limit has been updated to `{limit - 1}`",
            ),
        )
