from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import discord
from discord import ui

from core.discord.ctx import layout_from_items

if TYPE_CHECKING:
    from core.vain import Vain

LOADING = "<a:loading:1534646618693963807>"
BOT_NAME = "vain"


def _clear_accent(container: ui.Container) -> None:
    for attr in ("accent_color", "accent_colour", "color", "colour"):
        if hasattr(container, attr):
            with contextlib.suppress(Exception):
                setattr(container, attr, None)


def build_setup_intro(*, prefix: str = ",") -> ui.LayoutView:
    body = (
        f"> -# {BOT_NAME.title()}'s default prefix is set to `{prefix}`\n"
        f"> -# This prefix can be changed by using `{prefix}prefix set {{prefix}}`\n"
        f"> -# Move my role as high as possible in your role list\n"
        f"> -# Make sure my role has **Administrator** permissions\n"
        f"> -# Click **Automatic Setup** to configure the following:\n"
        f"> -# - VoiceMaster\n"
        f"> -# - jail configuration\n"
        f"> -# - mute roles\n"
        f"> -# - logging\n"
        f"> -# - antinuke\n"
        f"> -# - antiraid"
    )
    container = ui.Container()
    _clear_accent(container)
    container.add_item(ui.TextDisplay(f"**{BOT_NAME} setup**"))
    try:
        container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
    except Exception:
        try:
            container.add_item(ui.Separator(visible=True))
        except Exception:
            pass
    container.add_item(ui.TextDisplay(body))
    return layout_from_items([container], timeout=None)


def build_setup_loading() -> ui.LayoutView:
    container = ui.Container()
    _clear_accent(container)
    container.add_item(
        ui.TextDisplay(
            f"{LOADING} Setting up **{BOT_NAME}**...\n"
            f"> -# Configuring VoiceMaster, logs, jail, mute roles, antinuke and antiraid"
        )
    )
    return layout_from_items([container], timeout=None)


def build_setup_done(*, prefix: str = ",") -> ui.LayoutView:
    body = (
        f"Thank you for setting up **{BOT_NAME}**\n"
        f"> -# Feel free to move around and change any of the channels, categories or role names\n"
        f"> -# Use `{prefix}antinuke setup` and `{prefix}antiraid setup` to fine-tune protection\n"
        f"> -# Use `{prefix}prefix set` to change the guild prefix anytime\n"
        f"> -# Use **embedbuilder** and **containerbuilder** to design your own embeds and containers"
    )
    container = ui.Container()
    _clear_accent(container)
    container.add_item(ui.TextDisplay(body))
    return layout_from_items([container], timeout=None)


def build_setup_reverting() -> ui.LayoutView:
    container = ui.Container()
    _clear_accent(container)
    container.add_item(
        ui.TextDisplay(
            f"{LOADING} **Reverting changes**...\n"
            f"> -# Removing setup channels, categories and related configuration"
        )
    )
    return layout_from_items([container], timeout=None)


def build_setup_reverted(*, prefix: str = ",") -> ui.LayoutView:
    container = ui.Container()
    _clear_accent(container)
    container.add_item(
        ui.TextDisplay(
            f"**Setup reverted**\n"
            f"> -# Categories and channels created by automatic setup were removed\n"
            f"> -# Run `{prefix}setup` anytime to configure again"
        )
    )
    return layout_from_items([container], timeout=None)


class SetupView(ui.LayoutView):
    """Interactive vain automatic setup."""

    def __init__(
        self,
        bot: "Vain",
        *,
        guild: discord.Guild,
        author_id: int | None = None,
        prefix: str = ",",
        message: discord.Message | None = None,
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.author_id = author_id
        self.prefix = prefix
        self.message = message
        self._created: list[tuple[str, int]] = []
        self._build_intro()

    def _build_intro(self) -> None:
        self.clear_items()
        body = (
            f"> -# {BOT_NAME.title()}'s default prefix is set to `{self.prefix}`\n"
            f"> -# This prefix can be changed by using `{self.prefix}prefix set {{prefix}}`\n"
            f"> -# Move my role as high as possible in your role list\n"
            f"> -# Make sure my role has **Administrator** permissions\n"
            f"> -# Click **Automatic Setup** to configure the following:\n"
            f"> -# - VoiceMaster\n"
            f"> -# - jail configuration\n"
            f"> -# - mute roles\n"
            f"> -# - logging\n"
            f"> -# - antinuke\n"
            f"> -# - antiraid"
        )
        container = ui.Container()
        _clear_accent(container)
        container.add_item(ui.TextDisplay(f"**{BOT_NAME} setup**"))
        try:
            container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        except Exception:
            with contextlib.suppress(Exception):
                container.add_item(ui.Separator(visible=True))
        container.add_item(ui.TextDisplay(body))
        row = ui.ActionRow()
        btn = ui.Button(label="Automatic Setup", style=discord.ButtonStyle.primary)
        btn.callback = self._on_automatic
        row.add_item(btn)
        container.add_item(row)
        self.add_item(container)

    def _build_loading(self) -> None:
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(
            ui.TextDisplay(
                f"{LOADING} Setting up **{BOT_NAME}**...\n"
                f"> -# Configuring VoiceMaster, logs, jail, mute roles, antinuke and antiraid"
            )
        )
        self.add_item(container)

    def _build_done(self) -> None:
        self.clear_items()
        body = (
            f"Thank you for setting up **{BOT_NAME}**\n"
            f"> -# Feel free to move around and change any of the channels, categories or role names\n"
            f"> -# Use `{self.prefix}antinuke setup` and `{self.prefix}antiraid setup` to fine-tune protection\n"
            f"> -# Use `{self.prefix}prefix set` to change the guild prefix anytime\n"
            f"> -# Use **embedbuilder** and **containerbuilder** to design your own embeds and containers"
        )
        container = ui.Container()
        _clear_accent(container)
        container.add_item(ui.TextDisplay(body))
        row = ui.ActionRow()
        btn = ui.Button(label="Revert changes", style=discord.ButtonStyle.primary)
        btn.callback = self._on_revert
        row.add_item(btn)
        container.add_item(row)
        self.add_item(container)

    def _build_reverting(self) -> None:
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(
            ui.TextDisplay(
                f"{LOADING} **Reverting changes**...\n"
                f"> -# Removing setup channels, categories and related configuration"
            )
        )
        self.add_item(container)

    def _build_reverted(self) -> None:
        self.clear_items()
        container = ui.Container()
        _clear_accent(container)
        container.add_item(
            ui.TextDisplay(
                f"**Setup reverted**\n"
                f"> -# Categories and channels created by automatic setup were removed\n"
                f"> -# Run `{self.prefix}setup` anytime to configure again"
            )
        )
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id is None:
            return True
        if interaction.user and interaction.user.id == self.author_id:
            return True
        if interaction.user and interaction.guild:
            member = interaction.guild.get_member(interaction.user.id)
            if member and member.guild_permissions.administrator:
                return True
        with contextlib.suppress(Exception):
            await interaction.response.send_message(
                "Only an **administrator** can use this setup.",
                ephemeral=True,
            )
        return False

    async def _edit(self, interaction: discord.Interaction | None = None) -> None:
        if interaction is not None and not interaction.response.is_done():
            with contextlib.suppress(Exception):
                await interaction.response.edit_message(view=self)
                return
        if self.message is not None:
            with contextlib.suppress(Exception):
                await self.message.edit(view=self)

    async def _on_automatic(self, interaction: discord.Interaction) -> None:
        self._build_loading()
        await self._edit(interaction)
        try:
            await self._run_setup()
        except Exception as e:
            self.clear_items()
            container = ui.Container()
            _clear_accent(container)
            container.add_item(
                ui.TextDisplay(
                    f"**Setup failed**\n> -# `{e}`\n> -# Fix permissions and try again"
                )
            )
            self.add_item(container)
            await self._edit()
            return
        self._build_done()
        await self._edit()

    async def _on_revert(self, interaction: discord.Interaction) -> None:
        self._build_reverting()
        await self._edit(interaction)
        try:
            await self._run_revert()
        except Exception as e:
            self.clear_items()
            container = ui.Container()
            _clear_accent(container)
            container.add_item(
                ui.TextDisplay(f"**Revert failed**\n> -# `{e}`")
            )
            self.add_item(container)
            await self._edit()
            return
        self._build_reverted()
        await self._edit()

    async def _run_setup(self) -> None:
        guild = self.guild
        me = guild.me
        if me is None:
            me = guild.get_member(self.bot.user.id)
        reason = f"{BOT_NAME} automatic setup"

        
        overwrites_logs = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
        }
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites_logs[role] = discord.PermissionOverwrite(view_channel=True)

        logs_cat = discord.utils.get(guild.categories, name="logs")
        if logs_cat is None:
            logs_cat = await guild.create_category("logs", overwrites=overwrites_logs, reason=reason)
            self._created.append(("category", logs_cat.id))
        else:
            with contextlib.suppress(Exception):
                await logs_cat.edit(overwrites=overwrites_logs)

        log_ch = discord.utils.get(logs_cat.text_channels, name="logs")
        if log_ch is None:
            log_ch = await logs_cat.create_text_channel("logs", topic="All server logs", reason=reason)
            self._created.append(("channel", log_ch.id))

        
        with contextlib.suppress(Exception):
            await self.bot.db.execute(
                """INSERT INTO modlog_config (guild_id, channel_id)
                   VALUES ($1, $2)
                   ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2""",
                guild.id,
                log_ch.id,
            )
        with contextlib.suppress(Exception):
            await self.bot.db.set_security_log_channels(
                guild.id,
                antinuke_channel_id=log_ch.id,
                antiraid_channel_id=log_ch.id,
            )
        
        with contextlib.suppress(Exception):
            await self.bot.db.execute(
                """
                INSERT INTO log_channels (guild_id, channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2
                """,
                guild.id,
                log_ch.id,
            )

        
        jail_role = discord.utils.get(guild.roles, name="Jailed")
        if jail_role is None:
            jail_role = await guild.create_role(
                name="Jailed",
                colour=discord.Colour.dark_grey(),
                reason=reason,
            )
            self._created.append(("role", jail_role.id))

        overwrites_jail = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
            me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
            jail_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites_jail[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        jail_cat = discord.utils.get(guild.categories, name="jail")
        if jail_cat is None:
            jail_cat = await guild.create_category("jail", overwrites=overwrites_jail, reason=reason)
            self._created.append(("category", jail_cat.id))
        jailed_ch = discord.utils.get(jail_cat.text_channels, name="jailed")
        if jailed_ch is None:
            jailed_ch = await jail_cat.create_text_channel("jailed", reason=reason)
            self._created.append(("channel", jailed_ch.id))
        with contextlib.suppress(Exception):
            await jailed_ch.edit(overwrites=overwrites_jail)

        with contextlib.suppress(Exception):
            await self.bot.db.execute(
                """INSERT INTO server_settings (guild_id, jail_channel_id, jail_role_id)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (guild_id) DO UPDATE
                   SET jail_channel_id = $2, jail_role_id = $3""",
                guild.id,
                jailed_ch.id,
                jail_role.id,
            )

        
        for channel in guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.ForumChannel)):
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

        
        mute_role = discord.utils.get(guild.roles, name="Muted")
        if mute_role is None:
            mute_role = await guild.create_role(
                name="Muted",
                colour=discord.Colour.dark_grey(),
                reason=reason,
            )
            self._created.append(("role", mute_role.id))
        with contextlib.suppress(Exception):
            await self.bot.db.execute(
                """INSERT INTO server_settings (guild_id, mute_role_id)
                   VALUES ($1, $2)
                   ON CONFLICT (guild_id) DO UPDATE SET mute_role_id = $2""",
                guild.id,
                mute_role.id,
            )
        for channel in guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.ForumChannel)):
                with contextlib.suppress(Exception):
                    await channel.set_permissions(
                        mute_role,
                        send_messages=False,
                        add_reactions=False,
                        speak=False,
                        reason=reason,
                    )

        
        with contextlib.suppress(Exception):
            from ext.server.extended.voicemaster.settings import VoiceMasterSettings
            exists = False
            with contextlib.suppress(Exception):
                exists = await VoiceMasterSettings.exists(self.bot, guild)
            if not exists:
                vm_cat = await guild.create_category("Voice Channels", reason=reason)
                self._created.append(("category", vm_cat.id))
                interface = await vm_cat.create_text_channel("interface", reason=reason)
                self._created.append(("channel", interface.id))
                join_vc = await vm_cat.create_voice_channel("Join to Create", reason=reason)
                self._created.append(("channel", join_vc.id))
                everyone = guild.default_role
                with contextlib.suppress(Exception):
                    await interface.set_permissions(
                        everyone,
                        send_messages=False,
                        send_messages_in_threads=False,
                        create_public_threads=False,
                        create_private_threads=False,
                    )
                settings = await VoiceMasterSettings.fetch(self.bot, guild)
                await settings.upsert(
                    category_id=vm_cat.id,
                    interface_id=interface.id,
                    channel_id=join_vc.id,
                )
                
                cog = self.bot.get_cog("VoiceMaster") or self.bot.get_cog("Voicemaster")
                if cog is not None and hasattr(cog, "_interface_embed"):
                    with contextlib.suppress(Exception):
                        from ext.server.extended.voicemaster import VoiceInterface
                        await interface.send(
                            embed=cog._interface_embed(guild),
                            view=VoiceInterface(cog),
                        )

        
        with contextlib.suppress(Exception):
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

        
        with contextlib.suppress(Exception):
            cog = self.bot.get_cog("Antiraid") or self.bot.get_cog("Security")
            if cog is not None:
                if hasattr(cog, "enable_antiraid_defaults"):
                    await cog.enable_antiraid_defaults(guild.id)
                elif hasattr(cog, "_enable_antiraid"):
                    await cog._enable_antiraid(guild.id)

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
        for role_name in ("Jailed", "Muted"):
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                with contextlib.suppress(Exception):
                    await role.delete(reason=reason)
        with contextlib.suppress(Exception):
            await self.bot.db.execute("DELETE FROM modlog_config WHERE guild_id = $1", guild.id)
        with contextlib.suppress(Exception):
            from ext.server.extended.voicemaster.settings import VoiceMasterSettings
            settings = await VoiceMasterSettings.fetch(self.bot, guild)
            await settings.delete()
