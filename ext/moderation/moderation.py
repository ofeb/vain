from __future__ import annotations

import discord
from discord.ext.commands import command, has_permissions
from discord.ext.commands import CommandError

from core.discord.package import Package


class ModerationCommands(Package):
    """standalone moderation commands"""

    def _audit_reason(self, ctx, reason: str | None) -> str:
        base = reason or "no reason provided"
        return f"{base} | executed by {ctx.author} ({ctx.author.id})"

    def _default_reason(self, reason: str | None) -> str:
        return reason or "no reason provided"

    def _ensure_targetable(self, ctx, member: discord.Member) -> None:
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")
        if member.id == ctx.author.id:
            raise CommandError("you cannot moderate yourself")
        if member.id == ctx.guild.owner_id:
            raise CommandError("you cannot moderate the server owner")

        author = ctx.author if isinstance(ctx.author, discord.Member) else None
        bot_member = ctx.guild.me or ctx.guild.get_member(self.bot.user.id if self.bot.user else 0)
        if author and ctx.guild.owner_id != author.id and member.top_role >= author.top_role:
            raise CommandError("that member is above or equal to your highest role")
        if bot_member is None:
            raise CommandError("I could not resolve my server member")
        if member.top_role >= bot_member.top_role:
            raise CommandError("that member is above or equal to my highest role")

    async def _create_case(
        self,
        ctx,
        *,
        action: str,
        target_id: int,
        reason: str | None,
    ) -> int | None:
        if getattr(self.db, "pool", None) is None:
            return None
        return await self.db.create_case(
            guild_id=ctx.guild.id,
            action=action,
            target_id=target_id,
            moderator_id=ctx.author.id,
            reason=self._default_reason(reason),
        )

    async def _send_modlog(
        self,
        ctx,
        *,
        action: str,
        target: discord.abc.User | None,
        case_id: int | None,
        reason: str | None,
    ) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        channel_id = await self.db.get_modlog_channel(ctx.guild.id)
        if not channel_id:
            return
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        target_label = str(target) if target else "Unknown User"
        embed = discord.Embed(
            color=self.color,
            title=f"Case #{case_id}" if case_id is not None else "Moderation action",
            description=(
                f"**Action:** {action}\n"
                f"**Target:** {target_label}\n"
                f"**Moderator:** {ctx.author}\n"
                f"**Reason:** {self._default_reason(reason)}"
            ),
        )
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    def _dispatch_antinuke_action(
        self,
        ctx,
        *,
        action: str,
        case_id: int | None,
        meta: dict | None = None,
    ) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return
        ctx.bot.dispatch(
            "antinuke_action",
            ctx.guild,
            ctx.author,
            action,
            case_id or 0,
            meta,
        )

    @command(
        name="tempban",
        description="No description given",
    )
    @has_permissions(ban_members=True)
    async def tempban(self, ctx, member, duration, *, reason):
        """temporarily ban a member"""
        pass

    @command(
        name="warn",
        description="Warns the mentioned user and private messages them the warning",
    )
    async def warn(self, ctx, member, *, reason):
        """warn a member"""
        pass

    @command(
        name="moveall",
        description="Move all members in current channel to another channel",
    )
    @has_permissions(administrator=True)
    async def moveall(self, ctx, channel):
        """move all members to another channel"""
        pass

    @command(
        name="stripstaff",
        description="No description given",
    )
    @has_permissions(administrator=True)
    async def stripstaff(self, ctx, member):
        """strip staff roles from member"""
        pass

    @command(
        name="jail",
        description="No description given",
    )
    async def jail(self, ctx, member, duration, *, reason):
        """jail a member"""
        pass

    @command(
        name="unjail",
        description="Unjails the mentioned user",
    )
    async def unjail(self, ctx, member, *, reason):
        """unjail a member"""
        pass

    @command(
        name="modstats",
        description="No description given",
    )
    @has_permissions(manage_messages=True)
    async def modstats(self, ctx, member):
        """view moderation stats for a member"""
        pass

    @command(
        name="warnings",
        description="View warnings for a member",
    )
    @has_permissions(manage_messages=True)
    async def warnings(self, ctx, member):
        """view warnings for a member"""
        pass

    @command(
        name="moderationhistory",
        description="View moderation actions from a staff member",
    )
    @has_permissions(manage_messages=True)
    async def moderationhistory(self, ctx, member, command):
        """view moderation history for a staff member"""
        pass

    @command(
        name="jaillist",
        description="View a list of every current jailed member",
    )
    @has_permissions(manage_messages=True)
    async def jaillist(self, ctx):
        """list all jailed members"""
        pass

    @command(
        name="caselog",
        description="No description given",
    )
    async def caselog(self, ctx, case_id):
        """view case log"""
        pass

    @command(
        name="timeout",
        description="Mutes the provided member using Discords timeout feature",
    )
    async def timeout(self, ctx, member, duration, *, reason):
        """timeout a member"""
        pass

    @command(
        name="untimeout",
        description="Removes a timeout for a member",
    )
    async def untimeout(self, ctx, member, *, reason):
        """remove timeout from a member"""
        pass

    @command(
        name="mute",
        description="No description given",
    )
    async def mute(self, ctx, member, duration, *, reason):
        """mute a member"""
        pass

    @command(
        name="unmute",
        description="No description given",
    )
    @has_permissions(moderate_members=True)
    async def unmute(self, ctx, member, *, reason):
        """unmute a member"""
        pass

    @command(
        name="imute",
        description="No description given",
    )
    @has_permissions(moderate_members=True)
    async def imute(self, ctx, member, *, reason):
        """image mute a member"""
        pass

    @command(
        name="iunmute",
        description="No description given",
    )
    @has_permissions(moderate_members=True)
    async def iunmute(self, ctx, member, *, reason):
        """un image mute a member"""
        pass

    @command(
        name="rmute",
        description="No description given",
    )
    @has_permissions(moderate_members=True)
    async def rmute(self, ctx, member, *, reason):
        """reaction mute a member"""
        pass

    @command(
        name="runmute",
        description="No description given",
    )
    @has_permissions(moderate_members=True)
    async def runmute(self, ctx, member, *, reason):
        """un reaction mute a member"""
        pass

    @command(
        name="hardban",
        description="Keep a member banned",
    )
    async def hardban(self, ctx, member, *, reason):
        """hardban a member"""
        pass

    @command(
        name="hardban list",
        description="View list of hardbanned members",
    )
    @has_permissions(administrator=True)
    async def hardban_list(self, ctx):
        """list hardbanned members"""
        pass

    @command(
        name="clearinvites",
        description="Remove all existing invites in guild",
    )
    @has_permissions(manage_guild=True)
    async def clearinvites(self, ctx, params):
        """clear all invites"""
        pass

    @command(
        name="drag",
        description="Drag member(s) to the specified Voice Channel",
    )
    async def drag(self, ctx, members, channel):
        """drag members to voice channel"""
        pass

    @command(
        name="unbanall",
        description="Unbans every member in a guild",
    )
    async def unbanall(self, ctx):
        """unban all members"""
        pass

    @command(
        name="unbanall cancel",
        description="Cancels a unban all task running",
    )
    async def unbanall_cancel(self, ctx):
        """cancel unban all task"""
        pass

    @command(
        name="unban",
        description="Unbans the mentioned user",
    )
    async def unban(self, ctx, user, *, reason):
        """unban a user"""
        pass

    @command(
        name="softban",
        description="Softbans the mentioned user and deleting 1 day of messages",
    )
    async def softban(self, ctx, member, delete_history, *, reason):
        """softban a member"""
        pass

    @command(
        name="ban",
        description="No description given",
    )
    @has_permissions(ban_members=True)
    async def ban(
        self,
        ctx,
        member: discord.Member,
        delete_history: int = 0,
        *,
        reason: str = None,
    ):
        """ban a member"""
        self._ensure_targetable(ctx, member)

        delete_days = max(0, min(int(delete_history or 0), 7))
        role_ids = [
            role.id
            for role in member.roles
            if role != ctx.guild.default_role
        ]
        target_display = str(member)
        target_id = member.id

        await member.ban(
            delete_message_seconds=delete_days * 86400,
            reason=self._audit_reason(ctx, reason),
        )

        case_id = await self._create_case(
            ctx,
            action="ban",
            target_id=target_id,
            reason=reason,
        )
        await self._send_modlog(
            ctx,
            action="ban",
            target=member,
            case_id=case_id,
            reason=reason,
        )
        self._dispatch_antinuke_action(
            ctx,
            action="ban",
            case_id=case_id,
            meta={
                "target_id": target_id,
                "target_display": target_display,
                "role_ids": role_ids,
            },
        )
        return await ctx.success(
            f"Banned **{target_display}** - {self._default_reason(reason)}"
        )

    @command(
        name="kick",
        description="Kick the mentioned user",
    )
    @has_permissions(kick_members=True)
    async def kick(
        self,
        ctx,
        member: discord.Member,
        *,
        reason: str = None,
    ):
        """kick a member"""
        self._ensure_targetable(ctx, member)

        role_ids = [
            role.id
            for role in member.roles
            if role != ctx.guild.default_role
        ]
        target_display = str(member)
        target_id = member.id

        await member.kick(reason=self._audit_reason(ctx, reason))

        case_id = await self._create_case(
            ctx,
            action="kick",
            target_id=target_id,
            reason=reason,
        )
        await self._send_modlog(
            ctx,
            action="kick",
            target=member,
            case_id=case_id,
            reason=reason,
        )
        self._dispatch_antinuke_action(
            ctx,
            action="kick",
            case_id=case_id,
            meta={
                "target_id": target_id,
                "target_display": target_display,
                "role_ids": role_ids,
            },
        )
        return await ctx.success(
            f"Kicked **{target_display}** - {self._default_reason(reason)}"
        )

    @command(
        name="ban recent",
        description="No description given",
    )
    async def ban_recent(self, ctx):
        """ban recent members"""
        pass

    @command(
        name="ban purge",
        description="No description given",
    )
    async def ban_purge(self, ctx, delete_history):
        """ban and purge"""
        pass

    @command(
        name="temprole",
        description="No description given",
    )
    @has_permissions(manage_roles=True)
    async def temprole(self, ctx, member, duration, role):
        """give temporary role"""
        pass

    @command(
        name="temprole list",
        description="No description given",
    )
    @has_permissions(manage_roles=True)
    async def temprole_list(self, ctx):
        """list temporary roles"""
        pass

    @command(
        name="dump",
        description="Dumps all members of a role",
    )
    @has_permissions(manage_roles=True)
    async def dump(self, ctx, role, flags):
        """dump role members"""
        pass

    @command(
        name="newmembers",
        description="View list of recently joined members",
    )
    async def newmembers(self, ctx, count):
        """view new members"""
        pass

    @command(
        name="recentban",
        description="Chunk ban recently joined members",
    )
    @has_permissions(ban_members=True)
    async def recentban(self, ctx, count, *, reason):
        """ban recent members"""
        pass

    @command(
        name="talk",
        description="Toggle a channel to text for a role",
    )
    @has_permissions(manage_channels=True)
    async def talk(self, ctx, channel, role):
        """toggle channel text for role"""
        pass

    @command(
        name="unhide",
        description="Unhide a channel from a role or member",
    )
    async def unhide(self, ctx, channel, role_or_member):
        """unhide channel from role or member"""
        pass

    @command(
        name="hide",
        description="Hide a channel from a role or member",
    )
    @has_permissions(manage_channels=True)
    async def hide(self, ctx, channel, role_or_member):
        """hide channel from role or member"""
        pass

    @command(
        name="setup",
        description="Start process for setting up the moderation system",
    )
    @has_permissions(administrator=True)
    async def setup(self, ctx):
        """setup moderation system"""
        pass

    @command(
        name="rename",
        description="Assigns the mentioned user a new nickname in the guild",
    )
    async def rename(self, ctx, member, newnick):
        """rename a member"""
        pass

    @command(
        name="raid",
        description="Remove all members that joined in the time provided in the event of a raid",
    )
    async def raid(self, ctx, time, action, *, reason):
        """raid mode"""
        pass

    @command(
        name="topic",
        description="Change the current channel topic",
    )
    @has_permissions(manage_channels=True)
    async def topic(self, ctx, *, text):
        """change channel topic"""
        pass

    @command(
        name="naughty",
        description="Temporarily make a channel NSFW for 30 seconds",
    )
    @has_permissions(manage_channels=True)
    async def naughty(self, ctx, channel):
        """make channel nsfw temporarily"""
        pass

    @command(
        name="setupmute",
        description="Sets up muted roles and channel permissions",
    )
    @has_permissions(manage_guild=True, manage_channels=True)
    async def setupmute(self, ctx):
        """setup mute system"""
        pass

    @command(
        name="permissions",
        description="Check permissions for member or myself",
    )
    @has_permissions(manage_roles=True, manage_channels=True)
    async def permissions(self, ctx, member, channel):
        """check permissions"""
        pass

    @command(
        name="unlock",
        description="Unlock a channel",
    )
    @has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel, *, reason):
        """unlock a channel"""
        pass

    @command(
        name="unlock all",
        description="Unlocks every channel",
    )
    @has_permissions(manage_channels=True)
    async def unlock_all(self, ctx, *, reason):
        """unlock all channels"""
        pass
