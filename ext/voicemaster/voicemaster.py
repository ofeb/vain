from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bleed import Bleed


import asyncio
import contextlib
from typing import Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from core.discord.package import Package, tasks

from .events import VoiceMasterEvents

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.managers.values import bot as bot_config, color, emojis
from .views import VoiceInterface
from core.managers.permissions import has_permissions


class VoiceMaster(VoiceMasterEvents, Package):
    """Voice channel management system."""

    def __init__(self, bot: Bleed):
        super().__init__(bot)
        self._cooldowns: dict = {}
        self.bot.add_view(VoiceInterface(self))

    def _interface_usage_lines(self, support_url: str) -> list[str]:
        return [
            f"{emojis.interface.lock} — [`Lock`]({support_url}) the voice channel",
            f"{emojis.interface.unlock} — [`Unlock`]({support_url}) the voice channel",
            f"{emojis.interface.ghost} — [`Ghost`]({support_url}) the voice channel",
            f"{emojis.interface.reveal} — [`Reveal`]({support_url}) the voice channel",
            f"{emojis.interface.claim} — [`Claim`]({support_url}) the voice channel",
            f"{emojis.interface.disconnect} — [`Disconnect`]({support_url}) a member",
            f"{emojis.interface.activity} — [`Start`]({support_url}) a new voice channel activity",
            f"{emojis.interface.information} — [`View`]({support_url}) channel information",
            f"{emojis.interface.increase} — [`Increase`]({support_url}) the user limit",
            f"{emojis.interface.decrease} — [`Decrease`]({support_url}) the user limit",
        ]

    def _interface_usage_blocks(self) -> list[str]:
        support_url = bot_config.support
        lines = self._interface_usage_lines(support_url)
        block = "\n".join(lines)
        if len(block) <= 1024:
            return [block]

        if support_url.startswith("https://"):
            compact_url = "http://" + support_url.removeprefix("https://")
            compact_lines = self._interface_usage_lines(compact_url)
            compact_block = "\n".join(compact_lines)
            if len(compact_block) <= 1024:
                return [compact_block]
            lines = compact_lines

        midpoint = (len(lines) + 1) // 2
        blocks = [
            "\n".join(lines[:midpoint]),
            "\n".join(lines[midpoint:]),
        ]
        return [block for block in blocks if block]

    def _interface_embed(self, guild: discord.Guild) -> discord.Embed:
        """Build the bleed-style VoiceMaster interface embed."""
        embed = discord.Embed(
            color=color.base,
            title="VoiceMaster Interface",
            description="Click the buttons below to control your voice channel",
        )
        embed.set_author(
            name=guild.name,
            icon_url=guild.icon.url if guild.icon else None,
        )
        if self.bot.user is not None:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        usage_blocks = self._interface_usage_blocks()
        embed.add_field(name="**Button Usage**", value=usage_blocks[0], inline=False)
        for block in usage_blocks[1:]:
            embed.add_field(name="\u200b", value=block, inline=False)
        return embed

    async def cog_load(self) -> None:
        """Clean up empty channels on load."""
        if getattr(self.bot.db, "pool", None) is None:
            return
        if not self._cleanup_loop.is_running():
            self._cleanup_loop.start()

    async def cog_unload(self) -> None:
        """Cleanup on unload."""
        self._cleanup_loop.cancel()

    @tasks.loop(minutes=1)
    async def _cleanup_loop(self):
        """Periodically clean up empty voice channels."""
        await self._cleanup_empty_channels()

    @_cleanup_loop.before_loop
    async def _before_cleanup_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _cleanup_empty_channels(self):
        """Delete empty voice channels from database and Discord."""
        if getattr(self.bot.db, "pool", None) is None:
            return

        to_delete = []
        
        rows = await self.bot.db.fetch(
            "SELECT channel_id FROM voicemaster_channels"
        )
        
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
            await self.bot.db.executemany(
                "DELETE FROM voicemaster_channels WHERE channel_id = $1",
                [(cid,) for cid in to_delete]
            )

    def _get_cooldown(self, key: str, rate: int, per: float) -> Optional[float]:
        """Simple cooldown implementation."""
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
        self,
        member: discord.Member,
        config,
        trigger_channel: discord.VoiceChannel,
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
            member,
            read_messages=True,
            connect=True,
            reason=f"VoiceMaster: Owner permissions for {member}",
        )

        await self.bot.db.execute(
            """INSERT INTO voicemaster_channels (guild_id, channel_id, owner_id)
               VALUES ($1, $2, $3)""",
            member.guild.id,
            channel.id,
            member.id,
        )

        if role_id := config.get("role_id"):
            role = member.guild.get_role(role_id)
            if role and role not in member.roles:
                with contextlib.suppress(discord.HTTPException):
                    await member.add_roles(role, reason="VoiceMaster: Default role")

    async def cog_check(self, ctx: Context) -> bool:
        """Check if user can use voicemaster commands."""
        admin_commands = {
            "voicemaster",
            "voicemaster setup",
            "voicemaster reset",
            "voicemaster unset",
            "voicemaster category",
            "voicemaster category private",
            "voicemaster default",
            "voicemaster default interface",
            "voicemaster default role",
            "voicemaster default bitrate",
            "voicemaster default name",
            "voicemaster default region",
        }
        
        if ctx.command.qualified_name in admin_commands:
            return True
        
        if not ctx.author.voice:
            raise commands.CommandError("You're not connected to a **voice channel**")
        
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster_channels WHERE channel_id = $1",
            ctx.author.voice.channel.id
        )
        
        if not owner_id:
            raise commands.CommandError("You're not in a **VoiceMaster** channel!")
        
        if ctx.command.qualified_name == "voicemaster claim":
            if ctx.author.id == owner_id:
                raise commands.CommandError("You already own this **voice channel**!")
            
            if owner_id in (m.id for m in ctx.author.voice.channel.members):
                raise commands.CommandError("The owner is still active in this channel!")
            
            return True
        
        if ctx.author.id != owner_id:
            raise commands.CommandError("You don't own this **voice channel**!")
        
        return True

    @hybrid(
        name="voicemaster",
        description="Make temporary voice channels in your server!",
        guild_only=True,
        invoke_without_command=True,
    )
    async def voicemaster(self, ctx: Context) -> None:
        """Main voicemaster command group."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @voicemaster.command(name="setup")
    @has_permissions(manage_guild=True)
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def voicemaster_setup(self, ctx: Context) -> None:
        """Begin VoiceMaster server configuration setup."""
        if await self.bot.db.fetchrow(
            "SELECT * FROM voicemaster_configuration WHERE guild_id = $1",
            ctx.guild.id
        ):
            return await ctx.fail(
                "Server is already configured. Use `voicemaster reset` to reset."
            )
        
        category = await ctx.guild.create_category("Voice Channels")
        interface = await category.create_text_channel("interface")
        channel = await category.create_voice_channel("Join to Create")
        
        everyone = ctx.guild.default_role
        await interface.set_permissions(
            everyone,
            send_messages=False,
            send_messages_in_threads=False,
            create_public_threads=False,
            create_private_threads=False,
        )
        
        await channel.set_permissions(
            everyone,
            connect=True,
        )
        
        await interface.send(embed=self._interface_embed(ctx.guild), view=VoiceInterface(self))
        
        await self.bot.db.execute(
            """INSERT INTO voicemaster_configuration 
               (guild_id, category_id, interface_id, channel_id) 
               VALUES ($1, $2, $3, $4)""",
            ctx.guild.id, category.id, interface.id, channel.id
        )
        
        await ctx.success("VoiceMaster setup complete!")

    @voicemaster.command(name="reset")
    @has_permissions(manage_guild=True)
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def voicemaster_reset(self, ctx: Context) -> None:
        """Reset server configuration for VoiceMaster."""
        row = await self.bot.db.fetchrow(
            "DELETE FROM voicemaster_configuration WHERE guild_id = $1 RETURNING category_id, interface_id, channel_id",
            ctx.guild.id
        )
        
        if row:
            for channel_id in row:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    try:
                        await channel.delete()
                    except discord.HTTPException:
                        pass
            await ctx.success("VoiceMaster configuration reset")
        else:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="unset", aliases=["remove"])
    @has_permissions(manage_guild=True)
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def voicemaster_unset(self, ctx: Context) -> None:
        """Remove VoiceMaster configuration without deleting channels."""
        row = await self.bot.db.fetchrow(
            "DELETE FROM voicemaster_configuration WHERE guild_id = $1 RETURNING category_id",
            ctx.guild.id
        )
        if row:
            await ctx.success("VoiceMaster configuration removed. Channels were kept.")
        else:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="category")
    @has_permissions(manage_guild=True)
    @describe(channel="Voice channel category")
    async def voicemaster_category(self, ctx: Context, channel: discord.CategoryChannel) -> None:
        """Redirect voice channels to custom category."""
        try:
            await self.bot.db.execute(
                "UPDATE voicemaster_configuration SET category_id = $2 WHERE guild_id = $1",
                ctx.guild.id, channel.id
            )
            await ctx.success(f"Set {channel.name} as the voice category")
        except Exception:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="category private", slash=False)
    @has_permissions(manage_guild=True)
    @describe(channel="Private voice channel category")
    async def voicemaster_category_private(self, ctx: Context, channel: discord.CategoryChannel) -> None:
        """Set the private category for VoiceMaster channels."""
        try:
            await self.bot.db.execute(
                "UPDATE voicemaster_configuration SET private_category_id = $2 WHERE guild_id = $1",
                ctx.guild.id, channel.id
            )
            await ctx.success(f"Set {channel.name} as the private category")
        except Exception:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="default")
    async def voicemaster_default(self, ctx: Context) -> None:
        """View default VoiceMaster settings."""
        config = await self.bot.db.fetchrow(
            "SELECT * FROM voicemaster_configuration WHERE guild_id = $1",
            ctx.guild.id
        )
        
        if not config:
            return await ctx.fail("Server is not configured")
        
        embed = discord.Embed(title="VoiceMaster Defaults", color=color.base)
        embed.add_field(name="Bitrate", value=f"{config.get('bitrate', 64000) // 1000}kbps", inline=True)
        embed.add_field(name="Region", value=config.get('region', 'auto'), inline=True)
        embed.add_field(name="Default Role", value=f"<@{config.get('role_id', 0)}>", inline=True)
        await ctx.send(embed=embed)

    @voicemaster.command(name="default interface", slash=False)
    @describe(setting="Enable or disable interface")
    async def voicemaster_default_interface(self, ctx: Context, setting: bool) -> None:
        """Send interface to new Voice Channels."""
        try:
            await self.bot.db.execute(
                "UPDATE voicemaster_configuration SET send_interface = $2 WHERE guild_id = $1",
                ctx.guild.id, setting
            )
            await ctx.success(f"Interface sending {'enabled' if setting else 'disabled'}")
        except Exception:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="default role", slash=False)
    @has_permissions(manage_guild=True, manage_roles=True)
    @describe(role="Default role for voice channels")
    async def voicemaster_default_role(self, ctx: Context, role: discord.Role) -> None:
        """Set the default role for VoiceMaster."""
        try:
            await self.bot.db.execute(
                "UPDATE voicemaster_configuration SET role_id = $2 WHERE guild_id = $1",
                ctx.guild.id, role.id
            )
            await ctx.success(f"Set {role.mention} as default role")
        except Exception:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="default bitrate", slash=False)
    @has_permissions(manage_guild=True)
    @describe(bitrate="Default bitrate in kbps")
    async def voicemaster_default_bitrate(self, ctx: Context, bitrate: int) -> None:
        """Edit default bitrate for new Voice Channels."""
        try:
            await self.bot.db.execute(
                "UPDATE voicemaster_configuration SET bitrate = $2 WHERE guild_id = $1",
                ctx.guild.id, bitrate * 1000
            )
            await ctx.success(f"Set default bitrate to {bitrate}kbps")
        except Exception:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="default name", slash=False)
    @has_permissions(manage_guild=True)
    @describe(name="Default name for new channels")
    async def voicemaster_default_name(self, ctx: Context, name: str) -> None:
        """Set default name for new Voice Channels."""
        try:
            await self.bot.db.execute(
                "UPDATE voicemaster_configuration SET default_name = $2 WHERE guild_id = $1",
                ctx.guild.id, name
            )
            await ctx.success(f"Set default name to {name}")
        except Exception:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="default region", slash=False)
    @has_permissions(manage_guild=True)
    @describe(region="Voice region")
    async def voicemaster_default_region(self, ctx: Context, region: str) -> None:
        """Edit default region for new Voice Channels."""
        try:
            await self.bot.db.execute(
                "UPDATE voicemaster_configuration SET region = $2 WHERE guild_id = $1",
                ctx.guild.id, region.lower()
            )
            await ctx.success(f"Set default region to {region}")
        except Exception:
            await ctx.fail("Server is not configured")

    @voicemaster.command(name="configuration")
    async def voicemaster_configuration(self, ctx: Context) -> None:
        """See current configuration for current voice channel."""
        channel = ctx.author.voice.channel
        
        embed = discord.Embed(title=channel.name, color=color.base)
        embed.add_field(name="Owner", value=f"<@{ctx.author.id}>", inline=True)
        embed.add_field(name="Locked", value="Yes" if not channel.permissions_for(ctx.guild.default_role).connect else "No", inline=True)
        embed.add_field(name="Members", value=f"{len(channel.members)}", inline=True)
        embed.add_field(name="Bitrate", value=f"{channel.bitrate // 1000}kbps", inline=True)
        embed.add_field(name="User Limit", value=channel.user_limit or "Unlimited", inline=True)
        
        await ctx.send(embed=embed)

    @voicemaster.command(name="lock")
    async def voicemaster_lock(self, ctx: Context) -> None:
        """Lock your voice channel."""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role,
            connect=False,
            reason=f"VoiceMaster: {ctx.author} locked channel"
        )
        await ctx.success("Voice channel locked")

    @voicemaster.command(name="unlock")
    async def voicemaster_unlock(self, ctx: Context) -> None:
        """Unlock your voice channel."""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role,
            connect=None,
            reason=f"VoiceMaster: {ctx.author} unlocked channel"
        )
        await ctx.success("Voice channel unlocked")

    @voicemaster.command(name="ghost")
    async def voicemaster_ghost(self, ctx: Context) -> None:
        """Hide your voice channel."""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role,
            view_channel=False,
            reason=f"VoiceMaster: {ctx.author} hid channel"
        )
        await ctx.success("Voice channel hidden")

    @voicemaster.command(name="unghost")
    async def voicemaster_unghost(self, ctx: Context) -> None:
        """Unhide your voice channel."""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role,
            view_channel=None,
            reason=f"VoiceMaster: {ctx.author} revealed channel"
        )
        await ctx.success("Voice channel revealed")

    @voicemaster.command(name="claim")
    async def voicemaster_claim(self, ctx: Context) -> None:
        """Claim an inactive voice channel."""
        await self.bot.db.execute(
            "UPDATE voicemaster_channels SET owner_id = $2 WHERE channel_id = $1",
            ctx.author.voice.channel.id, ctx.author.id
        )
        
        if ctx.author.voice.channel.name.endswith("channel"):
            try:
                await ctx.author.voice.channel.edit(name=f"{ctx.author.display_name}'s channel")
            except discord.HTTPException:
                pass
        
        await ctx.success("You now own this channel!")

    @voicemaster.command(name="transfer")
    @describe(member="Member to transfer ownership to")
    async def voicemaster_transfer(self, ctx: Context, member: discord.Member) -> None:
        """Transfer ownership of your channel to another member."""
        if member == ctx.author or member.bot:
            return await ctx.fail("Invalid member")
        
        if not member.voice or member.voice.channel != ctx.author.voice.channel:
            return await ctx.fail(f"{member} is not in your channel")
        
        await self.bot.db.execute(
            "UPDATE voicemaster_channels SET owner_id = $2 WHERE channel_id = $1",
            ctx.author.voice.channel.id, member.id
        )
        
        if ctx.author.voice.channel.name.endswith("channel"):
            try:
                await ctx.author.voice.channel.edit(name=f"{member.display_name}'s channel")
            except discord.HTTPException:
                pass
        
        await ctx.success(f"Transferred ownership to {member.mention}")

    @voicemaster.command(name="name")
    @describe(name="New channel name")
    async def voicemaster_name(self, ctx: Context, name: str) -> None:
        """Rename your voice channel."""
        if len(name) > 100:
            return await ctx.fail("Name too long (max 100 characters)")
        
        try:
            await ctx.author.voice.channel.edit(
                name=name,
                reason=f"VoiceMaster: {ctx.author} renamed channel"
            )
            await ctx.success(f"Renamed to {name}")
        except discord.HTTPException:
            await ctx.fail("Failed to rename channel")

    @voicemaster.command(name="limit")
    @describe(limit="User limit (0-99)")
    async def voicemaster_limit(self, ctx: Context, limit: int) -> None:
        """Set a member limit to your voice channel."""
        if limit < 0 or limit > 99:
            return await ctx.fail("Limit must be between 0 and 99")
        
        await ctx.author.voice.channel.edit(
            user_limit=limit,
            reason=f"VoiceMaster: {ctx.author} set limit"
        )
        await ctx.success(f"Set limit to {limit}")

    @voicemaster.command(name="role")
    @describe(role="Role to grant on join")
    async def voicemaster_role(self, ctx: Context, role: discord.Role) -> None:
        """Grant roles to members who join and remove from members leaving."""
        await self.bot.db.execute(
            "UPDATE voicemaster_channels SET role_id = $2 WHERE channel_id = $1",
            ctx.author.voice.channel.id, role.id
        )
        await ctx.success(f"Set {role.mention} as join role")

    @voicemaster.command(name="bitrate")
    @describe(bitrate="Bitrate in kbps")
    async def voicemaster_bitrate(self, ctx: Context, bitrate: int) -> None:
        """Edit bitrate of your voice channel."""
        await ctx.author.voice.channel.edit(
            bitrate=bitrate * 1000,
            reason=f"VoiceMaster: {ctx.author} set bitrate"
        )
        await ctx.success(f"Set bitrate to {bitrate}kbps")

    @voicemaster.command(name="music")
    @describe(setting="Enable or disable music mode")
    async def voicemaster_music(self, ctx: Context, setting: bool) -> None:
        """Change your channel to a Music Only channel."""
        await self.bot.db.execute(
            "UPDATE voicemaster_channels SET music_mode = $2 WHERE channel_id = $1",
            ctx.author.voice.channel.id, setting
        )
        await ctx.success(f"Music mode {'enabled' if setting else 'disabled'}")

    @voicemaster.command(name="sendinterface")
    async def voicemaster_sendinterface(self, ctx: Context) -> None:
        """Forcefully resend VoiceMaster interface."""
        config = await self.bot.db.fetchrow(
            "SELECT interface_id FROM voicemaster_configuration WHERE guild_id = $1",
            ctx.guild.id
        )
        
        if not config:
            return await ctx.fail("Server not configured")
        
        interface = ctx.guild.get_channel(config["interface_id"])
        if not interface:
            return await ctx.fail("Interface channel not found")
        
        await interface.send(embed=self._interface_embed(ctx.guild), view=VoiceInterface(self))
        await ctx.success("Interface resent")

    @voicemaster.command(name="status")
    @describe(status="Channel status message")
    async def voicemaster_status(self, ctx: Context, status: str) -> None:
        """Set a status for your voice channel."""
        await self.bot.db.execute(
            "UPDATE voicemaster_channels SET status = $2 WHERE channel_id = $1",
            ctx.author.voice.channel.id, status
        )
        await ctx.success(f"Set status to {status}")

    @voicemaster.command(name="join")
    async def voicemaster_join(self, ctx: Context) -> None:
        """Join a voice channel."""
        if not ctx.author.voice:
            return await ctx.fail("You're not in a voice channel")
        
        await ctx.success(f"You're in {ctx.author.voice.channel.name}")

    @voicemaster.command(name="join role", slash=False)
    @describe(role="Role to grant on join")
    async def voicemaster_join_role(self, ctx: Context, role: discord.Role) -> None:
        """Set role to grant on voice join."""
        await self.bot.db.execute(
            "UPDATE voicemaster_configuration SET join_role_id = $2 WHERE guild_id = $1",
            ctx.guild.id, role.id
        )
        await ctx.success(f"Set {role.mention} as join role")

    @voicemaster.command(name="permit")
    @describe(target="Member or role to permit")
    async def voicemaster_permit(self, ctx: Context, target: Union[discord.Member, discord.Role]) -> None:
        """Permit a member or role to join your VC."""
        await ctx.author.voice.channel.set_permissions(
            target,
            connect=True,
            view_channel=True,
            reason=f"VoiceMaster: {ctx.author} permitted {target}"
        )
        await ctx.success(f"Permitted {target.mention}")

    @voicemaster.command(name="reject")
    @describe(target="Member or role to reject")
    async def voicemaster_reject(self, ctx: Context, target: Union[discord.Member, discord.Role]) -> None:
        """Reject a member or role from joining your VC."""
        await ctx.author.voice.channel.set_permissions(
            target,
            connect=False,
            reason=f"VoiceMaster: {ctx.author} rejected {target}"
        )
        
        if isinstance(target, discord.Member):
            if target.voice and target.voice.channel == ctx.author.voice.channel:
                try:
                    await target.move_to(None)
                except discord.HTTPException:
                    pass
        
        await ctx.success(f"Rejected {target.mention}")
    pass
async def setup(bot: Bleed):
    await bot.add_cog(VoiceMaster(bot))
