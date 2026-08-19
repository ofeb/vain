from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Literal

import discord
from discord import ui

if TYPE_CHECKING:
    from core.vain import Vain

LOADING = "<a:loading:1534646618693963807>"
BOT_NAME = "vain"
SETUP_TIMEOUT = 300
SETUP_COOLDOWN = 120

_setup_cooldown: dict[int, float] = {}


def _clear_accent(container: ui.Container) -> None:
    for attr in ("accent_color", "accent_colour", "color", "colour"):
        if hasattr(container, attr):
            with contextlib.suppress(Exception):
                setattr(container, attr, None)


def _sep(container: ui.Container) -> None:
    try:
        container.add_item(
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
        )
    except Exception:
        with contextlib.suppress(Exception):
            container.add_item(ui.Separator(visible=True))


def setup_on_cooldown(guild_id: int) -> float | None:
    """Return remaining cooldown seconds, or None if ready."""
    until = _setup_cooldown.get(guild_id)
    if until is None:
        return None
    left = until - time.monotonic()
    if left <= 0:
        _setup_cooldown.pop(guild_id, None)
        return None
    return left


def mark_setup_cooldown(guild_id: int) -> None:
    _setup_cooldown[guild_id] = time.monotonic() + SETUP_COOLDOWN


def format_cooldown_left(left: float) -> str:
    mins = int(left // 60)
    secs = int(left % 60)
    return f"{mins}m {secs}s" if mins else f"{secs}s"


class SetupView(ui.LayoutView):
    """Interactive vain automatic setup with 5m phase timeouts and 2m action cooldown."""

    def __init__(
        self,
        bot: "Vain",
        *,
        guild: discord.Guild,
        author_id: int | None = None,
        prefix: str = ",",
        message: discord.Message | None = None,
    ) -> None:

        super().__init__(timeout=None)
        self.bot = bot
        self.guild = guild
        self.author_id = author_id
        self.prefix = prefix
        self.message = message
        self._created: list[tuple[str, int]] = []
        self._notes: list[str] = []
        self._expire_task: asyncio.Task | None = None
        self._phase: Literal[
            "intro", "loading", "done", "reverting", "reverted", "expired", "failed"
        ] = "intro"
        self._build_intro()


    def _cancel_expire(self) -> None:
        if self._expire_task is not None and not self._expire_task.done():
            self._expire_task.cancel()
        self._expire_task = None

    def _arm_expire(self) -> None:
        """Start a fresh 5-minute timer for the current interactive phase."""
        self._cancel_expire()

        async def _runner() -> None:
            try:
                await asyncio.sleep(SETUP_TIMEOUT)
                await self.on_timeout()
            except asyncio.CancelledError:
                return

        try:
            loop = asyncio.get_running_loop()
            self._expire_task = loop.create_task(_runner())
        except RuntimeError:
            self._expire_task = None


    def _build_intro(self) -> None:
        self._phase = "intro"
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(ui.TextDisplay("**vain setup**"))
        container.add_item(
            ui.TextDisplay(f"-# default prefix: `{self.prefix}`")
        )
        _sep(container)
        body = (
            f"> -# `1.` move my role to the **top** of the hierarchy\n"
            f"> -# `2.` grant me **Administrator** so every module can configure\n"
            f"> -# `3.` press **setup vain** to install the modules below\n\n"
            f"> -# · **voicemaster** - join-to-create voice + interface\n"
            f"> -# · **jail** - jailed role + isolated `#jail` channel\n"
            f"> -# · **image muted** / **reaction muted** roles\n"
            f"> -# · **logging** - `#antinuke-logs`, `#antiraid-logs`, `#jail-logs`, `#modlogs`, `#logs`\n"
            f"> -# · **antinuke** - recommended protection\n"
            f"> -# · **antiraid** - join protection when available"
        )
        container.add_item(ui.TextDisplay(body))
        row = ui.ActionRow()
        btn = ui.Button(label="setup vain", style=discord.ButtonStyle.primary)
        btn.callback = self._on_setup
        row.add_item(btn)
        container.add_item(row)
        self.add_item(container)
        self._arm_expire()

    def _build_loading(self) -> None:
        self._phase = "loading"
        self._cancel_expire()
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(
            ui.TextDisplay(
                f"{LOADING} **setting up {BOT_NAME}**\n"
                f"> -# voicemaster, jail, mute, logs, antinuke, antiraid"
            )
        )
        self.add_item(container)

    def _done_body_lines(self) -> list[str]:
        notes = self._notes or [
            "**voicemaster**: configured",
            "**jail**: configured",
            "**mute role**: configured",
            "**logging**: configured",
            "**antinuke**: configured",
            "**antiraid**: configured",
        ]
        lines = [f"> -# `{i}.` {n}" for i, n in enumerate(notes, start=1)]
        lines.append("")
        lines.append(
            f"> -# learn to reconfigure antinuke and antiraid with `{self.prefix}help antinuke` and `{self.prefix}help antiraid`"
        )
        lines.append("")
        lines.append(
            f"> -# create embeds and containers use `embedbuilder` and `containerbuilder`"
        )
        lines.append("")
        lines.append(
            f"> -# run `{self.prefix}unsetup` to revert all configurations done by {BOT_NAME}"
        )
        lines.append("")
        lines.append(
            "> -# this **removes** the configured channels and roles created\n"
            "> -# however this does **not** affect **voicemaster**, **antinuke** and **antiraid**."
        )
        return lines

    def _build_done(self) -> None:
        self._phase = "done"
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(
            ui.TextDisplay("**thank you for using vain, setup completed**")
        )
        _sep(container)
        container.add_item(ui.TextDisplay(chr(10).join(self._done_body_lines())))
        row = ui.ActionRow()
        btn = ui.Button(label="revert", style=discord.ButtonStyle.primary)
        btn.callback = self._on_revert
        row.add_item(btn)
        container.add_item(row)
        self.add_item(container)
        self._arm_expire()

    def _build_reverting(self) -> None:
        self._phase = "reverting"
        self._cancel_expire()
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(
            ui.TextDisplay(
                f"{LOADING} **reverting setup**\n"
                f"> -# removing categories, channels, roles created by setup"
            )
        )
        self.add_item(container)

    def _build_reverted(self) -> None:
        self._phase = "reverted"
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(ui.TextDisplay("**setup reverted**"))
        container.add_item(
            ui.TextDisplay(
                f"> -# channels and roles from automatic setup were removed\n"
                f"> -# press the button or run `{self.prefix}setup` again to set {BOT_NAME} up in this server"
            )
        )
        row = ui.ActionRow()
        btn = ui.Button(label="setup", style=discord.ButtonStyle.primary)
        btn.callback = self._on_setup_again
        row.add_item(btn)
        container.add_item(row)
        self.add_item(container)
        self._arm_expire()

    def _build_expired_intro(self) -> None:
        self._phase = "expired"
        self._cancel_expire()
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(ui.TextDisplay("**you were too late!**"))
        container.add_item(
            ui.TextDisplay(
                f"> -# this setup panel expired after **5 minutes**\n"
                f"> -# run `{self.prefix}setup` to set {BOT_NAME} up in this guild"
            )
        )
        self.add_item(container)

    def _build_expired_done(self) -> None:
        """Thank-you panel after 5m - same content, revert button removed."""
        self._phase = "expired"
        self._cancel_expire()
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(
            ui.TextDisplay("**thank you for using vain, setup completed**")
        )
        _sep(container)
        container.add_item(ui.TextDisplay(chr(10).join(self._done_body_lines())))
        self.add_item(container)

    def _build_expired_reverted(self) -> None:
        """Reverted panel after 5m - setup button removed."""
        self._phase = "expired"
        self._cancel_expire()
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(ui.TextDisplay("**setup reverted**"))
        container.add_item(
            ui.TextDisplay(
                f"> -# channels and roles from automatic setup were removed\n"
                f"> -# run `{self.prefix}setup` to configure {BOT_NAME} in this guild"
            )
        )
        self.add_item(container)

    def _build_failed(self, error: str) -> None:
        self._phase = "failed"
        self._cancel_expire()
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(ui.TextDisplay("**setup failed**"))
        container.add_item(
            ui.TextDisplay(
                f"> -# `{error}`\n"
                f"> -# make sure my role is high and has **Administrator**, then try again"
            )
        )
        self.add_item(container)



    async def on_timeout(self) -> None:
        if self._phase == "intro":
            self._build_expired_intro()
        elif self._phase == "done":
            self._build_expired_done()
        elif self._phase == "reverted":
            self._build_expired_reverted()
        else:
            return
        if self.message is not None:
            with contextlib.suppress(Exception):
                await self.message.edit(view=self)
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        user = interaction.user
        if user is None:
            return False
        owners = getattr(self.bot, "owners", None) or []
        if user.id == interaction.guild.owner_id or user.id in owners:
            return True
        msg = (
            "You are **missing** the permission to **setup** vain\n"
            "> -# **Permission Needed: Guild Owner**"
        )
        with contextlib.suppress(Exception):
            if hasattr(interaction, "warning"):
                await interaction.warning(msg)
            elif not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        return False

    async def _edit(self, interaction: discord.Interaction | None = None) -> None:
        if interaction is not None and not interaction.response.is_done():
            with contextlib.suppress(Exception):
                await interaction.response.edit_message(view=self)
                return
        if self.message is not None:
            with contextlib.suppress(Exception):
                await self.message.edit(view=self)

    async def _check_cooldown(self, interaction: discord.Interaction) -> bool:
        left = setup_on_cooldown(self.guild.id)
        if left is None:
            return True
        wait = format_cooldown_left(left)
        msg = f"Setup is on cooldown\n> -# **try again in** `{wait}`"
        with contextlib.suppress(Exception):
            if hasattr(interaction, "warning"):
                await interaction.warning(msg)
            elif not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        return False


    async def _on_setup(self, interaction: discord.Interaction) -> None:
        if not await self._check_cooldown(interaction):
            return
        self._notes = []
        self._build_loading()
        await self._edit(interaction)
        try:
            await self._run_setup()
        except Exception as e:
            self._build_failed(str(e)[:180])
            await self._edit()
            return
        mark_setup_cooldown(self.guild.id)
        self._build_done()
        await self._edit()

    async def _on_setup_again(self, interaction: discord.Interaction) -> None:
        if not await self._check_cooldown(interaction):
            return
        self._created = []
        self._notes = []
        self._build_loading()
        await self._edit(interaction)
        try:
            await self._run_setup()
        except Exception as e:
            self._build_failed(str(e)[:180])
            await self._edit()
            return
        mark_setup_cooldown(self.guild.id)
        self._build_done()
        await self._edit()

    async def _on_revert(self, interaction: discord.Interaction) -> None:
        if not await self._check_cooldown(interaction):
            return
        self._build_reverting()
        await self._edit(interaction)
        try:
            await self._run_revert()
        except Exception as e:
            self._build_failed(str(e)[:180])
            await self._edit()
            return
        mark_setup_cooldown(self.guild.id)
        self._build_reverted()
        await self._edit()


    async def _ensure_role(
        self, name: str, *, colour: discord.Colour | None = None
    ) -> discord.Role:
        role = discord.utils.get(self.guild.roles, name=name)
        if role is not None:
            return role
        role = await self.guild.create_role(
            name=name,
            colour=colour or discord.Colour.dark_grey(),
            permissions=discord.Permissions.none(),
            reason=f"{BOT_NAME} automatic setup",
        )
        self._created.append(("role", role.id))
        return role

    async def _ensure_category(
        self,
        name: str,
        overwrites: dict | None = None,
    ) -> discord.CategoryChannel:
        cat = discord.utils.get(self.guild.categories, name=name)
        if cat is not None:
            if overwrites:
                with contextlib.suppress(Exception):
                    await cat.edit(overwrites=overwrites)
            return cat
        cat = await self.guild.create_category(
            name,
            overwrites=overwrites or {},
            reason=f"{BOT_NAME} automatic setup",
        )
        self._created.append(("category", cat.id))
        return cat

    async def _ensure_text(
        self,
        name: str,
        category: discord.CategoryChannel,
        *,
        topic: str = "",
        overwrites: dict | None = None,
    ) -> discord.TextChannel:
        ch = discord.utils.get(category.text_channels, name=name)
        if ch is not None:
            if overwrites:
                with contextlib.suppress(Exception):
                    await ch.edit(overwrites=overwrites)
            return ch
        ch = await category.create_text_channel(
            name,
            topic=topic or None,
            overwrites=overwrites or {},
            reason=f"{BOT_NAME} automatic setup",
        )
        self._created.append(("channel", ch.id))
        return ch

    async def _ensure_voice(
        self,
        name: str,
        category: discord.CategoryChannel,
    ) -> discord.VoiceChannel:
        ch = discord.utils.get(category.voice_channels, name=name)
        if ch is not None:
            return ch
        ch = await category.create_voice_channel(
            name,
            reason=f"{BOT_NAME} automatic setup",
        )
        self._created.append(("channel", ch.id))
        return ch


    async def _run_setup(self) -> None:
        guild = self.guild
        me = guild.me or guild.get_member(self.bot.user.id)
        if me is None:
            raise RuntimeError("bot member not found in this guild")
        reason = f"{BOT_NAME} automatic setup"

        overwrites_logs = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True
            ),
        }
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites_logs[role] = discord.PermissionOverwrite(view_channel=True)

        logs_cat = await self._ensure_category("logs", overwrites_logs)

        antinuke_logs = await self._ensure_text(
            "antinuke-logs",
            logs_cat,
            topic="Antinuke events",
            overwrites=overwrites_logs,
        )
        antiraid_logs = await self._ensure_text(
            "antiraid-logs",
            logs_cat,
            topic="Antiraid events",
            overwrites=overwrites_logs,
        )
        jail_logs = await self._ensure_text(
            "jail-logs",
            logs_cat,
            topic="Jail events",
            overwrites=overwrites_logs,
        )
        modlogs = await self._ensure_text(
            "modlogs",
            logs_cat,
            topic="Moderation cases",
            overwrites=overwrites_logs,
        )
        all_logs = await self._ensure_text(
            "logs",
            logs_cat,
            topic="All server events",
            overwrites=overwrites_logs,
        )
        with contextlib.suppress(Exception):
            from ext.moderation.extended.setup.settings import Settings

            await Settings.set_modlog_channel(self.bot.db, guild.id, modlogs.id)
        with contextlib.suppress(Exception):
            await self.bot.db.set_security_log_channels(
                guild.id,
                antinuke_channel_id=antinuke_logs.id,
                antiraid_channel_id=antiraid_logs.id,
            )

        log_events = [
            "messages",
            "members",
            "channels",
            "roles",
            "invites",
            "emojis",
            "voice",
        ]
        with contextlib.suppress(Exception):
            await Settings.add_log_events(self.bot.db, guild.id, all_logs.id, log_events)
        with contextlib.suppress(Exception):
            await Settings.set_jail_log_channel(self.bot.db, guild.id, jail_logs.id)
        self._notes.append(
            f"**logging**: {antinuke_logs.mention}, {antiraid_logs.mention}, "
            f"{jail_logs.mention}, {modlogs.mention}, {all_logs.mention}"
        )

        jail_role = await self._ensure_role("Jailed")
        overwrites_jail = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False, send_messages=False
            ),
            me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True
            ),
            jail_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites_jail[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True
                )

        jail_cat = await self._ensure_category("jail", overwrites_jail)
        jail_ch = await self._ensure_text(
            "jail",
            jail_cat,
            topic="Jail channel",
            overwrites=overwrites_jail,
        )
        with contextlib.suppress(Exception):
            await Settings.set_jail_config(self.bot.db, guild.id, jail_ch.id, jail_role.id)
        for channel in list(guild.channels):
            if not isinstance(
                channel, (discord.TextChannel, discord.VoiceChannel, discord.ForumChannel)
            ):
                continue
            if channel.category_id == jail_cat.id:
                continue
            with contextlib.suppress(Exception):
                await channel.set_permissions(
                    jail_role,
                    view_channel=False,
                    send_messages=False,
                    connect=False,
                    reason=reason,
                )
        self._notes.append(f"**jail**: {jail_role.mention}, {jail_ch.mention}")

        imuted = await self._ensure_role("Image Muted")
        rmuted = await self._ensure_role("Reaction Muted")
        with contextlib.suppress(Exception):
            await Settings.set_mute_roles(self.bot.db, guild.id, imuted.id, rmuted.id)
        for channel in list(guild.text_channels):
            with contextlib.suppress(Exception):
                await channel.set_permissions(
                    imuted,
                    attach_files=False,
                    embed_links=False,
                    reason=reason,
                )
            with contextlib.suppress(Exception):
                await channel.set_permissions(
                    rmuted,
                    add_reactions=False,
                    reason=reason,
                )
        self._notes.append(
            f"**mute role**: {imuted.mention}, {rmuted.mention}"
        )

        try:
            from ext.server.extended.voicemaster.settings import Settings as VMSettings

            exists = await VMSettings.exists(self.bot, guild)
            if not exists:
                vm_cat = await self._ensure_category("Voice Channels")
                interface = await self._ensure_text("interface", vm_cat)
                join_vc = await self._ensure_voice("Join to Create", vm_cat)
                everyone = guild.default_role
                with contextlib.suppress(Exception):
                    await interface.set_permissions(
                        everyone,
                        send_messages=False,
                        send_messages_in_threads=False,
                        create_public_threads=False,
                        create_private_threads=False,
                    )
                settings = await VMSettings.fetch(self.bot, guild)
                await settings.upsert(
                    category_id=vm_cat.id,
                    interface_id=interface.id,
                    channel_id=join_vc.id,
                )
                cog = self.bot.get_cog("VoiceMaster") or self.bot.get_cog("Voicemaster")
                if cog is not None and hasattr(cog, "_panel_view"):
                    with contextlib.suppress(Exception):
                        panel_msg = await interface.send(view=cog._panel_view(guild))
                        settings = await VMSettings.fetch(self.bot, guild)
                        await settings.upsert(panel_message_id=panel_msg.id)
                self._notes.append(
                    f"**voicemaster**: {interface.mention}, {join_vc.mention}"
                )
            else:
                self._notes.append("**voicemaster**: already configured")
        except Exception as e:
            self._notes.append(f"**voicemaster**: skipped (`{str(e)[:60]}`)")

        try:
            cog = self.bot.get_cog("Antinuke") or self.bot.get_cog("Security")
            if cog is not None and hasattr(cog, "_commit_module"):
                defaults = {
                    "ban": {"punishment": "ban", "threshold": 3, "within": 300, "command": True},
                    "kick": {"punishment": "kick", "threshold": 3, "within": 300, "command": True},
                    "channel": {"punishment": "ban", "threshold": 3, "within": 300},
                    "role": {"punishment": "ban", "threshold": 3, "within": 300},
                    "webhook": {"punishment": "ban", "threshold": 1, "within": 300},
                    "emoji": {"punishment": "kick", "threshold": 5, "within": 300},
                    "vanity": {"punishment": "ban"},
                    "botadd": {"punishment": "ban"},
                }
                for module, payload in defaults.items():
                    await cog._commit_module(guild.id, module, {**payload, "status": True})
                if hasattr(cog, "_load_config"):
                    await cog._load_config(guild.id)
                self._notes.append("**antinuke**: recommended protection enabled")
            else:
                self._notes.append("**antinuke**: module unavailable")
        except Exception as e:
            self._notes.append(f"**antinuke**: skipped (`{str(e)[:60]}`)")

        try:
            cog = self.bot.get_cog("Antiraid") or self.bot.get_cog("Security")
            done = False
            if cog is not None:
                if hasattr(cog, "enable_antiraid_defaults"):
                    await cog.enable_antiraid_defaults(guild.id)
                    done = True
                elif hasattr(cog, "_enable_antiraid"):
                    await cog._enable_antiraid(guild.id)
                    done = True
            self._notes.append(
                "**antiraid**: enabled"
                if done
                else f"**antiraid**: configure with `{self.prefix}help antiraid`"
            )
        except Exception as e:
            self._notes.append(f"**antiraid**: skipped (`{str(e)[:60]}`)")

    async def _run_revert(self) -> None:
        guild = self.guild
        reason = f"{BOT_NAME} setup revert"

        for kind, oid in reversed(self._created):
            try:
                if kind == "channel":
                    ch = guild.get_channel(oid)
                    if ch:
                        await ch.delete(reason=reason)
                elif kind == "category":
                    cat = guild.get_channel(oid)
                    if cat:
                        for ch in list(getattr(cat, "channels", []) or []):
                            with contextlib.suppress(Exception):
                                await ch.delete(reason=reason)
                        await cat.delete(reason=reason)
                elif kind == "role":
                    role = guild.get_role(oid)
                    if role:
                        await role.delete(reason=reason)
            except Exception:
                continue

        for cat_name in ("logs", "jail", "Voice Channels"):
            cat = discord.utils.get(guild.categories, name=cat_name)
            if cat:
                for ch in list(cat.channels):
                    with contextlib.suppress(Exception):
                        await ch.delete(reason=reason)
                with contextlib.suppress(Exception):
                    await cat.delete(reason=reason)

        for role_name in ("Jailed", "Muted", "Image Muted", "Reaction Muted"):
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                with contextlib.suppress(Exception):
                    await role.delete(reason=reason)

        with contextlib.suppress(Exception):
            from ext.moderation.extended.setup.settings import Settings

            await Settings.clear_modlog_config(self.bot.db, guild.id)
        with contextlib.suppress(Exception):
            await Settings.clear_log_config(self.bot.db, guild.id)
        with contextlib.suppress(Exception):
            await Settings.clear_jail_and_mute_config(self.bot.db, guild.id)
        with contextlib.suppress(Exception):
            from ext.server.extended.voicemaster.settings import Settings as VMSettings

            settings = await VMSettings.fetch(self.bot, guild)
            await settings.delete()
