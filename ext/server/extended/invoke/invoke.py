from discord.ext.commands import group, CommandError
from core.discord.package import Package

from core.managers.permissions import has_permissions
VALID_ACTIONS = [
    "softban", "jail", "timeout", "kick", "unban",
    "unjail", "hardban", "untimeout", "tempban", "warn", "ban",
]


def _make_invoke_group(action_name: str):
    """build dm/message subgroup for an action"""
    pass


class InvokeCommands(Package):
    """invoke message customization"""

    @group(name="invoke", description="Change punishment messages for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke(self, ctx):
        """invoke help"""
        return await ctx.send_help(ctx.command)

    @invoke.group(name="softban", description="Change softban message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_softban(self, ctx):
        """softban subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_softban.group(name="dm", description="Change softban message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_softban_dm(self, ctx, *, message: str):
        """set softban dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "softban", message,
        )
        return await ctx.success("softban DM updated")

    @invoke_softban_dm.command(name="view", description="View the softban message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_softban_dm_view(self, ctx):
        """view softban dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "softban",
        )
        if not msg:
            raise CommandError("no softban DM message set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_softban.group(name="message", aliases=["msg"], description="Change softban message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_softban_message(self, ctx, *, message: str):
        """set softban response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "softban", message,
        )
        return await ctx.success("softban response updated")

    @invoke_softban_message.command(name="view", description="View the softban message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_softban_message_view(self, ctx):
        """view softban response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "softban",
        )
        if not msg:
            raise CommandError("no softban response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)


    @invoke.group(name="jail", description="Change jail message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_jail(self, ctx):
        """jail subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_jail.group(name="dm", description="Change jail message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_jail_dm(self, ctx, *, message: str):
        """set jail dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "jail", message,
        )
        return await ctx.success("jail DM updated")

    @invoke_jail_dm.command(name="view", description="View the jail message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_jail_dm_view(self, ctx):
        """view jail dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "jail",
        )
        if not msg:
            raise CommandError("no jail DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_jail.group(name="message", aliases=["msg"], description="Change jail message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_jail_message(self, ctx, *, message: str):
        """set jail response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "jail", message,
        )
        return await ctx.success("jail response updated")

    @invoke_jail_message.command(name="view", description="View the jail message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_jail_message_view(self, ctx):
        """view jail response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "jail",
        )
        if not msg:
            raise CommandError("no jail response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)


    @invoke.group(name="timeout", description="Change timeout message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_timeout(self, ctx):
        """timeout subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_timeout.group(name="dm", description="Change timeout message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_timeout_dm(self, ctx, *, message: str):
        """set timeout dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "timeout", message,
        )
        return await ctx.success("timeout DM updated")

    @invoke_timeout_dm.command(name="view", description="View the timeout message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_timeout_dm_view(self, ctx):
        """view timeout dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "timeout",
        )
        if not msg:
            raise CommandError("no timeout DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_timeout.group(name="message", aliases=["msg"], description="Change timeout message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_timeout_message(self, ctx, *, message: str):
        """set timeout response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "timeout", message,
        )
        return await ctx.success("timeout response updated")

    @invoke_timeout_message.command(name="view", description="View the timeout message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_timeout_message_view(self, ctx):
        """view timeout response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "timeout",
        )
        if not msg:
            raise CommandError("no timeout response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="kick", description="Change kick message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_kick(self, ctx):
        """kick subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_kick.group(name="dm", description="Change kick message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_kick_dm(self, ctx, *, message: str):
        """set kick dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "kick", message,
        )
        return await ctx.success("kick DM updated")

    @invoke_kick_dm.command(name="view", description="View the kick message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_kick_dm_view(self, ctx):
        """view kick dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "kick",
        )
        if not msg:
            raise CommandError("no kick DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_kick.group(name="message", aliases=["msg"], description="Change kick message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_kick_message(self, ctx, *, message: str):
        """set kick response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "kick", message,
        )
        return await ctx.success("kick response updated")

    @invoke_kick_message.command(name="view", description="View the kick message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_kick_message_view(self, ctx):
        """view kick response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "kick",
        )
        if not msg:
            raise CommandError("no kick response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="unban", description="Change unban message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unban(self, ctx):
        """unban subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_unban.group(name="dm", description="Change unban message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unban_dm(self, ctx, *, message: str):
        """set unban dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "unban", message,
        )
        return await ctx.success("unban DM updated")

    @invoke_unban_dm.command(name="view", description="View the unban message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_unban_dm_view(self, ctx):
        """view unban dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "unban",
        )
        if not msg:
            raise CommandError("no unban DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_unban.group(name="message", aliases=["msg"], description="Change unban message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unban_message(self, ctx, *, message: str):
        """set unban response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "unban", message,
        )
        return await ctx.success("unban response updated")

    @invoke_unban_message.command(name="view", description="View the unban message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_unban_message_view(self, ctx):
        """view unban response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "unban",
        )
        if not msg:
            raise CommandError("no unban response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="unjail", description="Change unjail message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unjail(self, ctx):
        """unjail subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_unjail.group(name="dm", description="Change unjail message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unjail_dm(self, ctx, *, message: str):
        """set unjail dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "unjail", message,
        )
        return await ctx.success("unjail DM updated")

    @invoke_unjail_dm.command(name="view", description="View the unjail message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_unjail_dm_view(self, ctx):
        """view unjail dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "unjail",
        )
        if not msg:
            raise CommandError("no unjail DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_unjail.group(name="message", aliases=["msg"], description="Change unjail message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unjail_message(self, ctx, *, message: str):
        """set unjail response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "unjail", message,
        )
        return await ctx.success("unjail response updated")

    @invoke_unjail_message.command(name="view", description="View the unjail message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_unjail_message_view(self, ctx):
        """view unjail response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "unjail",
        )
        if not msg:
            raise CommandError("no unjail response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="hardban", description="Change hardban message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_hardban(self, ctx):
        """hardban subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_hardban.group(name="dm", description="set hardban DM", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_hardban_dm(self, ctx, *, message: str):
        """set hardban dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "hardban", message,
        )
        return await ctx.success("hardban DM updated")

    @invoke_hardban_dm.command(name="view", description="preview hardban DM")
    @has_permissions(manage_guild=True)
    async def invoke_hardban_dm_view(self, ctx):
        """view hardban dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "hardban",
        )
        if not msg:
            raise CommandError("no hardban DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_hardban.group(name="message", aliases=["msg"], description="Change hardban message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_hardban_message(self, ctx, *, message: str):
        """set hardban response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "hardban", message,
        )
        return await ctx.success("hardban response updated")

    @invoke_hardban_message.command(name="view", description="View the hardban message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_hardban_message_view(self, ctx):
        """view hardban response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "hardban",
        )
        if not msg:
            raise CommandError("no hardban response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="untimeout", description="Change untimeout message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_untimeout(self, ctx):
        """untimeout subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_untimeout.group(name="dm", description="Change untimeout message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_untimeout_dm(self, ctx, *, message: str):
        """set untimeout dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "untimeout", message,
        )
        return await ctx.success("untimeout DM updated")

    @invoke_untimeout_dm.command(name="view", description="View the untimeout message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_untimeout_dm_view(self, ctx):
        """view untimeout dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "untimeout",
        )
        if not msg:
            raise CommandError("no untimeout DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_untimeout.group(name="message", aliases=["msg"], description="Change untimeout message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_untimeout_message(self, ctx, *, message: str):
        """set untimeout response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "untimeout", message,
        )
        return await ctx.success("untimeout response updated")

    @invoke_untimeout_message.command(name="view", description="View the untimeout message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_untimeout_message_view(self, ctx):
        """view untimeout response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "untimeout",
        )
        if not msg:
            raise CommandError("no untimeout response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="tempban", description="Change tempban message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_tempban(self, ctx):
        """tempban subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_tempban.group(name="dm", description="Change tempban message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_tempban_dm(self, ctx, *, message: str):
        """set tempban dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "tempban", message,
        )
        return await ctx.success("tempban DM updated")

    @invoke_tempban_dm.command(name="view", description="View the tempban message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_tempban_dm_view(self, ctx):
        """view tempban dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "tempban",
        )
        if not msg:
            raise CommandError("no tempban DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_tempban.group(name="message", aliases=["msg"], description="Change tempban message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_tempban_message(self, ctx, *, message: str):
        """set tempban response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "tempban", message,
        )
        return await ctx.success("tempban response updated")

    @invoke_tempban_message.command(name="view", description="View the tempban message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_tempban_message_view(self, ctx):
        """view tempban response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "tempban",
        )
        if not msg:
            raise CommandError("no tempban response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="warn", description="Change warn message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_warn(self, ctx):
        """warn subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_warn.group(name="dm", description="Change warn message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_warn_dm(self, ctx, *, message: str):
        """set warn dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "warn", message,
        )
        return await ctx.success("warn DM updated")

    @invoke_warn_dm.command(name="view", description="View the warn message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_warn_dm_view(self, ctx):
        """view warn dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "warn",
        )
        if not msg:
            raise CommandError("no warn DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_warn.group(name="message", aliases=["msg"], description="Change warn message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_warn_message(self, ctx, *, message: str):
        """set warn response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "warn", message,
        )
        return await ctx.success("warn response updated")

    @invoke_warn_message.command(name="view", description="View the warn message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_warn_message_view(self, ctx):
        """view warn response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "warn",
        )
        if not msg:
            raise CommandError("no warn response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="ban", description="Change ban message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_ban(self, ctx):
        """ban subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_ban.group(name="dm", description="Change ban message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_ban_dm(self, ctx, *, message: str):
        """set ban dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "ban", message,
        )
        return await ctx.success("ban DM updated")

    @invoke_ban_dm.command(name="view", description="View the ban message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_ban_dm_view(self, ctx):
        """view ban dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "ban",
        )
        if not msg:
            raise CommandError("no ban DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_ban.group(name="message", aliases=["msg"], description="Change ban message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_ban_message(self, ctx, *, message: str):
        """set ban response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "ban", message,
        )
        return await ctx.success("ban response updated")

    @invoke_ban_message.command(name="view", description="View the ban message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_ban_message_view(self, ctx):
        """view ban response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "ban",
        )
        if not msg:
            raise CommandError("no ban response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="mute", description="Change mute message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_mute(self, ctx):
        """mute subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_mute.group(name="dm", description="Change mute message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_mute_dm(self, ctx, *, message: str):
        """set mute dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "mute", message,
        )
        return await ctx.success("mute DM updated")

    @invoke_mute_dm.command(name="view", description="View the mute message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_mute_dm_view(self, ctx):
        """view mute dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "mute",
        )
        if not msg:
            raise CommandError("no mute DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_mute.group(name="message", aliases=["msg"], description="Change mute message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_mute_message(self, ctx, *, message: str):
        """set mute response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "mute", message,
        )
        return await ctx.success("mute response updated")

    @invoke_mute_message.command(name="view", description="View the mute message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_mute_message_view(self, ctx):
        """view mute response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "mute",
        )
        if not msg:
            raise CommandError("no mute response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="unmute", description="Change unmute message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unmute(self, ctx):
        """unmute subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_unmute.group(name="dm", description="Change unmute message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unmute_dm(self, ctx, *, message: str):
        """set unmute dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "unmute", message,
        )
        return await ctx.success("unmute DM updated")

    @invoke_unmute_dm.command(name="view", description="View the unmute message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_unmute_dm_view(self, ctx):
        """view unmute dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "unmute",
        )
        if not msg:
            raise CommandError("no unmute DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_unmute.group(name="message", aliases=["msg"], description="Change unmute message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_unmute_message(self, ctx, *, message: str):
        """set unmute response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "unmute", message,
        )
        return await ctx.success("unmute response updated")

    @invoke_unmute_message.command(name="view", description="View the unmute message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_unmute_message_view(self, ctx):
        """view unmute response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "unmute",
        )
        if not msg:
            raise CommandError("no unmute response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="imute", description="Change imute message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_imute(self, ctx):
        """imute subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_imute.group(name="dm", description="Change imute message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_imute_dm(self, ctx, *, message: str):
        """set imute dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "imute", message,
        )
        return await ctx.success("imute DM updated")

    @invoke_imute_dm.command(name="view", description="View the imute message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_imute_dm_view(self, ctx):
        """view imute dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "imute",
        )
        if not msg:
            raise CommandError("no imute DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_imute.group(name="message", aliases=["msg"], description="Change imute message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_imute_message(self, ctx, *, message: str):
        """set imute response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "imute", message,
        )
        return await ctx.success("imute response updated")

    @invoke_imute_message.command(name="view", description="View the imute message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_imute_message_view(self, ctx):
        """view imute response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "imute",
        )
        if not msg:
            raise CommandError("no imute response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="iunmute", description="Change iunmute message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_iunmute(self, ctx):
        """iunmute subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_iunmute.group(name="dm", description="Change iunmute message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_iunmute_dm(self, ctx, *, message: str):
        """set iunmute dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "iunmute", message,
        )
        return await ctx.success("iunmute DM updated")

    @invoke_iunmute_dm.command(name="view", description="View the iunmute message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_iunmute_dm_view(self, ctx):
        """view iunmute dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "iunmute",
        )
        if not msg:
            raise CommandError("no iunmute DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_iunmute.group(name="message", aliases=["msg"], description="Change iunmute message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_iunmute_message(self, ctx, *, message: str):
        """set iunmute response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "iunmute", message,
        )
        return await ctx.success("iunmute response updated")

    @invoke_iunmute_message.command(name="view", description="View the iunmute message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_iunmute_message_view(self, ctx):
        """view iunmute response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "iunmute",
        )
        if not msg:
            raise CommandError("no iunmute response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="rmute", description="Change rmute message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_rmute(self, ctx):
        """rmute subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_rmute.group(name="dm", description="Change rmute message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_rmute_dm(self, ctx, *, message: str):
        """set rmute dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "rmute", message,
        )
        return await ctx.success("rmute DM updated")

    @invoke_rmute_dm.command(name="view", description="View the rmute message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_rmute_dm_view(self, ctx):
        """view rmute dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "rmute",
        )
        if not msg:
            raise CommandError("no rmute DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_rmute.group(name="message", aliases=["msg"], description="Change rmute message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_rmute_message(self, ctx, *, message: str):
        """set rmute response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "rmute", message,
        )
        return await ctx.success("rmute response updated")

    @invoke_rmute_message.command(name="view", description="View the rmute message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_rmute_message_view(self, ctx):
        """view rmute response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "rmute",
        )
        if not msg:
            raise CommandError("no rmute response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke.group(name="runmute", description="Change runmute message for DM or command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_runmute(self, ctx):
        """runmute subgroup"""
        return await ctx.send_help(ctx.command)

    @invoke_runmute.group(name="dm", description="Change runmute message for Direct Messages", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_runmute_dm(self, ctx, *, message: str):
        """set runmute dm"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, dm_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET dm_code = excluded.dm_code""",
            ctx.guild.id, "runmute", message,
        )
        return await ctx.success("runmute DM updated")

    @invoke_runmute_dm.command(name="view", description="View the runmute message for Direct Messages")
    @has_permissions(manage_guild=True)
    async def invoke_runmute_dm_view(self, ctx):
        """view runmute dm"""
        msg = await self.db.fetchval(
            """SELECT dm_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "runmute",
        )
        if not msg:
            raise CommandError("no runmute DM set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)

    @invoke_runmute.group(name="message", aliases=["msg"], description="Change runmute message for command response", invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def invoke_runmute_message(self, ctx, *, message: str):
        """set runmute response"""
        await self.db.execute(
            """INSERT INTO invocation (guild_id, command, message_code) VALUES($1, $2, $3) ON CONFLICT(guild_id, command) DO UPDATE SET message_code = excluded.message_code""",
            ctx.guild.id, "runmute", message,
        )
        return await ctx.success("runmute response updated")

    @invoke_runmute_message.command(name="view", description="View the runmute message for command response")
    @has_permissions(manage_guild=True)
    async def invoke_runmute_message_view(self, ctx):
        """view runmute response"""
        msg = await self.db.fetchval(
            """SELECT message_code FROM invocation WHERE guild_id = $1 AND command = $2""",
            ctx.guild.id, "runmute",
        )
        if not msg:
            raise CommandError("no runmute response set")
        return await self.bot.send_embed(ctx.channel, msg, user=ctx.author, moderator=ctx.author)
