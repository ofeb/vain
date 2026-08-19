import discord
from discord.ext.commands import group, CommandError
from discord import Embed, TextChannel

from core.discord.package import Package
from core.managers.permissions import has_permissions


class Lockdown(Package):
    """lockdown management"""

    async def _parse_channel_and_target(self, ctx, first: str | None, second: str | None):
        if first is None:
            return ctx.channel, None
        try:
            ch = await discord.ext.commands.TextChannelConverter().convert(ctx, first)
            return ch, second
        except CommandError:
            return ctx.channel, first

    async def _resolve_target(self, ctx, token: str | None):
        if not token:
            return ctx.guild.default_role
        for converter in (
            discord.ext.commands.RoleConverter(),
            discord.ext.commands.MemberConverter(),
        ):
            try:
                return await converter.convert(ctx, token)
            except CommandError:
                continue
        raise CommandError(f"couldn't find a role or member matching `{token}`")

    @group(
        name="lock",
        aliases=["ld", "lockdown"],
        description="lockdown a channel for everyone or a specific user/role",
        invoke_without_command=True,
        example=",lock #general raid",
    )
    @has_permissions(manage_channels=True)
    async def lock(
        self,
        ctx,
        first: str = None,
        second: str = None,
    ):
        """lockdown a channel (defaults to current channel)"""
        channel, target_str = await self._parse_channel_and_target(ctx, first, second)
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        target = await self._resolve_target(ctx, target_str)
        overwrite = channel.overwrites_for(target)
        overwrite.send_messages = False
        await channel.set_permissions(
            target,
            overwrite=overwrite,
            reason=f"Lockdown by {ctx.author}",
        )

        await self.db.execute(
            """INSERT INTO lockdowns (guild_id, channel_id, locked_by, reason)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (guild_id, channel_id) DO UPDATE SET locked_by = $3, reason = $4""",
            ctx.guild.id,
            channel.id,
            ctx.author.id,
            "lockdown",
        )

        who = "**everyone**" if target == ctx.guild.default_role else target.mention
        return await ctx.success(f"{channel.mention} has been **locked** for {who}")

    @lock.command(
        name="all",
        description="locks all channels",
        example=",lock all raid",
    )
    @has_permissions(manage_guild=True)
    async def lock_all(self, ctx, *, reason: str = "No reason provided"):
        """lockdown all channels"""
        from core.discord.views.confirm import ThreeButtonConfirmView, ConfirmChoice

        ignored_rows = await self.db.fetch(
            """SELECT channel_id FROM lockdown_ignore WHERE guild_id = $1""",
            ctx.guild.id,
        )
        ignored_ids = {row[0] for row in ignored_rows}
        everyone = ctx.guild.default_role
        already_locked = []
        to_lock = []

        for channel in ctx.guild.channels:
            if channel.id in ignored_ids:
                continue
            if not isinstance(channel, TextChannel):
                continue
            overwrite = channel.overwrites_for(everyone)
            if overwrite.send_messages is False:
                already_locked.append(channel)
            else:
                to_lock.append(channel)

        if not to_lock:
            return await ctx.warn("All channels are **already** locked")

        if already_locked:
            msg = (
                f"**{len(already_locked)}** channel(s) were **already locked** before using **lockdown all**\n"
                f"> -# **approve locks all channels** ;\n"
                f"> -# **deny locks only the channels that weren't locked** ;\n"
                f"> -# **cancel this using the cancel button**"
            )
        else:
            msg = (
                f"**{len(to_lock)}** channel(s) will be locked.\n"
                f"> -# **approve locks all channels** ;\n"
                f"> -# **deny locks only the channels that weren't locked** ;\n"
                f"> -# **cancel this using the cancel button**"
            )

        view = ThreeButtonConfirmView(ctx, show_cancel=True)
        choice = await view.prompt(msg)

        if choice == ConfirmChoice.CANCEL:
            return await ctx.warn("Cancelled\n> -# **lockdown all was cancelled**")

        locked = []

        if choice == ConfirmChoice.DENY:
            for channel in to_lock:
                overwrite = channel.overwrites_for(everyone)
                overwrite.send_messages = False
                await channel.set_permissions(
                    everyone,
                    overwrite=overwrite,
                    reason=f"Lockdown all by {ctx.author}: {reason}",
                )
                locked.append(channel.mention)
                await self.db.execute(
                    """INSERT INTO lockdowns (guild_id, channel_id, locked_by, reason)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (guild_id, channel_id) DO UPDATE SET locked_by = $3, reason = $4""",
                    ctx.guild.id,
                    channel.id,
                    ctx.author.id,
                    reason,
                )
        else:
            for channel in ctx.guild.channels:
                if channel.id in ignored_ids:
                    continue
                if not isinstance(channel, TextChannel):
                    continue
                overwrite = channel.overwrites_for(everyone)
                if overwrite.send_messages is not False:
                    overwrite.send_messages = False
                    await channel.set_permissions(
                        everyone,
                        overwrite=overwrite,
                        reason=f"Lockdown all by {ctx.author}: {reason}",
                    )
                    locked.append(channel.mention)
                    await self.db.execute(
                        """INSERT INTO lockdowns (guild_id, channel_id, locked_by, reason)
                           VALUES ($1, $2, $3, $4)
                           ON CONFLICT (guild_id, channel_id) DO UPDATE SET locked_by = $3, reason = $4""",
                        ctx.guild.id,
                        channel.id,
                        ctx.author.id,
                        reason,
                    )

        return await ctx.success(f"**{len(locked)}** channels locked - {reason}")

    @lock.command(
        name="role",
        description="allow a role to bypass lockdown",
        example=",lock role @Admins",
    )
    @has_permissions(manage_guild=True)
    async def lock_role(self, ctx, role: discord.Role):
        """lockdown role"""
        everyone = ctx.guild.default_role
        for channel in ctx.guild.channels:
            if not isinstance(channel, TextChannel):
                continue
            overwrite = channel.overwrites_for(everyone)
            if overwrite.send_messages is False:
                channel_overwrite = channel.overwrites_for(role)
                channel_overwrite.send_messages = True
                await channel.set_permissions(
                    role,
                    overwrite=channel_overwrite,
                    reason=f"Lockdown bypass by {ctx.author}",
                )

        return await ctx.success(f"{role.mention} can now **speak** in locked channels")

    @lock.group(
        name="ignore",
        description="manage channels ignored from lockdown",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def lock_ignore(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @lock_ignore.command(
        name="add",
        description="set an ignored lockdown channel",
        example=",lock ignore add #bot-commands",
    )
    @has_permissions(manage_guild=True)
    async def lock_ignore_add(self, ctx, channel: TextChannel = None):
        """add ignored lockdown channel"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        existing = await self.db.fetchval(
            """SELECT channel_id FROM lockdown_ignore WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id,
            channel.id,
        )
        if existing:
            return await ctx.warn(f"{channel.mention} is already **ignored**")

        await self.db.execute(
            """INSERT INTO lockdown_ignore (guild_id, channel_id) VALUES ($1, $2)""",
            ctx.guild.id,
            channel.id,
        )
        return await ctx.success(
            f"{channel.mention} will be **ignored** during lockdown all"
        )

    @lock_ignore.command(
        name="remove",
        description="remove an ignored lockdown channel",
        example=",lock ignore remove #bot-commands",
    )
    @has_permissions(manage_guild=True)
    async def lock_ignore_remove(self, ctx, channel: TextChannel = None):
        """remove ignored lockdown channel"""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        deleted = await self.db.execute(
            """DELETE FROM lockdown_ignore WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id,
            channel.id,
        )
        if deleted == "DELETE 0":
            return await ctx.warn(f"{channel.mention} is not **ignored**")
        return await ctx.success(
            f"{channel.mention} is no longer **ignored** during lockdown all"
        )

    @lock_ignore.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="view all ignored lockdown channels",
    )
    @has_permissions(manage_guild=True)
    async def lock_ignore_list(self, ctx):
        """list ignored lockdown channels"""
        rows = await self.db.fetch(
            """SELECT channel_id FROM lockdown_ignore WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("no channels are **ignored** from lockdown")

        lines = []
        for row in rows:
            ch = ctx.guild.get_channel(row[0])
            if ch:
                lines.append(ch.mention)

        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            Embed(title="Ignored Lockdown Channels").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @group(
        name="unlock",
        aliases=["uld", "unlockdown"],
        description="unlock a locked channel",
        invoke_without_command=True,
        example=",unlock #general",
    )
    @has_permissions(manage_channels=True)
    async def unlock(
        self,
        ctx,
        first: str = None,
        second: str = None,
    ):
        """unlock a channel (defaults to current channel)"""
        channel, target_str = await self._parse_channel_and_target(ctx, first, second)
        if not isinstance(channel, TextChannel):
            raise CommandError("this command only works on **text channels**")

        target = await self._resolve_target(ctx, target_str)
        overwrite = channel.overwrites_for(target)
        overwrite.send_messages = None
        await channel.set_permissions(
            target,
            overwrite=overwrite,
            reason=f"Unlocked by {ctx.author}",
        )

        await self.db.execute(
            """DELETE FROM lockdowns WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id,
            channel.id,
        )

        who = "**everyone**" if target == ctx.guild.default_role else target.mention
        return await ctx.success(f"{channel.mention} has been **unlocked** for {who}")

    @unlock.command(
        name="all",
        description="unlocks all locked channels",
        example=",unlock all",
    )
    @has_permissions(manage_guild=True)
    async def unlock_all(self, ctx, *, reason: str = "No reason provided"):
        """unlock all channels"""
        from core.discord.views.confirm import ThreeButtonConfirmView, ConfirmChoice

        everyone = ctx.guild.default_role
        already_locked = []
        already_unlocked = []

        for channel in ctx.guild.channels:
            if not isinstance(channel, TextChannel):
                continue
            overwrite = channel.overwrites_for(everyone)
            if overwrite.send_messages is False:
                already_locked.append(channel)
            else:
                already_unlocked.append(channel)

        if not already_locked:
            return await ctx.warn("No channels are currently **locked**")

        if already_unlocked:
            msg = (
                f"**{len(already_locked)}** channel(s) were **already locked** before using **unlockdown all**\n"
                f"> -# **approve unlocks all channels** ;\n"
                f"> -# **deny unlocks only the channels that were locked using lockdown** ;\n"
                f"> -# **cancel this using the cancel button**"
            )
        else:
            msg = (
                f"**{len(already_locked)}** channel(s) will be unlocked.\n"
                f"> -# **approve unlocks all channels** ;\n"
                f"> -# **deny unlocks only the channels that were locked using lockdown** ;\n"
                f"> -# **cancel this using the cancel button**"
            )

        view = ThreeButtonConfirmView(ctx, show_cancel=True)
        choice = await view.prompt(msg)

        if choice == ConfirmChoice.CANCEL:
            return await ctx.warn("Cancelled\n> -# **unlockdown all was cancelled**")

        unlocked = []

        if choice == ConfirmChoice.DENY:
            for channel in already_locked:
                overwrite = channel.overwrites_for(everyone)
                overwrite.send_messages = None
                await channel.set_permissions(
                    everyone,
                    overwrite=overwrite,
                    reason=f"Unlock all channels by {ctx.author}: {reason}",
                )
                unlocked.append(channel.mention)
            await self.db.execute(
                """DELETE FROM lockdowns WHERE guild_id = $1""",
                ctx.guild.id,
            )
        else:
            for channel in ctx.guild.channels:
                if not isinstance(channel, TextChannel):
                    continue
                overwrite = channel.overwrites_for(everyone)
                if overwrite.send_messages is False:
                    overwrite.send_messages = None
                    await channel.set_permissions(
                        everyone,
                        overwrite=overwrite,
                        reason=f"Unlock all channels by {ctx.author}: {reason}",
                    )
                    unlocked.append(channel.mention)
            await self.db.execute(
                """DELETE FROM lockdowns WHERE guild_id = $1""",
                ctx.guild.id,
            )

        return await ctx.success(f"**{len(unlocked)}** channels unlocked - {reason}")
