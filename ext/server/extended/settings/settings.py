from typing import Union
from discord.ext.commands import group, has_permissions, CommandError
from discord import Embed, TextChannel, Thread, Guild
from asyncio import ensure_future
from core.discord.package import Package


class SettingsCommands(Package):
    """tracker settings and username/vanity tracking"""

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
        description="add a channel for username alerts",
        example=",tracker username add #names",
    )
    @has_permissions(manage_guild=True)
    async def tracker_username_add(self, ctx, *, channel: Union[TextChannel, Thread]):
        """add username tracker channel"""
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
        description="remove a username tracker channel",
        example=",tracker username remove #names",
    )
    @has_permissions(manage_guild=True)
    async def tracker_username_remove(self, ctx, *, channel: Union[TextChannel, Thread]):
        """remove username tracker"""
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
        description="track available vanity URLs",
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
        description="add a channel for vanity alerts",
        example=",tracker vanity add #vanities",
    )
    @has_permissions(manage_guild=True)
    async def tracker_vanity_add(self, ctx, *, channel: Union[TextChannel, Thread]):
        """add vanity tracker channel"""
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
        description="remove a vanity tracker channel",
        example=",tracker vanity remove #vanities",
    )
    @has_permissions(manage_guild=True)
    async def tracker_vanity_remove(self, ctx, *, channel: Union[TextChannel, Thread]):
        """remove vanity tracker"""
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
        for t in trackers:
            guild = self.bot.get_guild(t.guild_id)
            if not guild or not t.channel_ids:
                continue
            ensure_future(notify(guild, vanity, t.channel_ids))

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
        for t in trackers:
            guild = self.bot.get_guild(t.guild_id)
            if not guild or not t.channel_ids:
                continue
            ensure_future(notify(guild, username, t.channel_ids))
