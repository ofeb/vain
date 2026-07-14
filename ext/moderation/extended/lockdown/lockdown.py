import discord
from discord.ext.commands import group, command, CommandError
from discord import Embed, TextChannel, PermissionOverwrite

from core.discord.package import Package
from core.managers.permissions import has_permissions


class Lockdown(Package):
    """lockdown management"""

    @group(
        name="lock",
        aliases=["ld", "lockdown"],
        description="Lockdown a channel",
        invoke_without_command=True,
        example=",lock #general spam raid",
    )
    @has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: TextChannel, *, reason: str = "No reason provided"):
        """lockdown a channel"""
        everyone = ctx.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False
        await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Lockdown by {ctx.author}: {reason}")

        await self.db.execute(
            """INSERT INTO lockdowns (guild_id, channel_id, locked_by, reason)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (guild_id, channel_id) DO UPDATE SET locked_by = $3, reason = $4""",
            ctx.guild.id, channel.id, ctx.author.id, reason,
        )

        return await ctx.success(f"{channel.mention} has been **locked** — {reason}")

    @lock.command(
        name="all",
        description="Locks all channels",
        example=",lock all raid",
    )
    @has_permissions(manage_guild=True)
    async def lock_all(self, ctx, *, reason: str = "No reason provided"):
        """lockdown all channels"""
        ignored_rows = await self.db.fetch(
            """SELECT channel_id FROM lockdown_ignore WHERE guild_id = $1""",
            ctx.guild.id,
        )
        ignored_ids = {row[0] for row in ignored_rows}
        everyone = ctx.guild.default_role
        locked = []

        for channel in ctx.guild.channels:
            if channel.id in ignored_ids:
                continue
            if not isinstance(channel, TextChannel):
                continue
            overwrite = channel.overwrites_for(everyone)
            if overwrite.send_messages is not False:
                overwrite.send_messages = False
                await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Lockdown all by {ctx.author}: {reason}")
                locked.append(channel.mention)

                await self.db.execute(
                    """INSERT INTO lockdowns (guild_id, channel_id, locked_by, reason)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (guild_id, channel_id) DO UPDATE SET locked_by = $3, reason = $4""",
                    ctx.guild.id, channel.id, ctx.author.id, reason,
                )

        if not locked:
            return await ctx.warn("no channels were locked")

        return await ctx.success(f"**{len(locked)}** channels locked — {reason}")

    @lock.command(
        name="role",
        description="Allow a role to bypass lockdown",
        example=",lock role @Admins",
    )
    @has_permissions(manage_guild=True)
    async def lock_role(self, ctx, role):
        """lockdown role"""
        everyone = ctx.guild.default_role
        for channel in ctx.guild.channels:
            if not isinstance(channel, TextChannel):
                continue
            overwrite = channel.overwrites_for(everyone)
            if overwrite.send_messages is False:
                channel_overwrite = channel.overwrites_for(role)
                channel_overwrite.send_messages = True
                await channel.set_permissions(role, overwrite=channel_overwrite, reason=f"Lockdown bypass by {ctx.author}")

        return await ctx.success(f"{role.mention} can now **speak** in locked channels")

    @lock.group(
        name="ignore",
        description="Manage channels ignored from lockdown",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def lock_ignore(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @lock_ignore.command(
        name="add",
        description="Set an ignored lockdown channel",
        example=",lock ignore add #bot-commands",
    )
    @has_permissions(manage_guild=True)
    async def lock_ignore_add(self, ctx, channel: TextChannel):
        """add ignored lockdown channel"""
        existing = await self.db.fetchval(
            """SELECT channel_id FROM lockdown_ignore WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id, channel.id,
        )
        if existing:
            return await ctx.warn(f"{channel.mention} is already **ignored**")

        await self.db.execute(
            """INSERT INTO lockdown_ignore (guild_id, channel_id) VALUES ($1, $2)""",
            ctx.guild.id, channel.id,
        )
        return await ctx.success(f"{channel.mention} will be **ignored** during lockdown all")

    @lock_ignore.command(
        name="remove",
        description="Remove an ignored lockdown channel",
        example=",lock ignore remove #bot-commands",
    )
    @has_permissions(manage_guild=True)
    async def lock_ignore_remove(self, ctx, channel: TextChannel):
        """remove ignored lockdown channel"""
        deleted = await self.db.execute(
            """DELETE FROM lockdown_ignore WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id, channel.id,
        )
        if deleted == "DELETE 0":
            return await ctx.warn(f"{channel.mention} is not **ignored**")
        return await ctx.success(f"{channel.mention} is no longer **ignored** during lockdown all")

    @lock_ignore.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View all ignored lockdown channels",
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
            Embed(title="Ignored Lockdown Channels", color=self.bot.color).set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @group(
        name="unlock",
        aliases=["uld", "unlockdown"],
        description="Unlock a locked channel",
        invoke_without_command=True,
        example=",unlock #general",
    )
    @has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: TextChannel, *, reason: str = "No reason provided"):
        """unlock a channel"""
        everyone = ctx.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = None
        await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Unlocked by {ctx.author}: {reason}")

        await self.db.execute(
            """DELETE FROM lockdowns WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id, channel.id,
        )

        return await ctx.success(f"{channel.mention} has been **unlocked** — {reason}")

    @unlock.command(
        name="all",
        description="Unlocks all locked channels",
        example=",unlock all",
    )
    @has_permissions(manage_guild=True)
    async def unlock_all(self, ctx, *, reason: str = "No reason provided"):
        """unlock all channels"""
        everyone = ctx.guild.default_role
        unlocked = []

        for channel in ctx.guild.channels:
            if not isinstance(channel, TextChannel):
                continue
            overwrite = channel.overwrites_for(everyone)
            if overwrite.send_messages is False:
                overwrite.send_messages = None
                await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Unlock all channels by {ctx.author}: {reason}")
                unlocked.append(channel.mention)

        await self.db.execute(
            """DELETE FROM lockdowns WHERE guild_id = $1""",
            ctx.guild.id,
        )

        if not unlocked:
            return await ctx.warn("no channels are currently **locked**")

        return await ctx.success(f"**{len(unlocked)}** channels unlocked — {reason}")

    @command(
        name="moveall",
        description="Move all members in current channel to another channel",
        example=",moveall #voice-2",
    )
    @has_permissions(administrator=True)
    async def moveall(self, ctx, channel: discord.VoiceChannel):
        """move all members to another voice channel"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise CommandError("you must be in a **voice channel** to use this command")

        source = ctx.author.voice.channel
        members = source.members
        if not members:
            raise CommandError("no members in your current **voice channel**")

        moved = 0
        for member in members:
            try:
                await member.move_to(channel, reason=f"moveall by {ctx.author}")
                moved += 1
            except discord.HTTPException:
                continue

        if not moved:
            return await ctx.fail("failed to move any members")
        return await ctx.success(f"moved **{moved}** members to {channel.mention}")

    @command(
        name="stripstaff",
        description="Remove all staff/dangerous permission roles from a member",
        example=",stripstaff @user",
    )
    @has_permissions(administrator=True)
    async def stripstaff(self, ctx, member: discord.Member):
        """strip staff roles from a member"""
        if member.id == ctx.guild.owner_id:
            raise CommandError("you cannot strip the **server owner**")
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            raise CommandError("that member has a **higher or equal** role than you")

        dangerous_perms = {
            "administrator", "manage_guild", "manage_channels",
            "manage_roles", "ban_members", "kick_members",
            "manage_messages", "manage_webhooks", "manage_expressions",
            "moderate_members",
        }

        staff_roles = []
        for role in member.roles:
            if role.is_default():
                continue
            role_perms = dict(role.permissions)
            if any(role_perms.get(p) for p in dangerous_perms):
                staff_roles.append(role)

        if not staff_roles:
            raise CommandError(f"{member.mention} has no **staff roles** to strip")

        try:
            await member.remove_roles(*staff_roles, reason=f"stripstaff by {ctx.author}")
        except discord.HTTPException as e:
            raise CommandError(f"failed to strip roles: {e}")

        return await ctx.success(f"stripped **{len(staff_roles)}** staff roles from {member.mention}")
