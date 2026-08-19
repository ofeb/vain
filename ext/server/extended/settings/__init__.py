from __future__ import annotations

from asyncio import ensure_future
from typing import Optional, Union

import discord
from discord import Embed, Guild, Role, TextChannel, Thread
from discord.ext.commands import CommandError, Converter, group

from core.discord.package import Package
from core.tools.convert import ChannelConvert, RoleConvert

from core.managers.permissions import has_permissions
CLEAR_WORDS = {"clear", "none", "off", "remove", "reset"}


def parse_toggle(value: str) -> bool | None:
    """parse common on/off style inputs"""
    normalized = value.lower().strip()
    if normalized in {"enable", "enabled", "yes", "on", "true"}:
        return True
    if normalized in {"disable", "disabled", "no", "off", "false"}:
        return False
    return None


class RoleOrClear(Converter):
    """role converter that accepts clear words"""

    async def convert(self, ctx, argument: str):
        if argument.lower().strip() in CLEAR_WORDS:
            return None
        return await RoleConvert().convert(ctx, argument)


class ChannelOrClear(Converter):
    """text channel converter that accepts clear words"""

    async def convert(self, ctx, argument: str):
        if argument.lower().strip() in CLEAR_WORDS:
            return None
        channel = await ChannelConvert().convert(ctx, argument)
        if not isinstance(channel, (TextChannel, Thread)):
            raise CommandError(f"**{channel}** is not a text channel")
        return channel


class SettingsCommands(Package):
    """server settings and tracker commands"""

    async def _resolve_staff_roles(self, ctx, raw: str) -> list[Role]:
        roles: list[Role] = []
        converter = RoleConvert()
        for chunk in [part.strip() for part in raw.split(",") if part.strip()]:
            roles.append(await converter.convert(ctx, chunk))
        return roles

    def _format_channel(self, guild: Guild, channel_id: int | None) -> str:
        if not channel_id:
            return "n/a"
        channel = guild.get_channel(int(channel_id))
        if channel:
            return channel.mention
        return f"<#{channel_id}>"

    def _format_role(self, guild: Guild, role_id: int | None) -> str:
        if not role_id:
            return "n/a"
        role = guild.get_role(int(role_id))
        if role:
            return role.mention
        return f"<@&{role_id}>"

    @group(
        name="settings",
        usage="(subcommand) <args>",
        example="jail #jail",
        aliases=["bind"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def settings(self, ctx):
        """Server configuration."""
        return await ctx.send_help()

    @settings.command(name="modlog", aliases=["jaillog"])
    @has_permissions(manage_guild=True)
    async def settings_modlog(self, ctx, channel: TextChannel = None):
        """Set the mod log channel."""
        target = channel or (ctx.channel if isinstance(ctx.channel, TextChannel) else None)
        if target is None:
            return await ctx.send_help(ctx.command)
        await self.db.set_modlog_channel(ctx.guild.id, target.id)
        return await ctx.success(
            f"Successfully **updated** the mod log channel to {target.mention}"
        )

    @settings.command(
        name="googlesafetylevel",
        aliases=["googlesafety", "safetylevel", "gs"],
    )
    @has_permissions(manage_guild=True)
    async def settings_google_safety_level(self, ctx, setting: str):
        """Enable or disable Google safety level."""
        toggle = parse_toggle(setting)
        if toggle is None:
            return await ctx.warn("Invalid setting. Use **yes** or **no**.")
        await self.db.set_server_settings(ctx.guild.id, google_safety_level=toggle)
        status = "enabled" if toggle else "disabled"
        return await ctx.success(
            f"Successfully **set** Google safety to **{status}**"
        )

    @settings.group(name="staff", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def settings_staff(self, ctx, *, roles: str = None):
        """Toggle one or more configured staff roles."""
        if not roles:
            return await ctx.send_help(ctx.command)
        resolved = await self._resolve_staff_roles(ctx, roles)
        if not resolved:
            return await ctx.warn("You need to provide at least one **role**.")

        lines: list[str] = []
        for role in resolved:
            added = await self.db.toggle_staff_role(ctx.guild.id, role.id)
            action = "added" if added else "removed"
            lines.append(f"**{action}** {role.mention}")
        return await ctx.success("\n".join(lines))

    @settings_staff.command(name="list")
    @has_permissions(manage_guild=True)
    async def settings_staff_list(self, ctx):
        """View all configured staff roles."""
        role_ids = await self.db.list_staff_roles(ctx.guild.id)
        if not role_ids:
            return await ctx.warn("No **staff roles** are set.")
        lines = [
            f"`{index:02d}` {self._format_role(ctx.guild, role_id)}"
            for index, role_id in enumerate(role_ids, start=1)
        ]
        return await ctx.paginate(
            Embed(title="Staff Roles", color=self.color),
            lines,
        )

    @settings.command(
        name="jail",
        description="set the jail channel (defaults to current channel)",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def settings_jail(self, ctx, channel: TextChannel = None):
        """Set the jail channel."""
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        await self.db.set_server_settings(ctx.guild.id, jail_channel_id=channel.id)
        return await ctx.success(
            f"Successfully **set** the jail channel to {channel.mention}"
        )

    @settings.command(name="jailrole", aliases=["jailed", "jailedrole"])
    @has_permissions(manage_guild=True)
    async def settings_jailrole(self, ctx, role: RoleOrClear):
        """Set the jail role."""
        await self.db.set_server_settings(
            ctx.guild.id,
            jail_role_id=(role.id if role else None),
        )
        if role is None:
            return await ctx.success("Successfully **cleared** the jail role")
        return await ctx.success(
            f"Successfully **set** the jail role to {role.mention}"
        )

    @settings.command(name="muted", aliases=["textmute", "mute"])
    @has_permissions(manage_guild=True)
    async def settings_muted(self, ctx, role: RoleOrClear):
        """Set the muted role."""
        await self.db.set_server_settings(
            ctx.guild.id,
            muted_role_id=(role.id if role else None),
        )
        if role is None:
            return await ctx.success("Successfully **cleared** the muted role")
        return await ctx.success(
            f"Successfully **set** the muted role to {role.mention}"
        )

    @settings.command(name="imuted", aliases=["imute"])
    @has_permissions(manage_guild=True)
    async def settings_imuted(self, ctx, role: RoleOrClear):
        """Set the image muted role."""
        await self.db.set_server_settings(
            ctx.guild.id,
            imuted_role_id=(role.id if role else None),
        )
        if role is None:
            return await ctx.success("Successfully **cleared** the image muted role")
        return await ctx.success(
            f"Successfully **set** the image muted role to {role.mention}"
        )

    @settings.command(name="rmuted", aliases=["rmute"])
    @has_permissions(manage_guild=True)
    async def settings_rmuted(self, ctx, role: RoleOrClear):
        """Set the reaction muted role."""
        await self.db.set_server_settings(
            ctx.guild.id,
            rmuted_role_id=(role.id if role else None),
        )
        if role is None:
            return await ctx.success("Successfully **cleared** the reaction muted role")
        return await ctx.success(
            f"Successfully **set** the reaction muted role to {role.mention}"
        )

    @settings.command(name="autonick")
    @has_permissions(manage_guild=True)
    async def settings_autonick(self, ctx, *, nickname: str):
        """Set or clear autonick."""
        value = nickname.strip()
        if value.lower() in CLEAR_WORDS:
            value = ""
        await self.db.set_server_settings(
            ctx.guild.id,
            autonick=(value or None),
        )
        if value:
            return await ctx.success(f"Successfully **set** autonick to **{value}**")
        return await ctx.success("Successfully **cleared** autonick")

    @settings.command(name="dj")
    @has_permissions(manage_guild=True)
    async def settings_dj(self, ctx, role: RoleOrClear):
        """Set the DJ role."""
        await self.db.set_server_settings(
            ctx.guild.id,
            dj_role_id=(role.id if role else None),
        )
        if role is None:
            return await ctx.success("Successfully **cleared** the DJ role")
        return await ctx.success(
            f"Successfully **set** the DJ role to {role.mention}"
        )

    @settings.command(name="premiumrole", aliases=["premiumid", "pr"])
    @has_permissions(manage_guild=True)
    async def settings_premiumrole(self, ctx, role: RoleOrClear):
        """Set the premium role."""
        await self.db.set_server_settings(
            ctx.guild.id,
            premium_role_id=(role.id if role else None),
        )
        if role is None:
            return await ctx.success("Successfully **cleared** the premium role")
        return await ctx.success(
            f"Successfully **set** the premium role to {role.mention}"
        )

    @settings.command(name="joinlogs", aliases=["joinlog", "jl"])
    @has_permissions(manage_guild=True)
    async def settings_joinlogs(self, ctx, channel: TextChannel = None):
        """Set the join and leave log channel."""
        target = channel or (ctx.channel if isinstance(ctx.channel, TextChannel) else None)
        if target is None:
            return await ctx.send_help(ctx.command)
        await self.db.set_server_settings(ctx.guild.id, joinlog_channel_id=target.id)
        return await ctx.success(
            f"Successfully **set** the join log channel to {target.mention}"
        )

    @settings.command(name="baserole", aliases=["baseid"])
    @has_permissions(manage_guild=True)
    async def settings_baserole(self, ctx, role: RoleOrClear):
        """Set the base role."""
        await self.db.set_server_settings(
            ctx.guild.id,
            member_base_role_id=(role.id if role else None),
        )
        if role is None:
            return await ctx.success("Successfully **cleared** the base role")
        return await ctx.success(
            f"Successfully **set** the base role to {role.mention}"
        )

    @settings.command(name="jailmsg", aliases=["jailmessage"])
    @has_permissions(manage_guild=True)
    async def settings_jailmsg(self, ctx, *, message: str):
        """Set the jail message."""
        value = message.strip()
        if value.lower() in CLEAR_WORDS:
            value = ""
        await self.db.set_server_settings(
            ctx.guild.id,
            jail_message=(value or None),
        )
        if value:
            return await ctx.success("Successfully **updated** the jail message")
        return await ctx.success("Successfully **cleared** the jail message")

    @settings.command(name="jailroles")
    @has_permissions(manage_guild=True)
    async def settings_jailroles(self, ctx, setting: str):
        """Enable or disable jail role removal."""
        toggle = parse_toggle(setting)
        if toggle is None:
            return await ctx.warn("Invalid setting. Use **yes** or **no**.")
        await self.db.set_server_settings(ctx.guild.id, jail_remove_roles=toggle)
        status = "enabled" if toggle else "disabled"
        return await ctx.success(
            f"Successfully **set** jail role removal to **{status}**"
        )

    @settings.command(name="disablecustomfms", aliases=["disablefms"])
    @has_permissions(manage_channels=True)
    async def settings_disablecustomfms(self, ctx, setting: str):
        """Enable or disable custom now playing commands."""
        toggle = parse_toggle(setting)
        if toggle is None:
            return await ctx.warn("Invalid setting. Use **yes** or **no**.")
        await self.db.set_server_settings(ctx.guild.id, disable_custom_fms=toggle)
        status = "disabled" if toggle else "enabled"
        return await ctx.success(
            f"Successfully **set** custom now playing commands to **{status}**"
        )

    @settings.command(name="autoplay")
    @has_permissions(manage_guild=True)
    async def settings_autoplay(self, ctx, setting: str):
        """Enable or disable autoplay."""
        toggle = parse_toggle(setting)
        if toggle is None:
            return await ctx.warn("Invalid setting. Use **yes** or **no**.")
        await self.db.set_server_settings(
            ctx.guild.id,
            autoplay=("on" if toggle else None),
        )
        status = "enabled" if toggle else "disabled"
        return await ctx.success(f"Successfully **{status}** autoplay")

    @settings.command(name="reset", aliases=["clear"])
    @has_permissions(administrator=True)
    async def settings_reset(self, ctx):
        """Reset server data. This can't be undone."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Reset **all** server data for this guild? "
            "This action **can't be undone**."
        )
        if not ok:
            return await ctx.warn("Server data reset **cancelled**")
        await self.db.purge_guild_data(ctx.guild.id)
        return await ctx.success(
            "Successfully **reset** server data. This action can't be undone."
        )

    @settings.command(name="resetcases")
    @has_permissions(administrator=True)
    async def settings_resetcases(self, ctx):
        """Reset modlog cases. This can't be undone."""
        from core.discord.views.confirm import ConfirmView

        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Reset **all** modlog cases for this server? "
            "This action **can't be undone**."
        )
        if not ok:
            return await ctx.warn("Cases reset **cancelled**")
        await self.db.reset_modlog_cases(ctx.guild.id)
        return await ctx.success(
            "Successfully **reset** server cases. This action can't be undone."
        )

    @settings.command(name="config", aliases=["list", "configuration"])
    @has_permissions(manage_guild=True)
    async def settings_config(self, ctx):
        """View current server settings."""
        settings = await self.db.get_server_settings(ctx.guild.id)
        modlog_id = await self.db.get_modlog_channel(ctx.guild.id)
        booster_base_id = await self.db.fetchval(
            "SELECT base_id FROM booster_roles WHERE guild_id = $1",
            ctx.guild.id,
        )

        embed = Embed(title="settings", color=self.color)
        embed.add_field(
            name="Mod Log",
            value=self._format_channel(ctx.guild, modlog_id),
            inline=True,
        )
        embed.add_field(
            name="Jail Channel",
            value=self._format_channel(
                ctx.guild,
                settings.jail_channel_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="Jail Role",
            value=self._format_role(
                ctx.guild,
                settings.jail_role_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="Join Logs",
            value=self._format_channel(
                ctx.guild,
                settings.joinlog_channel_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="Base Role",
            value=self._format_role(
                ctx.guild,
                settings.member_base_role_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="Muted Role",
            value=self._format_role(
                ctx.guild,
                settings.muted_role_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="Image Muted Role",
            value=self._format_role(
                ctx.guild,
                settings.imuted_role_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="Reaction Muted Role",
            value=self._format_role(
                ctx.guild,
                settings.rmuted_role_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="DJ Role",
            value=self._format_role(
                ctx.guild,
                settings.dj_role_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="Premium Role",
            value=self._format_role(
                ctx.guild,
                settings.premium_role_id if settings else None,
            ),
            inline=True,
        )
        embed.add_field(
            name="Booster Base Role",
            value=self._format_role(ctx.guild, booster_base_id),
            inline=True,
        )
        jail_roles = "enabled"
        if settings and settings.jail_remove_roles is False:
            jail_roles = "disabled"
        embed.add_field(name="Jail Roles", value=jail_roles, inline=True)
        google = "enabled" if settings and settings.google_safety_level else "disabled"
        embed.add_field(name="Google Safety", value=google, inline=True)
        custom_fm = "disabled" if settings and settings.disable_custom_fms else "enabled"
        embed.add_field(name="Custom FM", value=custom_fm, inline=True)
        autoplay = "enabled" if settings and settings.autoplay else "disabled"
        embed.add_field(name="Autoplay", value=autoplay, inline=True)
        embed.add_field(
            name="Autonick",
            value=(settings.autonick if settings and settings.autonick else "n/a"),
            inline=True,
        )
        embed.add_field(
            name="Jail Message",
            value=(settings.jail_message if settings and settings.jail_message else "n/a"),
            inline=False,
        )
        return await ctx.send(embed=embed)

    @group(
        name="tracker",
        aliases=["trackers"],
        description="track username or vanity availability",
        invoke_without_command=True,
    )
    async def tracker(self, ctx):
        """tracker help"""
        return await ctx.send_help(ctx.command)

    @tracker.group(
        name="username",
        aliases=["names", "users", "usernames"],
        description="track available usernames",
        example=",tracker username add #names",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def tracker_username(self, ctx):
        """username tracker subgroup"""
        return await ctx.send_help(ctx.command)

    @tracker_username.command(
        name="add",
        aliases=["create", "set", "c", "a", "s"],
        description="add a channel for username alerts (defaults to current channel)",
        example=",tracker username add #names",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def tracker_username_add(
        self, ctx, channel: Optional[Union[TextChannel, Thread]] = None
    ):
        """add username tracker channel"""
        channel = channel or (
            ctx.channel
            if isinstance(ctx.channel, (TextChannel, Thread))
            else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        ids = (
            await self.db.fetchval(
                """SELECT channel_ids FROM trackers WHERE tracker_type = $1 AND guild_id = $2""",
                "username", ctx.guild.id,
            ) or []
        )
        if len(ids) >= 2:
            raise CommandError("max of **2** tracker channels per type")
        if channel.id in ids:
            raise CommandError(f"{channel.mention} is already a username tracker")
        ids.append(channel.id)
        await self.db.execute(
            """INSERT INTO trackers (guild_id, tracker_type, channel_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, tracker_type) DO UPDATE SET channel_ids = excluded.channel_ids""",
            ctx.guild.id, "username", ids,
        )
        return await ctx.success(f"added {channel.mention} as a **username tracker**")

    @tracker_username.command(
        name="remove",
        aliases=["delete", "del", "d", "r"],
        description="remove a username tracker channel (defaults to current channel)",
        example=",tracker username remove #names",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def tracker_username_remove(
        self, ctx, channel: Optional[Union[TextChannel, Thread]] = None
    ):
        """remove username tracker"""
        channel = channel or (
            ctx.channel
            if isinstance(ctx.channel, (TextChannel, Thread))
            else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        ids = await self.db.fetchval(
            """SELECT channel_ids FROM trackers WHERE tracker_type = $1 AND guild_id = $2""",
            "username", ctx.guild.id,
        )
        if not ids:
            raise CommandError("no username trackers set")
        if channel.id not in ids:
            raise CommandError(f"no tracker in {channel.mention}")
        ids.remove(channel.id)
        if ids:
            await self.db.execute(
                """INSERT INTO trackers (guild_id, tracker_type, channel_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, tracker_type) DO UPDATE SET channel_ids = excluded.channel_ids""",
                ctx.guild.id, "username", ids,
            )
        else:
            await self.db.execute(
                """DELETE FROM trackers WHERE guild_id = $1 AND tracker_type = $2""",
                ctx.guild.id, "username",
            )
        return await ctx.success(f"removed {channel.mention} as a **username tracker**")

    @tracker.group(
        name="vanity",
        aliases=["vanitys"],
        description="track available vanity urls",
        example=",tracker vanity add #vanities",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def tracker_vanity(self, ctx):
        """vanity tracker subgroup"""
        return await ctx.send_help(ctx.command)

    @tracker_vanity.command(
        name="add",
        aliases=["create", "set", "c", "a", "s"],
        description="add a channel for vanity alerts (defaults to current channel)",
        example=",tracker vanity add #vanities",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def tracker_vanity_add(
        self, ctx, channel: Optional[Union[TextChannel, Thread]] = None
    ):
        """add vanity tracker channel"""
        channel = channel or (
            ctx.channel
            if isinstance(ctx.channel, (TextChannel, Thread))
            else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        ids = (
            await self.db.fetchval(
                """SELECT channel_ids FROM trackers WHERE tracker_type = $1 AND guild_id = $2""",
                "vanity", ctx.guild.id,
            ) or []
        )
        if len(ids) >= 2:
            raise CommandError("max of **2** tracker channels per type")
        if channel.id in ids:
            raise CommandError(f"{channel.mention} is already a vanity tracker")
        ids.append(channel.id)
        await self.db.execute(
            """INSERT INTO trackers (guild_id, tracker_type, channel_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, tracker_type) DO UPDATE SET channel_ids = excluded.channel_ids""",
            ctx.guild.id, "vanity", ids,
        )
        return await ctx.success(f"added {channel.mention} as a **vanity tracker**")

    @tracker_vanity.command(
        name="remove",
        aliases=["delete", "del", "d", "r"],
        description="remove a vanity tracker channel (defaults to current channel)",
        example=",tracker vanity remove #vanities",
        usage="[channel]",
    )
    @has_permissions(manage_guild=True)
    async def tracker_vanity_remove(
        self, ctx, channel: Optional[Union[TextChannel, Thread]] = None
    ):
        """remove vanity tracker"""
        channel = channel or (
            ctx.channel
            if isinstance(ctx.channel, (TextChannel, Thread))
            else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        ids = await self.db.fetchval(
            """SELECT channel_ids FROM trackers WHERE tracker_type = $1 AND guild_id = $2""",
            "vanity", ctx.guild.id,
        )
        if not ids:
            raise CommandError("no vanity trackers set")
        if channel.id not in ids:
            raise CommandError(f"no tracker in {channel.mention}")
        ids.remove(channel.id)
        if ids:
            await self.db.execute(
                """INSERT INTO trackers (guild_id, tracker_type, channel_ids) VALUES($1, $2, $3) ON CONFLICT(guild_id, tracker_type) DO UPDATE SET channel_ids = excluded.channel_ids""",
                ctx.guild.id, "vanity", ids,
            )
        else:
            await self.db.execute(
                """DELETE FROM trackers WHERE guild_id = $1 AND tracker_type = $2""",
                ctx.guild.id, "vanity",
            )
        return await ctx.success(f"removed {channel.mention} as a **vanity tracker**")

    @tracker.command(
        name="settings",
        aliases=["config", "show", "view", "ls"],
        description="show all tracker configuration",
    )
    @has_permissions(manage_guild=True)
    async def tracker_settings(self, ctx):
        """view tracker config"""
        rows = await self.db.fetch(
            """SELECT tracker_type, channel_ids FROM trackers WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not rows:
            raise CommandError("no trackers configured")

        def channel_list(ids):
            entries = []
            for cid in ids:
                ch = ctx.guild.get_channel(cid)
                entries.append(ch.mention if ch else f"unknown (`{cid}`)")
            return "\n".join(f"`{i}` {e}" for i, e in enumerate(entries, start=1))

        username_val = None
        vanity_val = None
        for row in rows:
            if row.tracker_type == "username":
                username_val = channel_list(row.channel_ids)
            elif row.tracker_type == "vanity":
                vanity_val = channel_list(row.channel_ids)

        embed = Embed(title="Tracker Settings")
        embed.add_field(name="Username", value=username_val or "N/A", inline=False)
        embed.add_field(name="Vanity", value=vanity_val or "N/A", inline=False)
        return await ctx.send(embed=embed)

    async def on_vanity_change(self, vanity: str):
        """notify on vanity available"""

        async def notify(guild: Guild, vanity: str, ids: list):
            for cid in ids:
                ch = guild.get_channel(cid)
                if ch:
                    await ch.send(f"**/{vanity}** is now available")

        trackers = await self.bot.db.fetch(
            """SELECT guild_id, channel_ids FROM trackers WHERE tracker_type = $1""",
            "vanity",
        )
        if not trackers:
            return
        for tracker in trackers:
            guild = self.bot.get_guild(tracker.guild_id)
            if not guild or not tracker.channel_ids:
                continue
            ensure_future(notify(guild, vanity, tracker.channel_ids))

    async def on_username_change(self, username: str):
        """notify on username available"""

        async def notify(guild: Guild, username: str, ids: list):
            for cid in ids:
                ch = guild.get_channel(cid)
                if ch:
                    await ch.send(f"**{username}** is now available")

        trackers = await self.bot.db.fetch(
            """SELECT guild_id, channel_ids FROM trackers WHERE tracker_type = $1""",
            "username",
        )
        if not trackers:
            return
        for tracker in trackers:
            guild = self.bot.get_guild(tracker.guild_id)
            if not guild or not tracker.channel_ids:
                continue
            ensure_future(notify(guild, username, tracker.channel_ids))

