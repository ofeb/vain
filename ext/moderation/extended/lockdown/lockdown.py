from discord.ext.commands import group, CommandError
from discord import Embed, TextChannel, PermissionOverwrite

from core.discord.package import Package
from core.managers.permissions import has_permissions
from lib.classes.converters import EVENT_MAPPING


class Lockdown(Package):
    """lockdown management"""

    @group(
        name="lockdown",
        description="Lockdown a channel",
        invoke_without_command=True,
        example=",lockdown #general spam raid",
    )
    @has_permissions(manage_channels=True)
    async def lockdown(self, ctx, channel: TextChannel, *, reason: str = "No reason provided"):
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

    @lockdown.command(
        name="all",
        description="Locks all channels",
        example=",lockdown all raid",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_all(self, ctx, *, reason: str = "No reason provided"):
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
            return await ctx.fail("no channels were locked")

        return await ctx.success(f"**{len(locked)}** channels locked — {reason}")

    @lockdown.command(
        name="role",
        description="Allow a role to bypass lockdown",
        example=",lockdown role @Admins",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_role(self, ctx, role):
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

    ignore = group(
        name="ignore",
        description="Manage channels ignored from lockdown",
        invoke_without_command=True,
    )

    @ignore.command(
        name="add",
        description="Set an ignored lockdown channel",
        example=",lockdown ignore add #bot-commands",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_ignore_add(self, ctx, channel: TextChannel):
        """add ignored lockdown channel"""
        existing = await self.db.fetchval(
            """SELECT channel_id FROM lockdown_ignore WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id, channel.id,
        )
        if existing:
            return await ctx.fail(f"{channel.mention} is already **ignored**")

        await self.db.execute(
            """INSERT INTO lockdown_ignore (guild_id, channel_id) VALUES ($1, $2)""",
            ctx.guild.id, channel.id,
        )
        return await ctx.success(f"{channel.mention} will be **ignored** during lockdown all")

    @ignore.command(
        name="remove",
        description="Remove an ignored lockdown channel",
        example=",lockdown ignore remove #bot-commands",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_ignore_remove(self, ctx, channel: TextChannel):
        """remove ignored lockdown channel"""
        deleted = await self.db.execute(
            """DELETE FROM lockdown_ignore WHERE guild_id = $1 AND channel_id = $2""",
            ctx.guild.id, channel.id,
        )
        if deleted == "DELETE 0":
            return await ctx.fail(f"{channel.mention} is not **ignored**")
        return await ctx.success(f"{channel.mention} is no longer **ignored** during lockdown all")

    @ignore.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View all ignored lockdown channels",
    )
    @has_permissions(manage_guild=True)
    async def lockdown_ignore_list(self, ctx):
        """list ignored lockdown channels"""
        rows = await self.db.fetch(
            """SELECT channel_id FROM lockdown_ignore WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.fail("no channels are **ignored** from lockdown")

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
        await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Unlock by {ctx.author}: {reason}")

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
                await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Unlock all by {ctx.author}: {reason}")
                unlocked.append(channel.mention)

        await self.db.execute(
            """DELETE FROM lockdowns WHERE guild_id = $1""",
            ctx.guild.id,
        )

        if not unlocked:
            return await ctx.fail("no channels are currently **locked**")

        return await ctx.success(f"**{len(unlocked)}** channels unlocked — {reason}")
