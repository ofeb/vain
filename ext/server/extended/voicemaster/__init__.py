from __future__ import annotations

from typing import TYPE_CHECKING

from core.discord.ctx import layout_from_items

if TYPE_CHECKING:
    from core.vain import Vain

import asyncio
import contextlib
from typing import Optional, Union

import discord
from discord import app_commands, ui
from discord.ext import commands

from core.discord.package import Package, tasks

from .events import VoiceMasterEvents

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from config import bot as bot_config, color
from .improper.views import VoiceInterface
from core.managers.permissions import has_permissions
from .settings import Settings as VoiceMasterSettings


def _vm_container(text: str) -> ui.LayoutView:
    from discord import ui
    c = ui.Container()
    for attr in ("accent_color", "accent_colour"):
        if hasattr(c, attr):
            with contextlib.suppress(Exception):
                setattr(c, attr, None)
    c.add_item(ui.TextDisplay(text))
    return layout_from_items([c], timeout=None)


class VoiceMaster(VoiceMasterEvents, Package):
    """Voice channel management system."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._cooldowns: dict = {}
        self.bot.add_view(VoiceInterface(self))

    def _panel_view(self, guild: discord.Guild) -> discord.ui.LayoutView:
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
        container = discord.ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)

        server_icon = guild.icon.url if guild.icon else None
        header_text = (
            f"## {guild.name}\n"
            f"-# Manage temporary voice channels in **{guild.name}**."
        )
        if server_icon:
            container.add_item(discord.ui.Section(
                discord.ui.TextDisplay(header_text),
                accessory=discord.ui.ActionRow(
                    discord.ui.Thumbnail(media=server_icon),
                ),
            ))
        else:
            container.add_item(discord.ui.TextDisplay(header_text))
        container.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))

        controls = (
            f">>> **Controls**\n"
            f"{VM['lock']} — **Lock** the channel\n"
            f"{VM['unlock']} — **Unlock** the channel\n"
            f"{VM['claim']} — **Claim** the channel\n"
            f"{VM['delete']} — **Delete** the channel\n"
            f"{VM['disconnect']} — **Disconnect** member(s)\n"
            f"{VM['hide']} — **Hide** the channel\n"
            f"{VM['reveal']} — **Reveal** the channel\n"
            f"{VM['limit']} — Set a user **limit**\n"
            f"{VM['rename']} — **Rename** the channel"
        )
        container.add_item(discord.ui.TextDisplay(controls))
        container.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))

        row1 = discord.ui.ActionRow(
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["lock"], custom_id="voicemaster:lock"),
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["unlock"], custom_id="voicemaster:unlock"),
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["claim"], custom_id="voicemaster:claim"),
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["delete"], custom_id="voicemaster:delete"),
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["disconnect"], custom_id="voicemaster:disconnect"),
        )
        container.add_item(row1)
        row2 = discord.ui.ActionRow(
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["hide"], custom_id="voicemaster:hide"),
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["reveal"], custom_id="voicemaster:reveal"),
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["limit"], custom_id="voicemaster:limit"),
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["rename"], custom_id="voicemaster:rename"),
            discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=VM["status"], custom_id="voicemaster:status"),
        )
        container.add_item(row2)
        container.add_item(discord.ui.TextDisplay("-# You must own the voice channel to use these controls."))
        return layout_from_items([container], timeout=None)

    async def cog_load(self) -> None:
        if getattr(self.bot.db, "pool", None) is None:
            return
        await VoiceMasterSettings.ensure_schema(self.bot.db)
        if not self._cleanup_loop.is_running():
            self._cleanup_loop.start()
        if not self._panel_refresh_loop.is_running():
            self._panel_refresh_loop.start()

    async def cog_unload(self) -> None:
        self._cleanup_loop.cancel()
        self._panel_refresh_loop.cancel()

    @tasks.loop(minutes=1)
    async def _cleanup_loop(self):
        await self._cleanup_empty_channels()

    @_cleanup_loop.before_loop
    async def _before_cleanup_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _cleanup_empty_channels(self):
        if getattr(self.bot.db, "pool", None) is None:
            return
        to_delete = []
        rows = await VoiceMasterSettings.fetch_all_channel_ids(self.bot.db)
        for row in rows:
            channel_id = row["channel_id"]
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                with contextlib.suppress(discord.HTTPException, discord.Forbidden, discord.NotFound):
                    channel = await self.bot.fetch_channel(channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                to_delete.append(channel_id)
                continue
            if not channel.members:
                try:
                    await channel.delete(reason="VoiceMaster: Empty channel cleanup")
                except discord.HTTPException:
                    pass
                to_delete.append(channel_id)
        if to_delete:
            await VoiceMasterSettings.delete_empty_channels(self.bot.db, to_delete)

    @tasks.loop(hours=6)
    async def _panel_refresh_loop(self):
        await self._refresh_all_panels()

    @_panel_refresh_loop.before_loop
    async def _before_panel_refresh_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _refresh_all_panels(self):
        if getattr(self.bot.db, "pool", None) is None:
            return
        rows = await VoiceMasterSettings.fetch_all_panel_rows(self.bot.db)
        for row in rows:
            guild_id = row["guild_id"]
            interface_id = row["interface_id"]
            old_msg_id = row["panel_message_id"]
            if not interface_id:
                continue
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            channel = guild.get_channel(interface_id)
            if not channel:
                continue
            if old_msg_id:
                with contextlib.suppress(Exception):
                    old_msg = await channel.fetch_message(old_msg_id)
                    await old_msg.delete()
            try:
                msg = await channel.send(view=self._panel_view(guild))
                settings = await VoiceMasterSettings.fetch(self.bot, guild)
                await settings.upsert(panel_message_id=msg.id)
            except Exception:
                continue

    async def reconfigure_after_nuke(self, old_channel_id: int, new_channel: discord.TextChannel) -> None:
        """Re-send the voicemaster panel if the nuked channel was the interface."""
        if getattr(self.bot.db, "pool", None) is None:
            return
        settings = await VoiceMasterSettings.fetch(self.bot, new_channel.guild)
        if not settings.record.get("interface_id"):
            return
        try:
            msg = await new_channel.send(view=self._panel_view(new_channel.guild))
            await settings.upsert(panel_message_id=msg.id)
        except Exception:
            pass

    def _get_cooldown(self, key: str, rate: int, per: float) -> Optional[float]:
        now = asyncio.get_event_loop().time()
        if key not in self._cooldowns:
            self._cooldowns[key] = (now, 0)
        last_time, count = self._cooldowns[key]
        if now - last_time > per:
            self._cooldowns[key] = (now, 0)
            return None
        if count >= rate:
            return per - (now - last_time)
        self._cooldowns[key] = (last_time, count + 1)
        return None

    @staticmethod
    def _resolve_channel_name(config, member: discord.Member) -> str:
        value = str(config.get("default_name") or "").strip()
        if value:
            return value
        return f"{member.display_name}'s channel"

    @staticmethod
    def _resolve_region(config) -> str | None:
        value = str(config.get("region") or "").strip().lower()
        if value in {"", "auto", "none", "null"}:
            return None
        return value

    @staticmethod
    def _resolve_bitrate(config, guild: discord.Guild) -> int | None:
        raw_limit = getattr(guild, "bitrate_limit", None)
        try:
            guild_limit = int(raw_limit) if raw_limit is not None else None
        except (TypeError, ValueError):
            guild_limit = None
        raw_value = config.get("bitrate")
        try:
            bitrate = int(raw_value) if raw_value not in (None, "") else 64000
        except (TypeError, ValueError):
            bitrate = 64000
        if bitrate <= 0:
            bitrate = 64000
        if guild_limit is not None and guild_limit > 0:
            return min(bitrate, guild_limit)
        return bitrate

    async def _create_member_channel(
        self, member: discord.Member, config, trigger_channel: discord.VoiceChannel,
    ) -> None:
        category = member.guild.get_channel(config["category_id"]) or trigger_channel.category
        channel = await member.guild.create_voice_channel(
            name=self._resolve_channel_name(config, member),
            category=category,
            bitrate=self._resolve_bitrate(config, member.guild),
            rtc_region=self._resolve_region(config),
            reason=f"VoiceMaster: Created channel for {member}",
        )
        try:
            await member.move_to(channel, reason="VoiceMaster: Moved to new channel")
        except discord.HTTPException:
            await channel.delete(reason="VoiceMaster: Failed to move member")
            return
        await channel.set_permissions(
            member, read_messages=True, connect=True,
            reason=f"VoiceMaster: Owner permissions for {member}",
        )
        await VoiceMasterSettings.insert_channel(
            self.bot.db, member.guild.id, channel.id, member.id,
        )
        status_text = config.get("default_status_text") or ""
        status_emoji = config.get("default_status_emoji") or ""
        if status_text or status_emoji:
            await VoiceMasterSettings.update_channel_status(
                self.bot.db, channel.id, status_text, status_emoji,
            )
        if role_id := config.get("role_id"):
            role = member.guild.get_role(role_id)
            if role and role not in member.roles:
                with contextlib.suppress(discord.HTTPException):
                    await member.add_roles(role, reason="VoiceMaster: Default role")

    async def cog_check(self, ctx: Context) -> bool:
        admin_commands = {
            "voicemaster", "voicemaster setup", "voicemaster reset", "voicemaster unset",
            "voicemaster category", "voicemaster category private", "voicemaster default",
            "voicemaster default interface", "voicemaster default role", "voicemaster default bitrate",
            "voicemaster default name", "voicemaster default region",
            "voicemaster sendinterface", "voicemaster join2unmute",
            "voicemaster messages", "voicemaster bypassed", "voicemaster private",
            "voicemaster ban", "voicemaster unban", "voicemaster bans",
        }
        if ctx.command.qualified_name in admin_commands:
            return True
        if not ctx.author.voice:
            raise commands.CommandError("you're not connected to a **voice channel**")
        owner_id = await VoiceMasterSettings.get_channel_owner(
            self.bot.db, ctx.author.voice.channel.id,
        )
        if not owner_id:
            raise commands.CommandError("you're not in a **voicemaster** channel!")
        if ctx.command.qualified_name == "voicemaster claim":
            if ctx.author.id == owner_id:
                raise commands.CommandError("you already own this **voice channel**!")
            if owner_id in (m.id for m in ctx.author.voice.channel.members):
                raise commands.CommandError("the owner is still active in this channel!")
            return True
        if ctx.author.id != owner_id:
            raise commands.CommandError("you **don't** own this **voice channel**!")
        return True

    @group(name="voicemaster", description="manage temporary voice channels in your server", guild_only=True, invoke_without_command=True)
    async def voicemaster(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @voicemaster.command(name="setup")
    @has_permissions(manage_guild=True)
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def voicemaster_setup(self, ctx: Context) -> None:
        """setup the voicemaster channel creation system"""
        if await VoiceMasterSettings.exists(self.bot, ctx.guild):
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is already **configured**, use `voicemaster reset` to reset"))
        category = await ctx.guild.create_category("Voice Channels")
        interface = await category.create_text_channel("interface")
        channel = await category.create_voice_channel("Join to Create")
        everyone = ctx.guild.default_role
        await interface.set_permissions(everyone, send_messages=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
        await channel.set_permissions(everyone, connect=True)
        panel_msg = await interface.send(view=self._panel_view(ctx.guild))
        settings = await VoiceMasterSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(category_id=category.id, interface_id=interface.id, channel_id=channel.id, panel_message_id=panel_msg.id)
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: voicemaster **setup complete**"))

    @voicemaster.command(name="reset")
    @has_permissions(manage_guild=True)
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def voicemaster_reset(self, ctx: Context) -> None:
        """reset the voicemaster configuration and delete channels"""
        existing = await VoiceMasterSettings.fetch_existing_config(self.bot.db, ctx.guild.id)
        if not existing:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))
        from core.discord.views.confirm import ConfirmView
        view = ConfirmView(ctx)
        ok = await view.prompt("reset voicemaster and **delete** its category/channels? this action **can't be undone**")
        if not ok:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: reset **cancelled**"))
        row = await VoiceMasterSettings.delete_config_returning(self.bot.db, ctx.guild.id)
        if row:
            for channel_id in row:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    with contextlib.suppress(discord.HTTPException):
                        await channel.delete()
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: voicemaster **reset**"))
        else:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="unset", aliases=["remove"])
    @has_permissions(manage_guild=True)
    async def voicemaster_unset(self, ctx: Context) -> None:
        """remove voicemaster configuration without deleting channels"""
        row = await VoiceMasterSettings.delete_config_returning_category(self.bot.db, ctx.guild.id)
        if row:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: configuration **removed**, channels kept"))
        else:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="category")
    @has_permissions(manage_guild=True)
    @describe(channel="voice channel category")
    async def voicemaster_category(self, ctx: Context, channel: discord.CategoryChannel) -> None:
        """set the category for new voice channels"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "category_id", channel.id,
            )
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: set {channel.mention} as the voice category"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="category private", slash=False)
    @has_permissions(manage_guild=True)
    @describe(channel="private voice channel category")
    async def voicemaster_category_private(self, ctx: Context, channel: discord.CategoryChannel) -> None:
        """set the private category for locked/hidden channels"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "private_category_id", channel.id,
            )
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: set {channel.mention} as the private category"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="default")
    async def voicemaster_default(self, ctx: Context) -> None:
        """view default voicemaster settings"""
        config = await VoiceMasterSettings.get_config(self.bot.db, ctx.guild.id)
        if not config:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))
        lines = (
            f"> **bitrate**: `{config.get('bitrate', 64000) // 1000}kbps`\n"
            f"> **region**: `{config.get('region', 'auto')}`\n"
            f"> **role**: <@{config.get('role_id', 0)}>\n"
            f"> **default name**: `{config.get('default_name', 'none')}`"
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}:\n{lines}"))

    @voicemaster.command(name="default interface", slash=False)
    @describe(setting="enable or disable interface")
    async def voicemaster_default_interface(self, ctx: Context, setting: bool) -> None:
        """send interface to new voice channels"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "send_interface", setting,
            )
            state = "enabled" if setting else "disabled"
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: interface sending **{state}**"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="default role", slash=False)
    @has_permissions(manage_guild=True, manage_roles=True)
    @describe(role="default role for voice channels")
    async def voicemaster_default_role(self, ctx: Context, role: discord.Role) -> None:
        """set the default role granted on channel join"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "role_id", role.id,
            )
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: set {role.mention} as default role"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="default bitrate", slash=False)
    @has_permissions(manage_guild=True)
    @describe(bitrate="default bitrate in kbps")
    async def voicemaster_default_bitrate(self, ctx: Context, bitrate: int) -> None:
        """set default bitrate for new voice channels"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "bitrate", bitrate * 1000,
            )
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: set default bitrate to **{bitrate}kbps**"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="default name", slash=False)
    @has_permissions(manage_guild=True)
    @describe(name="default name for new channels")
    async def voicemaster_default_name(self, ctx: Context, name: str) -> None:
        """set default name for new voice channels"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "default_name", name,
            )
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: set default name to **{name}**"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="default region", slash=False)
    @has_permissions(manage_guild=True)
    @describe(region="voice region")
    async def voicemaster_default_region(self, ctx: Context, region: str) -> None:
        """set default region for new voice channels"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "region", region.lower(),
            )
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: set default region to **{region}**"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="claim")
    async def voicemaster_claim(self, ctx: Context) -> None:
        """claim ownership of the voice channel"""
        await VoiceMasterSettings.update_channel_owner(
            self.bot.db, ctx.author.voice.channel.id, ctx.author.id,
        )
        if ctx.author.voice.channel.name.endswith("channel"):
            with contextlib.suppress(discord.HTTPException):
                await ctx.author.voice.channel.edit(name=f"{ctx.author.display_name}'s channel")
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: you now **own** this channel"))

    @voicemaster.command(name="transfer")
    @describe(member="member to transfer ownership to")
    async def voicemaster_transfer(self, ctx: Context, member: discord.Member) -> None:
        """transfer ownership of your voice channel"""
        if member == ctx.author or member.bot:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: invalid member"))
        if not member.voice or member.voice.channel != ctx.author.voice.channel:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: {member.mention} is not in your channel"))
        await VoiceMasterSettings.update_channel_owner(
            self.bot.db, ctx.author.voice.channel.id, member.id,
        )
        if ctx.author.voice.channel.name.endswith("channel"):
            with contextlib.suppress(discord.HTTPException):
                await ctx.author.voice.channel.edit(name=f"{member.display_name}'s channel")
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: ownership **transferred** to {member.mention}"))

    @voicemaster.command(name="rename")
    @describe(name="new channel name")
    async def voicemaster_rename(self, ctx: Context, name: str) -> None:
        """rename your voice channel"""
        if len(name) > 100:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: name too long (max 100 characters)"))
        try:
            await ctx.author.voice.channel.edit(name=name, reason=f"VoiceMaster: {ctx.author} renamed")
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: channel renamed to **{name}**"))
        except discord.HTTPException:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: failed to rename channel"))

    @voicemaster.command(name="lock")
    async def voicemaster_lock(self, ctx: Context) -> None:
        """deny members from joining your voice channel"""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role, connect=False,
            reason=f"VoiceMaster: {ctx.author} locked channel",
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: voice channel **locked**"))

    @voicemaster.command(name="unlock")
    async def voicemaster_unlock(self, ctx: Context) -> None:
        """allow members to join your voice channel"""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role, connect=None,
            reason=f"VoiceMaster: {ctx.author} unlocked channel",
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: voice channel **unlocked**"))

    @voicemaster.command(name="hide")
    async def voicemaster_hide(self, ctx: Context) -> None:
        """hide your voice channel from the channel list"""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role, view_channel=False,
            reason=f"VoiceMaster: {ctx.author} hid channel",
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: voice channel **hidden**"))

    @voicemaster.command(name="reveal")
    async def voicemaster_reveal(self, ctx: Context) -> None:
        """reveal your voice channel in the channel list"""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role, view_channel=None,
            reason=f"VoiceMaster: {ctx.author} revealed channel",
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: voice channel **revealed**"))

    @voicemaster.command(name="limit")
    @describe(limit="user limit (0-99)")
    async def voicemaster_limit(self, ctx: Context, limit: int) -> None:
        """set a user limit for your voice channel"""
        if limit < 0 or limit > 99:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: limit must be between **0** and **99**"))
        await ctx.author.voice.channel.edit(user_limit=limit, reason=f"VoiceMaster: {ctx.author} set limit")
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: limit set to **{limit}**"))

    @voicemaster.command(name="status")
    @describe(text="status text", emoji="status emoji")
    async def voicemaster_status(self, ctx: Context, text: str = "", emoji: str = "") -> None:
        """set the status/description of your voice channel"""
        channel = ctx.author.voice.channel
        await VoiceMasterSettings.update_channel_status(
            self.bot.db, channel.id, text, emoji,
        )
        display = f"{emoji} {text}" if emoji and text else text or emoji or "status **cleared**"
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: channel status set to **{display}**"))

    @voicemaster.command(name="permit")
    @describe(target="member or role to permit")
    async def voicemaster_permit(self, ctx: Context, target: Union[discord.Member, discord.Role]) -> None:
        """allow a member or role to join your voice channel"""
        await ctx.author.voice.channel.set_permissions(
            target, connect=True, view_channel=True,
            reason=f"VoiceMaster: {ctx.author} permitted {target}",
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: permitted {target.mention}"))

    @voicemaster.command(name="reject")
    @describe(target="member or role to reject")
    async def voicemaster_reject(self, ctx: Context, target: Union[discord.Member, discord.Role]) -> None:
        """deny a member or role from joining your voice channel"""
        await ctx.author.voice.channel.set_permissions(
            target, connect=False,
            reason=f"VoiceMaster: {ctx.author} rejected {target}",
        )
        if isinstance(target, discord.Member):
            if target.voice and target.voice.channel == ctx.author.voice.channel:
                with contextlib.suppress(discord.HTTPException):
                    await target.move_to(None)
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: rejected {target.mention}"))

    @voicemaster.command(name="bitrate")
    @describe(bitrate="bitrate in kbps")
    async def voicemaster_bitrate(self, ctx: Context, bitrate: int) -> None:
        """set the bitrate of your voice channel"""
        await ctx.author.voice.channel.edit(
            bitrate=bitrate * 1000,
            reason=f"VoiceMaster: {ctx.author} set bitrate",
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: bitrate set to **{bitrate}kbps**"))

    @voicemaster.command(name="role")
    @describe(role="role to grant on join")
    async def voicemaster_role(self, ctx: Context, role: discord.Role) -> None:
        """set the role granted to members who join your channel"""
        await VoiceMasterSettings.update_channel_field(
            self.bot.db, ctx.author.voice.channel.id, "role_id", role.id,
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: set {role.mention} as join role"))

    @voicemaster.command(name="music")
    @describe(setting="enable or disable music mode")
    async def voicemaster_music(self, ctx: Context, setting: bool) -> None:
        """toggle music mode for your voice channel"""
        await VoiceMasterSettings.update_channel_field(
            self.bot.db, ctx.author.voice.channel.id, "music_mode", setting,
        )
        state = "enabled" if setting else "disabled"
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: music mode **{state}**"))

    @voicemaster.command(name="sendinterface")
    async def voicemaster_sendinterface(self, ctx: Context) -> None:
        """resend the voicemaster interface panel"""
        config = await VoiceMasterSettings.fetch_interface_id(self.bot.db, ctx.guild.id)
        if not config:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: server **not configured**"))
        interface = ctx.guild.get_channel(config["interface_id"])
        if not interface:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: interface channel **not found**"))
        panel_msg = await interface.send(view=self._panel_view(ctx.guild))
        settings = await VoiceMasterSettings.fetch(self.bot, ctx.guild)
        await settings.upsert(panel_message_id=panel_msg.id)
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: interface **resent**"))

    @voicemaster.command(name="configuration")
    async def voicemaster_configuration(self, ctx: Context) -> None:
        """view configuration for your current voice channel"""
        channel = ctx.author.voice.channel
        locked = channel.permissions_for(ctx.guild.default_role).connect is False
        lines = (
            f"> **owner**: {ctx.author.mention}\n"
            f"> **locked**: {'yes' if locked else 'no'}\n"
            f"> **members**: `{len(channel.members)}`\n"
            f"> **bitrate**: `{channel.bitrate // 1000}kbps`\n"
            f"> **limit**: `{channel.user_limit or 'unlimited'}`"
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention} - **{channel.name}**\n{lines}"))

    @voicemaster.command(name="join2unmute")
    @has_permissions(manage_guild=True)
    @describe(channel="voice channel to use as join2unmute")
    async def voicemaster_join2unmute(self, ctx: Context, channel: discord.VoiceChannel) -> None:
        """create a channel that auto-unmutes server muted users"""
        added = await VoiceMasterSettings.toggle_join2unmute(
            self.bot.db, ctx.guild.id, channel.id,
        )
        if added:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: {channel.mention} set as **join2unmute** channel"))
        else:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: {channel.mention} **removed** from join2unmute"))

    @voicemaster.command(name="ban")
    @has_permissions(manage_guild=True)
    @describe(member="member to ban from voicemaster channels")
    async def voicemaster_ban(self, ctx: Context, member: discord.Member) -> None:
        """ban a user from joining your voicemaster channels"""
        if member == ctx.author:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: you can't **ban yourself**"))
        existing = await VoiceMasterSettings.check_ban(
            self.bot.db, ctx.guild.id, member.id,
        )
        if existing:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: {member.mention} is **already banned**"))
        await VoiceMasterSettings.insert_ban(
            self.bot.db, ctx.guild.id, member.id, ctx.author.id,
        )
        if member.voice and member.voice.channel:
            vm_channel_ids = await VoiceMasterSettings.fetch_guild_channel_ids(
                self.bot.db, ctx.guild.id,
            )
            if member.voice.channel.id in vm_channel_ids:
                with contextlib.suppress(discord.HTTPException):
                    await member.move_to(None, reason="VoiceMaster: banned from voicemaster")
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: {member.mention} **banned** from voicemaster channels"))

    @voicemaster.command(name="unban")
    @has_permissions(manage_guild=True)
    @describe(member="member to unban from voicemaster channels")
    async def voicemaster_unban(self, ctx: Context, member: discord.Member) -> None:
        """remove a user's ban from your voicemaster channels"""
        deleted = await VoiceMasterSettings.remove_ban(
            self.bot.db, ctx.guild.id, member.id,
        )
        if deleted:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: {member.mention} **unbanned** from voicemaster channels"))
        else:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: {member.mention} is **not banned**"))

    @voicemaster.command(name="bans")
    @has_permissions(manage_guild=True)
    async def voicemaster_bans(self, ctx: Context) -> None:
        """view users banned from your voicemaster channels"""
        rows = await VoiceMasterSettings.get_bans(self.bot.db, ctx.guild.id)
        if not rows:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: no **banned** users"))
        lines = [f"> <@{r['user_id']}>" for r in rows[:25]]
        await ctx.send(view=_vm_container(f"{ctx.author.mention}:\n" + "\n".join(lines)))

    @voicemaster.command(name="messages")
    @has_permissions(manage_guild=True)
    @describe(setting="enable or disable")
    async def voicemaster_messages(self, ctx: Context, setting: bool) -> None:
        """toggle send_messages deny for new voice channels"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "deny_messages", setting,
            )
            state = "enabled" if setting else "disabled"
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: message deny **{state}**"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="bypassed")
    @has_permissions(manage_guild=True)
    async def voicemaster_bypassed(self, ctx: Context) -> None:
        """view all users and roles who can bypass locked channels"""
        channel = ctx.author.voice.channel
        bypassed = []
        for target, overwrite in channel.overwrites.items():
            if overwrite.connect is True:
                bypassed.append(target.mention)
        if not bypassed:
            return await ctx.send(view=_vm_container(f"{ctx.author.mention}: no **bypassed** users or roles"))
        await ctx.send(view=_vm_container(f"{ctx.author.mention}:\n" + ", ".join(bypassed)))

    @voicemaster.command(name="private", slash=False)
    @has_permissions(manage_guild=True)
    @describe(setting="enable or disable")
    async def voicemaster_private(self, ctx: Context, setting: bool) -> None:
        """toggle moving locked/hidden channels into private categories"""
        try:
            await VoiceMasterSettings.update_config_field(
                self.bot.db, ctx.guild.id, "use_private", setting,
            )
            state = "enabled" if setting else "disabled"
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: private category **{state}**"))
        except Exception:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: server is **not configured**"))

    @voicemaster.command(name="invite")
    async def voicemaster_invite(self, ctx: Context) -> None:
        """create an invite link to your voice channel"""
        try:
            invite = await ctx.author.voice.channel.create_invite(
                max_age=3600, reason=f"VoiceMaster: {ctx.author} created invite",
            )
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: [click here to join]({invite.url})"))
        except discord.HTTPException:
            await ctx.send(view=_vm_container(f"{ctx.author.mention}: failed to create **invite**"))

    @voicemaster.command(name="region")
    @describe(region="voice region")
    async def voicemaster_region(self, ctx: Context, region: str) -> None:
        """set the region of your voice channel"""
        await ctx.author.voice.channel.edit(
            rtc_region=region.lower() if region.lower() != "auto" else None,
            reason=f"VoiceMaster: {ctx.author} set region",
        )
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: region set to **{region}**"))

    @voicemaster.command(name="nsfw")
    @describe(setting="enable or disable")
    async def voicemaster_nsfw(self, ctx: Context, setting: bool) -> None:
        """toggle nsfw mode for your voice channel"""
        await ctx.author.voice.channel.edit(
            nsfw=setting,
            reason=f"VoiceMaster: {ctx.author} toggled nsfw",
        )
        state = "enabled" if setting else "disabled"
        await ctx.send(view=_vm_container(f"{ctx.author.mention}: nsfw mode **{state}**"))


async def setup(bot: Vain):
    await bot.add_cog(VoiceMaster(bot))
